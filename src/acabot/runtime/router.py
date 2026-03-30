"""runtime.router 负责把平台事件路由到 SessionConfig 决策主线.

当前 router 只做一件事:

- 把 `StandardEvent` 交给 `SessionRuntime`
- 把 session-config 决策收口成 `RouteDecision`
"""

from __future__ import annotations

from acabot.types import StandardEvent

from .contracts import (
    AdmissionDomainConfig,
    ComputerDomainConfig,
    ContextDomainConfig,
    ExtractionDomainConfig,
    PersistenceDomainConfig,
    RouteDecision,
    RoutingDomainConfig,
    SessionConfig,
    SurfaceConfig,
)
from .control.session_loader import StaticSessionConfigLoader
from .control.session_runtime import SessionRuntime


class RuntimeRouter:
    """SessionConfig 驱动的最小运行时路由器."""

    def __init__(
        self,
        *,
        default_agent_id: str = "default",
        session_runtime: SessionRuntime | None = None,
    ) -> None:
        """初始化最小路由器.

        Args:
            default_agent_id: 没有显式 session 文件时使用的默认 profile.
            session_runtime: 会话配置驱动的决策运行时.
        """

        self.default_agent_id = default_agent_id
        self.session_runtime = session_runtime or SessionRuntime(
            StaticSessionConfigLoader(_default_session_config(default_agent_id))
        )

    async def route(self, event: StandardEvent) -> RouteDecision:
        """把一条标准事件解析成 RouteDecision.

        Args:
            event: 已经标准化的平台事件.

        Returns:
            RouteDecision: 本次消息的路由结果.
        """

        facts = self.session_runtime.build_facts(event)
        session = self.session_runtime.load_session(facts)
        surface = self.session_runtime.resolve_surface(facts, session)
        routing = self.session_runtime.resolve_routing(facts, session, surface)
        admission = self.session_runtime.resolve_admission(facts, session, surface)
        context = self.session_runtime.resolve_context(facts, session, surface)
        persistence = self.session_runtime.resolve_persistence(facts, session, surface)
        extraction = self.session_runtime.resolve_extraction(facts, session, surface)
        computer = self.session_runtime.resolve_computer(facts, session, surface)
        return RouteDecision(
            thread_id=facts.thread_id,
            actor_id=facts.actor_id,
            agent_id=routing.agent_id,
            channel_scope=facts.channel_scope,
            run_mode=admission.mode,
            metadata={
                "bot_relation": event.bot_relation,
                "target_reasons": list(event.target_reasons),
                "mentions_self": event.mentions_self,
                "reply_targets_self": event.reply_targets_self,
                "surface_id": surface.surface_id,
                "surface_exists": surface.exists,
                "routing_agent_id": routing.agent_id,
                "routing_actor_lane": routing.actor_lane,
                "admission_mode": admission.mode,
                "event_persist": persistence.persist_event,
                "event_tags": list(extraction.tags),
                "computer_backend": computer.backend,
                "computer_allow_exec": computer.allow_exec,
                "computer_allow_sessions": computer.allow_sessions,
                "context_labels": list(context.context_labels),
                "context_retrieval_tags": list(context.retrieval_tags),
                "route_source": "session_config",
            },
            event_facts=facts,
            surface_resolution=surface,
            routing_decision=routing,
            admission_decision=admission,
            context_decision=context,
            persistence_decision=persistence,
            extraction_decision=extraction,
            computer_policy_decision=computer,
        )

    @staticmethod
    def build_actor_id(event: StandardEvent) -> str:
        """为发言用户构造 canonical actor_id.

        Args:
            event: 当前标准事件.

        Returns:
            str: canonical actor_id.
        """

        return f"{event.platform}:user:{event.source.user_id}"

    @staticmethod
    def build_channel_scope(event: StandardEvent) -> str:
        """根据平台和会话范围构造 channel_scope.

        Args:
            event: 当前标准事件.

        Returns:
            str: canonical channel_scope.
        """

        if event.is_group:
            return f"{event.platform}:group:{event.source.group_id}"
        return f"{event.platform}:user:{event.source.user_id}"

    @classmethod
    def build_thread_id(cls, event: StandardEvent) -> str:
        """构造 thread_id.

        Args:
            event: 当前标准事件.

        Returns:
            str: 当前消息落到的 thread_id.
        """

        return cls.build_channel_scope(event)


def _default_session_config(default_agent_id: str) -> SessionConfig:
    """构造 router 级最小内建 SessionConfig.

    Args:
        default_agent_id: 默认前台 agent.

    Returns:
        SessionConfig: 内建最小 session 配置.
    """

    def _surface() -> SurfaceConfig:
        return SurfaceConfig(
            routing=RoutingDomainConfig(default={"agent_id": default_agent_id}),
            admission=AdmissionDomainConfig(default={"mode": "respond"}),
            context=ContextDomainConfig(default={}),
            persistence=PersistenceDomainConfig(default={"persist_event": True}),
            extraction=ExtractionDomainConfig(default={"tags": []}),
            computer=ComputerDomainConfig(default={"backend": "host", "allow_exec": True, "allow_sessions": True}),
        )

    return SessionConfig(
        session_id="inline:default",
        template_id="inline_default",
        title="Inline Default Session",
        frontstage_agent_id=default_agent_id,
        selectors={},
        surfaces={
            "message.mention": _surface(),
            "message.reply_to_bot": _surface(),
            "message.command": _surface(),
            "message.private": _surface(),
            "message.plain": _surface(),
            "notice.default": _surface(),
        },
        metadata={"config_path": "<inline-session:router>"},
    )


__all__ = ["RuntimeRouter"]
