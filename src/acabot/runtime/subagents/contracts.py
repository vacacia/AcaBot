"""runtime.subagents.contracts 定义 subagent delegation 契约."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SubagentDelegationRequest:
    """一次 subagent delegation 的标准化请求."""

    skill_name: str
    parent_run_id: str
    parent_thread_id: str
    parent_agent_id: str
    actor_id: str
    channel_scope: str
    delegate_agent_id: str
    payload: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class SubagentDelegationResult:
    """一次 subagent delegation 的标准化返回值."""

    skill_name: str
    ok: bool
    delegated_run_id: str = ""
    summary: str = ""
    artifacts: list[dict[str, object]] = field(default_factory=list)
    error: str = ""
    metadata: dict[str, object] = field(default_factory=dict)
