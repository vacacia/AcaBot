"""runtime.router 负责把平台事件路由到运行时世界.

它解决的核心问题是, 一条外部 event 进入系统后, 应该落到哪个 thread, actor 和 agent 上.
"""

from __future__ import annotations

from typing import Callable

from acabot.types import StandardEvent

from .models import RouteDecision, RunMode


class RuntimeRouter:
    """最小运行时路由器.

    最基本的映射规则, 把 event 解析成 RouteDecision.
    """
    # TODO: profile binding, agent registry 和更复杂的 route policy.
    def __init__(
        self,
        *,
        default_agent_id: str = "default",
        decide_run_mode: Callable[[StandardEvent], RunMode] | None = None,
    ) -> None:
        """初始化最小路由器.

        Args:
            default_agent_id: 未命中特殊规则时使用的默认 agent.
            decide_run_mode: 可选回调, 用于决定这条消息是 `respond` 还是 `record_only`.
        """

        self.default_agent_id = default_agent_id
        self.decide_run_mode = decide_run_mode

    async def route(self, event: StandardEvent) -> RouteDecision:
        """把一条标准事件解析成 RouteDecision."""

        channel_scope = self.build_channel_scope(event)
        return RouteDecision(
            thread_id=self.build_thread_id(event), # 走哪个 thread
            actor_id=self.build_actor_id(event), # 谁发的消息
            agent_id=self.default_agent_id, # 用哪个 agent 处理
            channel_scope=channel_scope,
            run_mode=self._decide_run_mode(event),
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
