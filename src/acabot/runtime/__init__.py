"""核心运行时对象.

这里先集中暴露数据模型, router, manager, store interface.
后续 App, ThreadPipeline, Outbox 继续挂到这一层.
"""

from .agent_runtime import AgentRuntime
from .app import RuntimeApp
from .bootstrap import RuntimeComponents, build_runtime_components
from .memory_store import InMemoryMessageStore
from .legacy_agent_runtime import LegacyAgentRuntime
from .models import (
    AgentProfile,
    AgentRuntimeResult,
    BindingRule,
    DeliveryResult,
    DispatchReport,
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
from .router import RuntimeRouter
from .runs import InMemoryRunManager, RunManager, StoreBackedRunManager
from .sqlite_stores import SQLiteMessageStore, SQLiteRunStore, SQLiteThreadStore
from .stores import MessageStore, RunStore, ThreadStore
from .threads import InMemoryThreadManager, StoreBackedThreadManager, ThreadManager

__all__ = [
    "AgentRuntime",
    "AgentRuntimeResult",
    "AgentProfile",
    "AgentProfileRegistry",
    "BindingRule",
    "DeliveryResult",
    "DispatchReport",
    "build_runtime_components",
    "InMemoryRunManager",
    "InMemoryMessageStore",
    "InMemoryThreadManager",
    "LegacyAgentRuntime",
    "MessageRecord",
    "MessageStore",
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
]
