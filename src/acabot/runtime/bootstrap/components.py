"""runtime.bootstrap.components 定义 runtime 装配结果对象."""

from __future__ import annotations

from dataclasses import dataclass

from ..agent_runtime import AgentRuntime
from ..app import RuntimeApp
from ..computer import ComputerRuntime
from ..control.config_control_plane import RuntimeConfigControlPlane
from ..control.control_plane import RuntimeControlPlane
from ..gateway_protocol import GatewayProtocol
from ..inbound.image_context import ImageContextService
from ..inbound.message_preparation import MessagePreparationService
from ..memory.context_compactor import ContextCompactor
from ..memory.memory_broker import MemoryBroker
from ..memory.retrieval_planner import RetrievalPlanner
from ..memory.sticky_notes import StickyNotesService
from ..model.model_registry import FileSystemModelRegistryManager
from ..outbox import Outbox
from ..pipeline import ThreadPipeline
from ..plugin_manager import RuntimePluginManager
from ..control.profile_loader import ProfileLoader, PromptLoader
from ..references import ReferenceBackend
from ..router import RuntimeRouter
from ..skills import SkillCatalog
from ..storage.runs import RunManager
from ..storage.stores import ChannelEventStore, MemoryStore, MessageStore
from ..storage.threads import ThreadManager
from ..subagents import SubagentDelegationBroker, SubagentExecutorRegistry
from ..subagents.execution import LocalSubagentExecutionService
from ..tool_broker import ToolBroker
from ..approval_resumer import ApprovalResumer


@dataclass(slots=True)
class RuntimeComponents:
    """runtime 组装结果."""

    gateway: GatewayProtocol
    router: RuntimeRouter
    thread_manager: ThreadManager
    run_manager: RunManager
    channel_event_store: ChannelEventStore
    message_store: MessageStore
    memory_store: MemoryStore
    sticky_notes: StickyNotesService
    skill_catalog: SkillCatalog
    subagent_executor_registry: SubagentExecutorRegistry
    subagent_delegator: SubagentDelegationBroker
    subagent_execution_service: LocalSubagentExecutionService
    memory_broker: MemoryBroker
    context_compactor: ContextCompactor
    retrieval_planner: RetrievalPlanner
    model_registry_manager: FileSystemModelRegistryManager
    computer_runtime: ComputerRuntime
    image_context_service: ImageContextService
    message_preparation_service: MessagePreparationService
    reference_backend: ReferenceBackend
    plugin_manager: RuntimePluginManager
    control_plane: RuntimeControlPlane
    config_control_plane: RuntimeConfigControlPlane
    prompt_loader: PromptLoader
    profile_loader: ProfileLoader
    tool_broker: ToolBroker
    agent_runtime: AgentRuntime
    approval_resumer: ApprovalResumer
    outbox: Outbox
    pipeline: ThreadPipeline
    app: RuntimeApp


__all__ = ["RuntimeComponents"]
