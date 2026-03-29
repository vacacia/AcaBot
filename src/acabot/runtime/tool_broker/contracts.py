"""runtime.tool_broker.contracts 定义 tool broker 公开契约."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

from acabot.agent import Attachment, ToolExecutionResult, ToolSpec
from acabot.types import EventSource

from ..contracts import AgentProfile, PlannedAction

if TYPE_CHECKING:
    from ..computer import WorldView
    from ..model.model_agent_runtime import ToolRuntimeState


@dataclass(slots=True)
class ToolPolicyDecision:
    """ToolPolicy 的判定结果."""

    allowed: bool
    requires_approval: bool = False
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolAuditRecord:
    """一次工具执行的最小审计记录."""

    tool_call_id: str
    run_id: str
    tool_name: str
    status: Literal["started", "waiting_approval", "completed", "rejected", "failed"]
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "run_id": self.run_id,
            "name": self.tool_name,
            "status": self.status,
            "arguments": dict(self.arguments),
            "result": self.result,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ToolExecutionContext:
    """ToolBroker 执行工具时使用的上下文.

    Attributes:
        run_id (str): 当前 run_id.
        thread_id (str): 当前 thread_id.
        actor_id (str): 当前 actor_id.
        agent_id (str): 当前 agent_id.
        target (EventSource): 当前动作目标.
        profile (AgentProfile): 当前 profile.
        world_view (WorldView | None): 当前 run 的 Work World 视图.
        state (ToolRuntimeState | None): 当前 tool runtime 状态.
        visible_subagents (list[str]): 当前 run 真正允许访问的 subagent 列表.
        metadata (dict[str, Any]): 其他执行元数据.
    """

    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    target: EventSource
    profile: AgentProfile
    world_view: "WorldView | None" = None
    state: "ToolRuntimeState | None" = None
    visible_subagents: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    """ToolBroker 的标准化工具返回."""

    llm_content: str | list[dict[str, Any]] = ""
    attachments: list[Attachment] = field(default_factory=list)
    user_actions: list[PlannedAction] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def to_execution_result(self) -> ToolExecutionResult:
        return ToolExecutionResult(
            content=self.llm_content,
            attachments=list(self.attachments),
            raw=self.raw if self.raw is not None else dict(self.metadata),
        )


ToolHandler = Callable[[dict[str, Any], ToolExecutionContext], Awaitable[Any] | Any]


@dataclass(slots=True)
class RegisteredTool:
    """ToolBroker 内部持有的注册工具."""

    spec: ToolSpec
    handler: ToolHandler
    source: str = "runtime"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolReplayResult:
    """一次 approval replay 的最小结果."""

    ok: bool
    result: ToolResult
    audit_record: ToolAuditRecord | None = None
    status: Literal["completed", "rejected", "failed"] = "completed"


__all__ = [
    "RegisteredTool",
    "ToolAuditRecord",
    "ToolExecutionContext",
    "ToolHandler",
    "ToolPolicyDecision",
    "ToolReplayResult",
    "ToolResult",
]
