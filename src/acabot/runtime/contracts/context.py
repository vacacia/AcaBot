"""runtime.contracts.context 定义运行时执行现场和中间结果对象."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from acabot.types import Action, StandardEvent

from .common import ApprovalDecision, CommitWhen, RunStatus
from .records import PendingApprovalRecord, RunRecord, ThreadState
from .routing import ResolvedAgent, RouteDecision

if TYPE_CHECKING:
    from ..computer import AttachmentSnapshot, ComputerPolicy, WorkspaceState, WorldView
    from ..memory.memory_broker import (
        MemoryBlock,
        MemoryBrokerResult,
        SharedMemoryRetrievalRequest,
    )
    from ..model.model_registry import RuntimeModelRequest
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


@dataclass(slots=True)
class PlannedAction:
    """一次待出站动作的规划结果."""

    action_id: str
    action: Action
    thread_content: str | None = None
    commit_when: CommitWhen = "success"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PendingApproval:
    """待审批上下文."""

    approval_id: str
    reason: str
    tool_name: str
    tool_call_id: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    required_action_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ApprovalRequired(Exception):
    """表示当前 run 被工具打断并进入待审批状态."""

    def __init__(self, *, pending_approval: PendingApproval) -> None:
        super().__init__(pending_approval.reason)
        self.pending_approval = pending_approval


@dataclass(slots=True)
class AgentRuntimeResult:
    """一次 agent runtime 执行后的系统级结果."""

    status: Literal["completed", "waiting_approval", "failed"] = "completed"
    text: str = ""
    actions: list[PlannedAction] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model_used: str = ""
    error: str | None = None
    pending_approval: PendingApproval | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: Any = None


@dataclass(slots=True)
class DeliveryResult:
    """单个 action 的投递结果."""

    action_id: str
    ok: bool
    platform_message_id: str = ""
    error: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class OutboxItem:
    """Outbox 实际发送的最小单位."""

    thread_id: str
    run_id: str
    agent_id: str
    plan: PlannedAction
    origin_thread_id: str = ""
    destination_thread_id: str = ""
    destination_conversation_id: str = ""
    append_to_origin_thread: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """补齐 origin / destination contract 的默认值."""

        if not self.origin_thread_id:
            self.origin_thread_id = self.thread_id
        if not self.destination_thread_id:
            self.destination_thread_id = self.thread_id
        if not self.destination_conversation_id:
            channel_scope = str(self.metadata.get("channel_scope", "") or "").strip()
            self.destination_conversation_id = channel_scope or self.destination_thread_id


@dataclass(slots=True)
class DispatchReport:
    """一批出站动作的投递汇总结果."""

    results: list[DeliveryResult] = field(default_factory=list)
    delivered_items: list[OutboxItem] = field(default_factory=list)
    failed_action_ids: list[str] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return bool(self.failed_action_ids)


@dataclass(slots=True)
class ApprovalDecisionResult:
    """一次 approval decision 的返回结果."""

    run_id: str
    decision: ApprovalDecision
    ok: bool
    run_status: RunStatus | None = None
    message: str = ""
    pending_approval: PendingApprovalRecord | None = None


@dataclass(slots=True)
class RetrievalPlan:
    """进入模型前的 retrieval 计划与保留上下文.

    Attributes:
        requested_tags (list[str]): 本次 retrieval 的 tag 过滤条件.
        sticky_note_targets (list[str]): sticky note 允许注入的实体引用列表.
        retained_history (list[dict[str, Any]]): compaction 后保留下来的消息.
        dropped_messages (list[dict[str, Any]]): 被 compaction 丢弃的消息.
        working_summary (str): 当前 run 的有效 working summary.
        metadata (dict[str, Any]): 其他 planning 元数据.
    """

    requested_tags: list[str] = field(default_factory=list)
    sticky_note_targets: list[str] = field(default_factory=list)
    retained_history: list[dict[str, Any]] = field(default_factory=list)
    dropped_messages: list[dict[str, Any]] = field(default_factory=list)
    working_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RunStep:
    """run 内部的可审计步骤记录."""

    step_id: str
    run_id: str
    step_type: str
    status: str
    thread_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0


@dataclass(slots=True)
class ResolvedImageInput:
    """当前 run 内已解析完成的一张图片输入."""

    origin: str
    message_id: str
    attachment_index: int
    staged_path: str
    mime_type: str = ""
    caption: str = ""
    caption_status: str = "pending"


@dataclass(slots=True)
class ResolvedMessage:
    """当前 run 里已经补齐好的入站消息材料."""

    base_text: str
    reply_text: str = ""
    resolved_images: list[ResolvedImageInput] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryCandidate:
    """交给 memory 模块自己决定如何使用的一条候选材料."""

    kind: str
    text: str
    origin: str = "event"
    generated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MessageProjection:
    """同一条消息按不同用途生成的结果."""

    history_text: str
    model_content: str | list[dict[str, Any]]
    memory_candidates: list[MemoryCandidate] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OutboundMessageProjection:
    """同一条出站消息按不同用途生成的摘要结果.

    Attributes:
        fact_text (str): 写入 `MessageRecord.content_text` 的稳定事实摘要.
        thread_text (str): 写回 thread working memory 的连续性文本.
    """

    fact_text: str = ""
    thread_text: str = ""


@dataclass(slots=True)
class RunContext:
    """ThreadPipeline 执行一次 run 时共享的上下文对象."""

    run: RunRecord
    event: StandardEvent
    decision: RouteDecision
    thread: ThreadState
    agent: ResolvedAgent
    model_request: "RuntimeModelRequest | None" = None
    summary_model_request: "RuntimeModelRequest | None" = None
    event_facts: "EventFacts | None" = None
    surface_resolution: "SurfaceResolution | None" = None
    routing_decision: "RoutingDecision | None" = None
    admission_decision: "AdmissionDecision | None" = None
    context_decision: "ContextDecision | None" = None
    persistence_decision: "PersistenceDecision | None" = None
    extraction_decision: "ExtractionDecision | None" = None
    computer_policy_decision: "ComputerPolicyDecision | None" = None
    world_view: "WorldView | None" = None
    workspace_state: "WorkspaceState | None" = None
    attachment_snapshots: list["AttachmentSnapshot"] = field(default_factory=list)
    resolved_message: ResolvedMessage | None = None
    resolved_images: list[ResolvedImageInput] = field(default_factory=list)
    message_projection: MessageProjection | None = None
    computer_backend_kind: str = ""
    computer_policy_effective: "ComputerPolicy | None" = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    retrieval_plan: RetrievalPlan | None = None
    shared_memory_request: "SharedMemoryRetrievalRequest | None" = None
    memory_broker_result: "MemoryBrokerResult | None" = None
    memory_blocks: list["MemoryBlock"] = field(default_factory=list)
    memory_user_content: str = ""
    system_prompt: str = ""
    response: Any | None = None
    actions: list[PlannedAction] = field(default_factory=list)
    delivery_report: DispatchReport | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "AgentRuntimeResult",
    "ApprovalDecisionResult",
    "ApprovalRequired",
    "DeliveryResult",
    "DispatchReport",
    "MemoryCandidate",
    "MessageProjection",
    "OutboxItem",
    "PendingApproval",
    "PlannedAction",
    "ResolvedImageInput",
    "ResolvedMessage",
    "RetrievalPlan",
    "RunContext",
    "RunStep",
]
