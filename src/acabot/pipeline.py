"""Pipeline — 消息处理主线, 串联 Gateway/Session/Hook/Agent.

消息流:
    on_receive → pre_llm → [LLM] → post_llm → before_send → [send] → on_sent
    异常时 → on_error

Pipeline 是框架的中枢: Gateway 收到消息后调用 pipeline.process(event),
Pipeline 负责组装上下文、执行 hook 链、调用 Agent、发送回复.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .context import current_event
from .types import (
    StandardEvent, Action, ActionType,
    HookPoint, HookContext,
)
from .agent.base import BaseAgent
from .agent.response import AgentResponse
from .session.base import BaseSessionManager
from .session.memory import InMemorySessionManager
from .store.base import BaseMessageStore
from .store.null import NullMessageStore
from .bridge import SessionBridge
from .hook import HookRegistry, run_hooks

logger = logging.getLogger("acabot.pipeline")

_DEFAULT_ERROR_REPLY = "出了点问题, 请稍后再试"


class Pipeline:
    """消息处理主线.

    Gateway 收到原始消息 → 翻译为 StandardEvent → pipeline.process(event).
    Pipeline 内部按 hook 点依次执行, 最终通过 gateway 发送回复.

    Attributes:
        gateway: 网关实例, 只需要有 send(action) 方法.
        agent: LLM agent, 负责生成回复.
        system_prompt: 基础 system prompt, hook 可覆盖.
        session_mgr: 会话管理器, 默认 InMemorySessionManager.
        hooks: hook 注册表, 默认空.
        error_reply: Agent 出错时回复给用户的文案.
            None 表示不回复(只记日志), 有值则发送该文案.
        store: 消息持久化存储, 默认 NullMessageStore.
    """

    def __init__(
        self,
        gateway: Any,
        agent: BaseAgent,
        system_prompt: str = "",
        session_mgr: BaseSessionManager | None = None,
        hooks: HookRegistry | None = None,
        error_reply: str | None = _DEFAULT_ERROR_REPLY,
        store: BaseMessageStore | None = None,
    ) -> None:
        self.gateway = gateway
        self.agent = agent
        self.system_prompt = system_prompt
        self.session_mgr: BaseSessionManager = session_mgr or InMemorySessionManager()
        self.hooks = hooks or HookRegistry()
        self.error_reply = error_reply
        self.store: BaseMessageStore = store or NullMessageStore()
        # 同 session 串行, 跨 session 并行
        self._session_locks: dict[str, asyncio.Lock] = {}

    # region 入口
    async def process(self, event: StandardEvent) -> None:
        """处理一条消息 — Pipeline 唯一的公开入口.

        设置 contextvars, 获取 per-session 锁, 然后执行主线.

        Args:
            event: Gateway 翻译后的标准事件.
        """
        token = current_event.set(event)
        try:
            lock = self._session_locks.setdefault(
                event.session_key, asyncio.Lock(),
            )
            async with lock:
                await self._run_pipeline(event)
        finally:
            current_event.reset(token)

    # region 主线
    async def _run_pipeline(self, event: StandardEvent) -> None:
        """主线逻辑:
        on_receive → pre_llm → LLM → post_llm → before_send → send → on_sent.

        session 写入全由 bridge 管理, Pipeline 只操作 ctx.messages(临时副本).
        """
        session = await self.session_mgr.get_or_create(event.session_key)
        bridge = SessionBridge(
            gateway=self.gateway, session=session,
            store=self.store, session_key=event.session_key,
        )

        ctx = HookContext(
            event=event,
            session=session,
            messages=list(session.messages),
            system_prompt=self._build_system_prompt(session),
        )

        try:
            # --- on_receive ---
            result = await run_hooks(self.hooks, HookPoint.ON_RECEIVE, ctx)
            if result.action == "abort":
                return
            skip_llm = result.action == "skip_llm"
            if skip_llm:
                ctx.actions = list(result.early_response or [])

            # 记录用户消息(即使 skip_llm 也会记录, 保持上下文完整)
            await bridge.record_incoming(event)
            ctx.messages.append({"role": "user", "content": event.text})

            if not skip_llm:
                # --- pre_llm ---
                result = await run_hooks(self.hooks, HookPoint.PRE_LLM, ctx)
                if result.action == "skip_llm":
                    skip_llm = True
                    ctx.actions = list(result.early_response or [])

            # LLM 原始回复
            # session 存储原始消息; store 存储实际信息(分段/hook处理之后的消息)
            llm_response_text: str | None = None

            if not skip_llm:
                # --- LLM 调用 ---
                response = await self.agent.run(
                    system_prompt=ctx.system_prompt,
                    messages=ctx.messages,
                    model=ctx.model,
                )
                ctx.response = response

                if response.error:
                    logger.error(f"Agent error: {response.error}")
                    if self.error_reply:
                        ctx.actions = [Action(
                            action_type=ActionType.SEND_TEXT,
                            target=event.source,
                            payload={"text": self.error_reply},
                        )]
                    else:
                        return
                else:
                    ctx.actions = self._build_actions(event, response)
                    llm_response_text = response.text
                    # 只写 ctx.messages(给 post_llm hook 看)
                    ctx.messages.append(
                        {"role": "assistant", "content": response.text},
                    )

            # --- post_llm ---
            await run_hooks(self.hooks, HookPoint.POST_LLM, ctx)

            # --- before_send ---
            result = await run_hooks(self.hooks, HookPoint.BEFORE_SEND, ctx)
            if result.action == "abort":
                return

            # --- send (通过 bridge, 自动写入 session + store) ---
            for action in ctx.actions:
                await bridge.send(
                    action, session_content=llm_response_text,
                )

            # --- on_sent ---
            await run_hooks(self.hooks, HookPoint.ON_SENT, ctx)

        except Exception as e:
            logger.exception(f"Pipeline error: {e}")
            ctx.metadata["error"] = str(e)
            await run_hooks(self.hooks, HookPoint.ON_ERROR, ctx)

    # region 构建 system prompt
    def _build_system_prompt(self, session: Any) -> str:
        """拼接 system prompt + session 摘要.

        如果 session 有 summary(由 ContextCompressorHook 生成),
        追加到基础 system_prompt 末尾.
        """
        base = self.system_prompt
        summary = getattr(session, "summary", None)
        if summary and summary.strip():
            separator = "\n\n---\n" if base else ""
            base += f"{separator}以下是之前部分对话的压缩摘要:\n{summary}"
        return base

    # region 构建 Action
    def _build_actions(
        self, event: StandardEvent, response: AgentResponse,
    ) -> list[Action]:
        """把 AgentResponse 转成 Action 列表.

        文本 → SEND_TEXT, 附件 → 各自一条 SEND_SEGMENTS.
        如果既没文本也没附件, 返回空列表(不发送).

        Args:
            event: 原始事件, 用于获取 target.
            response: Agent 返回的结果.

        Returns:
            待发送的 Action 列表.
        """
        actions: list[Action] = []

        if response.text:
            actions.append(Action(
                action_type=ActionType.SEND_TEXT,
                target=event.source,
                payload={"text": response.text},
            ))

        for att in response.attachments:
            if att.type == "image":
                seg = {"type": "image", "data": {"url": att.url or att.data}}
            else:
                seg = {"type": "text", "data": {"text": f"[{att.type}: {att.url}]"}}
            actions.append(Action(
                action_type=ActionType.SEND_SEGMENTS,
                target=event.source,
                payload={"segments": [seg]},
            ))

        return actions
