"""runtime.router 负责把平台事件路由到运行时世界.

它解决的核心问题是, 一条外部 event 进入系统后, 应该落到哪个 thread, actor 和 agent 上.
"""

from __future__ import annotations

from typing import Any, Callable

from acabot.types import StandardEvent

from .models import RouteDecision, RunMode


class RuntimeRouter:
    """最小运行时路由器.

    最基本的映射规则, 把 event 解析成 RouteDecision.
    """
    def __init__(
        self,
        *,
        default_agent_id: str = "default",
        decide_run_mode: Callable[[StandardEvent], RunMode] | None = None,
        resolve_agent: Callable[..., tuple[str, dict[str, Any]]] | None = None,
    ) -> None:
        """初始化最小路由器.

        Args:
            default_agent_id: 未命中特殊规则时使用的默认 agent.
            decide_run_mode: 可选回调, 用于决定这条消息是 `respond` 还是 `record_only`.
            resolve_agent: 可选回调, 用于根据 canonical id 解析最终 agent_id 和 binding metadata.
        """

        self.default_agent_id = default_agent_id
        self.decide_run_mode = decide_run_mode
        self.resolve_agent = resolve_agent

    async def route(self, event: StandardEvent) -> RouteDecision:
        """把一条标准事件解析成 RouteDecision.

        Args:
            event: 已经标准化的平台事件.

        Returns:
            本次消息的 RouteDecision.
        """

        thread_id = self.build_thread_id(event)
        actor_id = self.build_actor_id(event)
        channel_scope = self.build_channel_scope(event)
        agent_id, metadata = self._resolve_agent(
            event=event,
            thread_id=thread_id,
            actor_id=actor_id,
            channel_scope=channel_scope,
        )
        return RouteDecision(
            thread_id=thread_id, # 走哪个 thread
            actor_id=actor_id, # 谁发的消息
            agent_id=agent_id, # 用哪个 agent 处理
            channel_scope=channel_scope,
            run_mode=self._decide_run_mode(event),
            metadata=metadata,
        )

    @staticmethod
    def build_actor_id(event: StandardEvent) -> str:
        """为发言用户构造的 actor_id."""

        return f"{event.platform}:user:{event.source.user_id}"

    @staticmethod
    def build_channel_scope(event: StandardEvent) -> str:
        """根据平台和会话范围构造 channel_scope."""

        if event.is_group:
            return f"{event.platform}:group:{event.source.group_id}"
        return f"{event.platform}:user:{event.source.user_id}"

    @classmethod
    def build_thread_id(cls, event: StandardEvent) -> str:
        """构造 thread_id.

        当前最小实现里, channel_scope 和 thread_id 先保持一致.
        """

        return cls.build_channel_scope(event)

    def _decide_run_mode(self, event: StandardEvent) -> RunMode:
        """决定本次 run 的模式.

        默认全部进入 `respond`.
        当外部提供自定义回调时, 由回调决定最终模式.
        """

        if self.decide_run_mode is None:
            return "respond"
        return self.decide_run_mode(event)

    def _resolve_agent(
        self,
        *,
        event: StandardEvent,
        thread_id: str,
        actor_id: str,
        channel_scope: str,
    ) -> tuple[str, dict[str, Any]]:
        """解析当前消息应该绑定的 agent.

        Args:
            event: 当前标准化消息事件.
            thread_id: 当前消息所属的 thread_id.
            actor_id: 当前消息发送方的 actor_id.
            channel_scope: 当前消息所在 channel_scope.

        Returns:
            一个二元组.
            第一个值是最终的 agent_id.
            第二个值是写回 RouteDecision.metadata 的 binding 信息.
        """

        if self.resolve_agent is not None:
            return self.resolve_agent(
                event=event,
                thread_id=thread_id,
                actor_id=actor_id,
                channel_scope=channel_scope,
            )
        return self.default_agent_id, {
            "binding_kind": "default",
            "binding_rule_id": "",
            "binding_priority": -1,
            "binding_match_keys": [],
        }
