"""runtime.contracts.routing 定义路由主线仍需使用的稳定对象.

这个模块保留两类契约:

- `ResolvedAgent`: 当前 run 使用的前台 agent 快照
- `RouteDecision`: router 输出给 app / pipeline 的统一决策对象
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .common import RunMode
from .session_config import (
    AdmissionDecision,
    ComputerPolicyDecision,
    ContextDecision,
    EventFacts,
    ExtractionDecision,
    PersistenceDecision,
    RoutingDecision,
    SurfaceResolution,
)

if TYPE_CHECKING:
    from ..computer import ComputerPolicy
    from .session_agent import SessionAgent


@dataclass(slots=True)
class ResolvedAgent:
    """当前 run 使用的 agent 配置快照.

    Attributes:
        agent_id (str): 当前 agent 的稳定 ID.
        prompt_ref (str): 关联的 prompt 引用.
        enabled_tools (list[str]): 当前 agent 允许的工具列表.
        skills (list[str]): 当前 agent 默认可见 skill 列表.
        visible_subagents (list[str]): 当前 agent 默认可见 subagent 列表.
        computer_policy (ComputerPolicy | None): 当前 agent 默认 computer policy.
        config (dict[str, Any]): 原始配置补充字段.
    """

    agent_id: str
    prompt_ref: str
    name: str = ""
    enabled_tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    visible_subagents: list[str] = field(default_factory=list)
    computer_policy: "ComputerPolicy | None" = None
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_session_agent(cls, session_agent: "SessionAgent") -> "ResolvedAgent":
        """把 session 真源对象投影成当前 run 的只读 agent 快照."""

        return cls(
            agent_id=session_agent.agent_id,
            prompt_ref=session_agent.prompt_ref,
            name=session_agent.agent_id,
            enabled_tools=list(session_agent.visible_tools),
            skills=list(session_agent.visible_skills),
            visible_subagents=list(session_agent.visible_subagents),
            computer_policy=session_agent.computer_policy,
            config=dict(session_agent.config),
        )


# TODO(session-owned-agent hard cut): bootstrap/control-plane 清完后删掉这个旧别名.
AgentProfile = ResolvedAgent


@dataclass(slots=True)
class RouteDecision:
    """router 的统一解析结果.

    Attributes:
        thread_id (str): 当前消息落到的 thread.
        actor_id (str): 当前消息的 canonical actor.
        agent_id (str): 当前消息最终使用的前台 agent ID.
        channel_scope (str): 当前消息的 canonical 会话范围.
        run_mode (RunMode): 当前消息的准入模式.
        metadata (dict[str, Any]): 供 app / store / UI 使用的轻量元数据.
        event_facts (EventFacts | None): 标准化后的输入事实.
        surface_resolution (SurfaceResolution | None): 当前命中的 surface.
        routing_decision (RoutingDecision | None): routing 决策结果.
        admission_decision (AdmissionDecision | None): admission 决策结果.
        context_decision (ContextDecision | None): context 决策结果.
        persistence_decision (PersistenceDecision | None): persistence 决策结果.
        extraction_decision (ExtractionDecision | None): extraction 决策结果.
        computer_policy_decision (ComputerPolicyDecision | None): computer 决策结果.
    """

    thread_id: str
    actor_id: str
    agent_id: str
    channel_scope: str
    run_mode: RunMode = "respond"
    metadata: dict[str, Any] = field(default_factory=dict)
    event_facts: EventFacts | None = None
    surface_resolution: SurfaceResolution | None = None
    routing_decision: RoutingDecision | None = None
    admission_decision: AdmissionDecision | None = None
    context_decision: ContextDecision | None = None
    persistence_decision: PersistenceDecision | None = None
    extraction_decision: ExtractionDecision | None = None
    computer_policy_decision: ComputerPolicyDecision | None = None


__all__ = ["AgentProfile", "ResolvedAgent", "RouteDecision"]
