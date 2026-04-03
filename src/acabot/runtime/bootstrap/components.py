"""runtime.bootstrap.components 定义 runtime 装配结果对象."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..agent_runtime import AgentRuntime
from ..app import RuntimeApp
from ..backend.bridge import BackendBridge
from ..backend.mode_registry import BackendModeRegistry
from ..computer import ComputerRuntime
from ..context_assembly import ContextAssembler, PayloadJsonWriter
from ..control.config_control_plane import RuntimeConfigControlPlane
from ..control.control_plane import RuntimeControlPlane
from ..gateway_protocol import GatewayProtocol
from ..inbound.image_context import ImageContextService
from ..inbound.message_preparation import MessagePreparationService
from ..memory.context_compactor import ContextCompactor
from ..memory.file_backed import StickyNoteFileStore
from ..memory.long_term_ingestor import LongTermMemoryIngestor
from ..memory.memory_broker import MemoryBroker
from ..memory.retrieval_planner import RetrievalPlanner
from ..memory.sticky_notes import StickyNoteService
from ..model.model_registry import FileSystemModelRegistryManager
from ..outbox import Outbox
from ..pipeline import ThreadPipeline
from ..plugin_reconciler import PluginReconciler
from ..plugin_runtime_host import PluginRuntimeHost
from ..plugin_package import PackageCatalog
from ..plugin_spec import SpecStore
from ..plugin_status import StatusStore
from ..render import RenderService
from ..contracts import ResolvedAgent, RouteDecision
from ..control.prompt_loader import PromptLoader
from ..router import RuntimeRouter
from ..skills import SkillCatalog
from ..soul import SoulSource
from ..storage.runs import RunManager
from ..storage.stores import ChannelEventStore, MessageStore
from ..storage.threads import ThreadManager
from ..subagents import SubagentCatalog, SubagentDelegationBroker
from ..subagents.execution import LocalSubagentExecutionService
from ..tool_broker import ToolBroker
from ..approval_resumer import ApprovalResumer
from ..scheduler import RuntimeScheduler


@dataclass(slots=True)
class RuntimeComponents:
    """runtime 组装结果."""

    gateway: GatewayProtocol
    router: RuntimeRouter
    thread_manager: ThreadManager
    run_manager: RunManager
    channel_event_store: ChannelEventStore
    message_store: MessageStore
    soul_source: SoulSource
    sticky_notes_source: StickyNoteFileStore
    sticky_notes: StickyNoteService
    skill_catalog: SkillCatalog
    subagent_catalog: SubagentCatalog
    subagent_delegator: SubagentDelegationBroker
    subagent_execution_service: LocalSubagentExecutionService
    memory_broker: MemoryBroker
    context_compactor: ContextCompactor
    retrieval_planner: RetrievalPlanner
    context_assembler: ContextAssembler
    payload_json_writer: PayloadJsonWriter
    model_registry_manager: FileSystemModelRegistryManager
    computer_runtime: ComputerRuntime
    image_context_service: ImageContextService
    message_preparation_service: MessagePreparationService
    plugin_reconciler: PluginReconciler
    plugin_runtime_host: PluginRuntimeHost
    plugin_catalog: PackageCatalog
    plugin_spec_store: SpecStore
    plugin_status_store: StatusStore
    control_plane: RuntimeControlPlane
    config_control_plane: RuntimeConfigControlPlane
    prompt_loader: PromptLoader
    agent_loader: Callable[[RouteDecision], ResolvedAgent]
    tool_broker: ToolBroker
    agent_runtime: AgentRuntime
    approval_resumer: ApprovalResumer
    outbox: Outbox
    render_service: RenderService
    pipeline: ThreadPipeline
    backend_bridge: BackendBridge
    backend_mode_registry: BackendModeRegistry
    app: RuntimeApp
    long_term_memory_ingestor: LongTermMemoryIngestor | None = None
    scheduler: RuntimeScheduler | None = None


__all__ = ["RuntimeComponents"]
