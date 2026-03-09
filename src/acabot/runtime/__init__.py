"""核心运行时对象.

这里先集中暴露数据模型, router, manager, store interface.
后续 App, ThreadPipeline, Outbox 继续挂到这一层.
"""

from .agent_runtime import AgentRuntime
from .app import RuntimeApp
from .models import (
    AgentProfile,
    AgentRuntimeResult,
    DeliveryResult,
    DispatchReport,
    MessageRecord,
    OutboxItem,
    PendingApproval,
    PlannedAction,
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
from .router import RuntimeRouter
from .runs import InMemoryRunManager, RunManager
from .stores import MessageStore, RunStore, ThreadStore
from .threads import InMemoryThreadManager, ThreadManager

__all__ = [
    "AgentRuntime",
    "AgentRuntimeResult",
    "AgentProfile",
    "DeliveryResult",
    "DispatchReport",
    "InMemoryRunManager",
    "InMemoryThreadManager",
    "MessageRecord",
    "MessageStore",
    "OutboxItem",
    "PendingApproval",
    "PlannedAction",
    "RouteDecision",
    "RuntimeApp",
    "RunContext",
    "RunManager",
    "RunRecord",
    "RunStatus",
    "RunStep",
    "RunStore",
    "RuntimeRouter",
    "Outbox",
    "ThreadPipeline",
    "ThreadManager",
    "ThreadRecord",
    "ThreadState",
    "ThreadStore",
]
