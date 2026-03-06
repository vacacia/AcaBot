"""BotContext — 插件与框架交互的唯一入口(门面模式)."""

from __future__ import annotations

from typing import Any

from acabot.gateway import BaseGateway
from acabot.session import BaseSessionManager
from acabot.store import BaseMessageStore, NullMessageStore
from acabot.agent import BaseAgent, AgentResponse
from acabot.types import Action, ActionType, EventSource, MsgSegment
from acabot.config import Config


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

    async def send(self, action: Action) -> dict[str, Any] | None:
        """委托 Gateway 发送动作(完整控制, 自行构造 Action)."""
        return await self.gateway.send(action)

    # region 高频便捷方法

    async def send_text(
        self, target: EventSource, text: str, reply_to: str | None = None,
    ) -> dict[str, Any] | None:
        """发送纯文字消息.

        Args:
            target: 发送目标, 通常用 event.source.
            text: 消息文本.
            reply_to: 引用回复的消息 ID, None 则为普通发送.
        """
        return await self.send(Action(
            action_type=ActionType.SEND_TEXT,
            target=target,
            payload={"text": text},
            reply_to=reply_to,
        ))

    async def send_segments(
        self, target: EventSource, segments: list[MsgSegment], reply_to: str | None = None,
    ) -> dict[str, Any] | None:
        """发送富文本消息(图片/at/混合内容等).

        Args:
            target: 发送目标.
            segments: 消息段列表.
            reply_to: 引用回复的消息 ID.
        """
        return await self.send(Action(
            action_type=ActionType.SEND_SEGMENTS,
            target=target,
            payload={"segments": [{"type": s.type, "data": s.data} for s in segments]},
            reply_to=reply_to,
        ))

    async def reply_text(
        self, target: EventSource, text: str, message_id: str,
    ) -> dict[str, Any] | None:
        """引用回复一条文字消息(send_text + reply_to 的快捷方式).

        Args:
            target: 发送目标.
            text: 回复文本.
            message_id: 要引用的消息 ID.
        """
        return await self.send_text(target, text, reply_to=message_id)

    # endregion

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
        self, session_key: str, limit: int = 100, since: int | None = None,
    ) -> list[Any]:
        """委托 Store 查询历史消息."""
        return await self.store.get_messages(session_key, limit=limit, since=since)

    def get_config(self, plugin_name: str) -> dict[str, Any]:
        """获取指定插件的配置段."""
        return self.config.get_plugin_config(plugin_name)
