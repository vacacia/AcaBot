"""BotContext — 插件与框架交互的唯一入口.

插件通过 BotContext 发消息/读配置/调 LLM, 不直接依赖具体实现.
所有发送接口自动记录到 session + store, 没有"裸发"接口.
详见 architecture/message-flow-and-persistence.md.
"""

from __future__ import annotations

import logging
from typing import Any

from acabot.gateway import BaseGateway
from acabot.session import BaseSessionManager
from acabot.store import BaseMessageStore, NullMessageStore
from acabot.agent import BaseAgent, AgentResponse
from acabot.bridge import SessionBridge
from acabot.types import Action, ActionType, EventSource, MsgSegment
from acabot.config import Config

logger = logging.getLogger("acabot.context")


class BotContext:
    """框架暴露给插件的统一接口.

    插件只通过 BotContext 和框架交互, 不直接依赖任何具体实现.
    Optional 组件(store, kv 等)使用 Null Object, 插件无需做 None 检查.

    Attributes:
        gateway: 发消息/调用平台 API.
        session_mgr: 查/改会话.
        agent: 主 Agent(带 tool loop).
        config: 读配置.
        store: 消息持久化存储, 默认 NullMessageStore.
        kv: 键值存储(v0.4).
        llm_registry: 多模型注册表(v0.4).
        scheduler: 定时调度(v0.4).
    """

    def __init__(
        self,
        gateway: BaseGateway,
        session_mgr: BaseSessionManager,
        agent: BaseAgent,
        config: Config,
        store: BaseMessageStore | None = None,
        kv: Any = None,
        llm_registry: Any = None,
        scheduler: Any = None,
    ):
        self.gateway = gateway
        self.session_mgr = session_mgr
        self.agent = agent
        self.config = config
        self.store: BaseMessageStore = store or NullMessageStore()
        self.kv = kv
        self.llm_registry = llm_registry
        self.scheduler = scheduler

    # region 发送接口

    async def send_text(
        self,
        target: EventSource,
        text: str,
        session_key: str,
        *,
        reply_to: str | None = None,
    ) -> dict[str, Any] | None:
        """发送纯文字消息, 自动记录到 session + store.

        Args:
            target: 发送目标, 通常用 event.source.
            text: 消息文本.
            session_key: 目标会话标识.
            reply_to: 引用回复的消息 ID, None 则为普通发送.

        Returns:
            gateway 返回的结果(含 message_id 等), 失败返回 None.
        """
        action = Action(
            action_type=ActionType.SEND_TEXT,
            target=target,
            payload={"text": text},
            reply_to=reply_to,
        )
        return await self._send_with_record(action, session_key)

    async def send_segments(
        self,
        target: EventSource,
        segments: list[MsgSegment],
        session_key: str,
        *,
        reply_to: str | None = None,
    ) -> dict[str, Any] | None:
        """发送富文本消息(图片/at/混合内容等), 自动记录到 session + store.

        Args:
            target: 发送目标.
            segments: 消息段列表.
            session_key: 目标会话标识.
            reply_to: 引用回复的消息 ID.

        Returns:
            gateway 返回的结果, 失败返回 None.
        """
        action = Action(
            action_type=ActionType.SEND_SEGMENTS,
            target=target,
            payload={"segments": [{"type": s.type, "data": s.data} for s in segments]},
            reply_to=reply_to,
        )
        return await self._send_with_record(action, session_key)

    async def reply_text(
        self,
        target: EventSource,
        text: str,
        message_id: str,
        session_key: str,
    ) -> dict[str, Any] | None:
        """引用回复一条文字消息(send_text + reply_to 的快捷方式).

        Args:
            target: 发送目标.
            text: 回复文本.
            message_id: 要引用的消息 ID.
            session_key: 目标会话标识.

        Returns:
            gateway 返回的结果, 失败返回 None.
        """
        return await self.send_text(
            target, text, session_key, reply_to=message_id,
        )

    # endregion

    # region 内部: 带记录的发送
    async def _send_with_record(
        self, action: Action, session_key: str,
    ) -> dict[str, Any] | None:
        """通过 SessionBridge 发送并记录到 session + store.

        Args:
            action: 要发送的动作.
            session_key: 目标会话标识.

        Returns:
            gateway 返回结果, 失败返回 None.
        """
        session = await self.session_mgr.get_or_create(session_key)
        bridge = SessionBridge(
            gateway=self.gateway, session=session,
            store=self.store, session_key=session_key,
        )
        return await bridge.send(action)
    # endregion

    # region 其他接口

    async def llm_call(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> AgentResponse:
        """委托 Agent 执行一次 LLM 调用."""
        return await self.agent.run(
            system_prompt=system_prompt,
            messages=messages,
            model=model,
        )

    async def get_messages(
        self, session_key: str, limit: int | None = None, since: int | None = None,
    ) -> list[Any]:
        """委托 Store 查询历史消息."""
        return await self.store.get_messages(session_key, limit=limit, since=since)

    def get_config(self, plugin_name: str) -> dict[str, Any]:
        """获取指定插件的配置段."""
        return self.config.get_plugin_config(plugin_name)

    # endregion
