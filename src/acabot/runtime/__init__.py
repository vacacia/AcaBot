"""核心运行时对象.

这里先集中暴露数据模型, router, manager, store interface.
后续 App, ThreadPipeline, Outbox 继续挂到这一层.
"""

from .agent_runtime import AgentRuntime
from .approval_resumer import (
    ApprovalResumeResult,
    ApprovalResumer,
    NoopApprovalResumer,
)
from .app import RuntimeApp
from .bootstrap import RuntimeComponents, build_runtime_components
from .event_store import InMemoryChannelEventStore
from .memory_store import InMemoryMessageStore
from .legacy_agent_runtime import LegacyAgentRuntime
from .model_agent_runtime import (
    ModelAgentRuntime,
    ToolRuntime,
    ToolRuntimeResolver,
    ToolRuntimeState,
)
from .models import (
    AgentProfile,
    ApprovalRequired,
    ApprovalDecisionResult,
    AgentRuntimeResult,
    BindingRule,
    ChannelEventRecord,
    DeliveryResult,
    DispatchReport,
    InboundRule,
    MessageRecord,
    OutboxItem,
    PendingApproval,
    PendingApprovalRecord,
    PlannedAction,
    RecoveryReport,
    RouteDecision,
    RunContext,
    RunRecord,
    RunStatus,
    RunStep,
    ThreadRecord,
    ThreadState,
)
from .outbox import Outbox
from .pipeline import ThreadPipeline
from .profile_loader import (
    AgentProfileRegistry,
    ProfileLoader,
    PromptLoader,
    StaticProfileLoader,
    StaticPromptLoader,
)
from .router import InboundRuleRegistry, RuntimeRouter
from .runs import InMemoryRunManager, RunManager, StoreBackedRunManager
from .sqlite_stores import (
    SQLiteChannelEventStore,
    SQLiteMessageStore,
    SQLiteRunStore,
    SQLiteThreadStore,
)
from .stores import ChannelEventStore, MessageStore, RunStore, ThreadStore
from .tool_broker import (
    AllowAllToolPolicy,
    InMemoryToolAudit,
    RegisteredTool,
    ToolBroker,
    ToolAudit,
    ToolAuditRecord,
    ToolPolicy,
    ToolPolicyDecision,
    ToolExecutionContext,
    ToolResult,
)
from .threads import InMemoryThreadManager, StoreBackedThreadManager, ThreadManager

__all__ = [
    "AgentRuntime",
    "AgentRuntimeResult",
    "AgentProfile",
    "AgentProfileRegistry",
    "ApprovalRequired",
    "ApprovalDecisionResult",
    "ApprovalResumeResult",
    "ApprovalResumer",
    "BindingRule",
    "ChannelEventRecord",
    "ChannelEventStore",
    "DeliveryResult",
    "DispatchReport",
    "build_runtime_components",
    "InboundRule",
    "InboundRuleRegistry",
    "InMemoryChannelEventStore",
    "InMemoryRunManager",
    "InMemoryMessageStore",
    "InMemoryThreadManager",
    "LegacyAgentRuntime",
    "MessageRecord",
    "MessageStore",
    "ModelAgentRuntime",
    "NoopApprovalResumer",
    "OutboxItem",
    "PendingApproval",
    "PendingApprovalRecord",
    "PlannedAction",
    "ProfileLoader",
    "PromptLoader",
    "RouteDecision",
    "RecoveryReport",
    "RuntimeComponents",
    "RuntimeApp",
    "RunContext",
    "RunManager",
    "RunRecord",
    "RunStatus",
    "RunStep",
    "RunStore",
    "RuntimeRouter",
    "Outbox",
    "SQLiteChannelEventStore",
    "SQLiteMessageStore",
    "SQLiteRunStore",
    "SQLiteThreadStore",
    "StaticProfileLoader",
    "StaticPromptLoader",
    "StoreBackedRunManager",
    "StoreBackedThreadManager",
    "ThreadPipeline",
    "ThreadManager",
    "ThreadRecord",
    "ThreadState",
    "ThreadStore",
    "AllowAllToolPolicy",
    "InMemoryToolAudit",
    "ToolRuntime",
    "ToolRuntimeState",
    "ToolRuntimeResolver",
    "RegisteredTool",
    "ToolBroker",
    "ToolAudit",
    "ToolAuditRecord",
    "ToolPolicy",
    "ToolPolicyDecision",
    "ToolExecutionContext",
    "ToolResult",
]
