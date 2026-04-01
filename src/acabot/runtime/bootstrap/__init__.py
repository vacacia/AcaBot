r"""runtime.bootstrap 提供 runtime 默认组装入口."""

from __future__ import annotations

from acabot.agent import BaseAgent
from acabot.config import Config

from ..agent_runtime import AgentRuntime
from ..approval_resumer import ApprovalResumer, ToolApprovalResumer
from ..app import RuntimeApp
from ..backend.bridge import BackendBridge
from ..backend.mode_registry import BackendModeRegistry
from ..backend.pi_adapter import PiBackendAdapter
from ..backend.session import (
    BackendSessionBindingStore,
    BackendSessionService,
    ConfiguredBackendSessionService,
)
from ..builtin_tools import register_core_builtin_tools
from ..context_assembly import ContextAssembler
from ..contracts import ResolvedAgent
from ..control.config_control_plane import RuntimeConfigControlPlane
from ..control.control_plane import RuntimeControlPlane
from ..gateway_protocol import GatewayProtocol
from ..inbound.image_context import ImageContextService
from ..inbound.message_preparation import MessagePreparationService
from ..inbound.message_projection import MessageProjectionService
from ..inbound.message_resolution import MessageResolutionService
from ..memory.conversation_facts import StoreBackedConversationFactReader
from ..memory.file_backed import StickyNoteFileStore
from ..memory.long_term_ingestor import LongTermMemoryIngestor
from ..memory.sticky_note_renderer import StickyNoteRenderer
from ..memory.sticky_notes import StickyNoteService
from ..soul import SoulSource
from ..model.model_agent_runtime import ModelAgentRuntime
from ..model.model_targets import MutableModelTargetCatalog, build_agent_model_targets
from ..outbox import Outbox
from ..pipeline import ThreadPipeline
from ..plugin_manager import (
    RuntimePlugin,
    RuntimePluginManager,
    load_runtime_plugins_from_config,
    load_runtime_plugins_from_config_with_failures,
)
from ..control.prompt_loader import PromptLoader, ReloadablePromptLoader
from ..router import RuntimeRouter
from ..subagents import SubagentDelegationBroker
from ..subagents.execution import LocalSubagentExecutionService
from ..tool_broker import ToolBroker
from .builders import (
    build_builtin_runtime_plugins,
    build_channel_event_store,
    build_computer_runtime,
    build_context_compactor,
    build_default_computer_policy,
    build_long_term_memory_ingestor,
    build_long_term_memory_source,
    build_long_term_memory_store,
    build_long_term_memory_write_port,
    build_memory_broker,
    build_message_store,
    build_model_registry_manager,
    build_payload_json_writer,
    build_reference_backend,
    build_retrieval_planner,
    build_run_manager,
    build_skill_catalog,
    build_subagent_catalog,
    build_thread_manager,
)
from .config import resolve_runtime_path
from .components import RuntimeComponents
from .loaders import (
    build_default_frontstage_agent,
    build_prompt_refs,
    build_prompt_loader,
    build_session_bundle_loader,
    build_session_runtime,
)


def _resolve_shared_admin_actor_ids(
    *,
    backend_conf: dict[str, object],
) -> set[str]:
    """解析共享管理员列表.

    Args:
        backend_conf: `runtime.backend` 配置块.

    Returns:
        规范化后的管理员 actor 集合.
    """

    return {
        str(value)
        for value in list(backend_conf.get("admin_actor_ids", []) or [])
        if str(value)
    }


def build_runtime_components(
    config: Config,
    *,
    gateway: GatewayProtocol,
    agent: BaseAgent,
    message_store=None,
    router=None,
    thread_manager=None,
    run_manager=None,
    channel_event_store=None,
    memory_broker=None,
    context_compactor=None,
    retrieval_planner=None,
    model_registry_manager=None,
    reference_backend=None,
    plugin_manager=None,
    tool_broker=None,
    skill_catalog=None,
    subagent_catalog=None,
    subagent_delegator=None,
    long_term_memory_ingestor: LongTermMemoryIngestor | None = None,
    approval_resumer: ApprovalResumer | None = None,
    plugins: list[RuntimePlugin] | None = None,
    log_buffer=None,
) -> RuntimeComponents:
    """根据配置和注入依赖组装一套最小 runtime 组件."""

    runtime_conf = config.get("runtime", {})
    default_computer_policy = build_default_computer_policy(config)
    default_frontstage_agent = build_default_frontstage_agent(
        config,
        default_computer_policy=default_computer_policy,
    )
    runtime_subagent_catalog = subagent_catalog or build_subagent_catalog(config)
    prompt_loader = ReloadablePromptLoader(
        build_prompt_loader(
            config,
            prompt_refs={default_frontstage_agent.prompt_ref},
            subagent_catalog=runtime_subagent_catalog,
        )
    )
    default_agent_id = str(default_frontstage_agent.agent_id or "default")
    runtime_model_target_catalog = MutableModelTargetCatalog()
    runtime_model_target_catalog.replace_agent_targets(build_agent_model_targets([default_frontstage_agent]))
    session_runtime = build_session_runtime(config)
    runtime_router = router or RuntimeRouter(
        default_agent_id=default_agent_id,
        session_runtime=session_runtime,
    )
    runtime_thread_manager = thread_manager or build_thread_manager(config)
    runtime_run_manager = run_manager or build_run_manager(config)
    runtime_channel_event_store = channel_event_store or build_channel_event_store(config)
    runtime_message_store = message_store or build_message_store(config)
    runtime_soul_dir = resolve_runtime_path(
        config,
        runtime_conf.get("soul_dir", runtime_conf.get("self_dir", "soul")),
    )
    runtime_sticky_notes_dir = resolve_runtime_path(
        config,
        runtime_conf.get("sticky_notes_dir", "sticky-notes"),
    )
    runtime_soul_source = SoulSource(root_dir=runtime_soul_dir)
    runtime_sticky_notes_source = StickyNoteFileStore(root_dir=runtime_sticky_notes_dir)
    runtime_sticky_notes = StickyNoteService(
        store=runtime_sticky_notes_source,
        renderer=StickyNoteRenderer(),
    )
    runtime_skill_catalog = skill_catalog or build_skill_catalog(config)
    runtime_subagent_delegator = subagent_delegator or SubagentDelegationBroker(
        catalog=runtime_subagent_catalog,
        default_agent_id=str(default_agent_id or ""),
    )
    runtime_context_compactor = context_compactor or build_context_compactor(
        config,
        agent=agent,
    )
    runtime_retrieval_planner = retrieval_planner or build_retrieval_planner(config)
    runtime_computer_runtime = build_computer_runtime(
        config,
        gateway=gateway,
        run_manager=runtime_run_manager,
        skill_catalog=runtime_skill_catalog,
    )
    runtime_reference_backend = reference_backend or build_reference_backend(config)
    runtime_model_registry_manager = model_registry_manager or build_model_registry_manager(
        config,
        target_catalog=runtime_model_target_catalog,
    )
    long_term_memory_conf = dict(runtime_conf.get("long_term_memory", {}))
    long_term_memory_enabled = bool(long_term_memory_conf.get("enabled", False))
    runtime_long_term_memory_source = None
    runtime_long_term_memory_ingestor = long_term_memory_ingestor
    runtime_fact_reader = None
    runtime_long_term_memory_store = None
    if long_term_memory_enabled and (memory_broker is None or runtime_long_term_memory_ingestor is None):
        runtime_long_term_memory_store = build_long_term_memory_store(config)
    if long_term_memory_enabled and memory_broker is None:
        if runtime_long_term_memory_store is None:
            runtime_long_term_memory_store = build_long_term_memory_store(config)
        runtime_long_term_memory_source = build_long_term_memory_source(
            config,
            agent=agent,
            store=runtime_long_term_memory_store,
            model_registry_manager=runtime_model_registry_manager,
        )
    if long_term_memory_enabled and runtime_long_term_memory_ingestor is None:
        if runtime_long_term_memory_store is None:
            runtime_long_term_memory_store = build_long_term_memory_store(config)
        runtime_fact_reader = StoreBackedConversationFactReader(
            channel_event_store=runtime_channel_event_store,
            message_store=runtime_message_store,
        )
        runtime_long_term_memory_write_port = build_long_term_memory_write_port(
            config,
            agent=agent,
            store=runtime_long_term_memory_store,
            model_registry_manager=runtime_model_registry_manager,
        )
        runtime_long_term_memory_ingestor = build_long_term_memory_ingestor(
            thread_manager=runtime_thread_manager,
            fact_reader=runtime_fact_reader,
            write_port=runtime_long_term_memory_write_port,
        )
    runtime_memory_broker = memory_broker or build_memory_broker(
        config,
        soul_source=runtime_soul_source,
        sticky_notes_source=runtime_sticky_notes_source,
        long_term_memory_source=runtime_long_term_memory_source,
    )
    backend_conf = dict(runtime_conf.get("backend", {}))
    runtime_backend_mode_registry = BackendModeRegistry()
    backend_session_path = resolve_runtime_path(
        config,
        backend_conf.get("session_binding_path", "backend/session.json"),
    )
    backend_binding_store = BackendSessionBindingStore(backend_session_path)
    backend_enabled = bool(backend_conf.get("enabled", False))
    backend_pi_command = [str(part) for part in list(backend_conf.get("pi_command", []) or []) if str(part)]
    backend_cwd = backend_conf.get("cwd")
    resolved_backend_cwd = config.base_dir()
    if backend_cwd not in (None, ""):
        resolved_backend_cwd = config.resolve_path(str(backend_cwd))
    if backend_enabled and backend_pi_command:
        runtime_backend_session_service = ConfiguredBackendSessionService(
            binding_store=backend_binding_store,
            adapter=PiBackendAdapter(
                command=backend_pi_command,
                cwd=resolved_backend_cwd,
            ),
        )
    else:
        runtime_backend_session_service = BackendSessionService(backend_binding_store)
    runtime_backend_bridge = BackendBridge(session=runtime_backend_session_service)
    runtime_backend_admin_actor_ids = _resolve_shared_admin_actor_ids(
        backend_conf=backend_conf,
    )
    runtime_image_context_service = ImageContextService(
        agent=agent,
        model_registry_manager=runtime_model_registry_manager,
    )
    runtime_message_resolution_service = MessageResolutionService(
        gateway=gateway,
        computer_runtime=runtime_computer_runtime,
    )
    runtime_message_projection_service = MessageProjectionService(
        image_context=runtime_image_context_service,
    )
    runtime_message_preparation_service = MessagePreparationService(
        resolution_service=runtime_message_resolution_service,
        projection_service=runtime_message_projection_service,
    )
    runtime_tool_broker = tool_broker or ToolBroker(
        skill_catalog=runtime_skill_catalog,
        subagent_catalog=runtime_subagent_catalog,
        default_agent_id=default_agent_id,
        backend_bridge=runtime_backend_bridge,
    )
    runtime_tool_broker.skill_catalog = runtime_skill_catalog
    runtime_tool_broker.subagent_catalog = runtime_subagent_catalog
    runtime_tool_broker.backend_bridge = runtime_backend_bridge
    runtime_context_assembler = ContextAssembler()
    runtime_payload_json_writer = build_payload_json_writer(config)
    register_core_builtin_tools(
        tool_broker=runtime_tool_broker,
        computer_runtime=runtime_computer_runtime,
        skill_catalog=runtime_skill_catalog,
        sticky_note_service=runtime_sticky_notes,
        subagent_delegator=runtime_subagent_delegator,
    )
    runtime_session_bundle_loader = build_session_bundle_loader(
        config,
        prompt_refs=build_prompt_refs(
            config,
            prompt_refs={default_frontstage_agent.prompt_ref},
            subagent_catalog=runtime_subagent_catalog,
        ),
        tool_names={
            str(item.get("name", "") or "")
            for item in runtime_tool_broker.list_registered_tools()
            if str(item.get("name", "") or "")
        },
        skill_names={item.skill_name for item in runtime_skill_catalog.list_all()},
        subagent_names={item.subagent_name for item in runtime_subagent_catalog.list_all()},
    )

    runtime_frontstage_agents: list[ResolvedAgent] = [default_frontstage_agent]
    if runtime_session_bundle_loader is not None:
        seen_agent_ids = {default_frontstage_agent.agent_id}
        for bundle in runtime_session_bundle_loader.list_bundles():
            resolved = ResolvedAgent.from_session_agent(bundle.frontstage_agent)
            if resolved.agent_id in seen_agent_ids:
                continue
            runtime_frontstage_agents.append(resolved)
            seen_agent_ids.add(resolved.agent_id)
    runtime_model_target_catalog.replace_agent_targets(build_agent_model_targets(runtime_frontstage_agents))
    runtime_model_registry_manager.target_catalog.replace_agent_targets(
        build_agent_model_targets(runtime_frontstage_agents)
    )
    runtime_model_registry_manager.reload_now()

    runtime_agent_loader_state = {
        "default_frontstage_agent": default_frontstage_agent,
        "session_bundle_loader": runtime_session_bundle_loader,
    }

    def runtime_agent_loader(decision):
        session_bundle_loader = runtime_agent_loader_state["session_bundle_loader"]
        if session_bundle_loader is not None:
            bundle = session_bundle_loader.load_by_session_id(decision.channel_scope)
            return ResolvedAgent.from_session_agent(bundle.frontstage_agent)
        return runtime_agent_loader_state["default_frontstage_agent"]

    def rebind_agent_loader(
        next_default_frontstage_agent: ResolvedAgent,
        next_session_bundle_loader,
    ) -> None:
        runtime_agent_loader_state["default_frontstage_agent"] = next_default_frontstage_agent
        runtime_agent_loader_state["session_bundle_loader"] = next_session_bundle_loader

    builtin_plugins = build_builtin_runtime_plugins()
    failed_plugin_import_paths: list[str] = []
    configured_plugins = plugins
    if configured_plugins is None:
        configured_plugins, failed_plugin_import_paths = load_runtime_plugins_from_config_with_failures(config)
    if plugin_manager is not None and getattr(plugin_manager, "_started", False):
        raise ValueError("build_runtime_components() requires a fresh RuntimePluginManager")
    runtime_plugin_manager = plugin_manager or RuntimePluginManager(
        config=config,
        gateway=gateway,
        tool_broker=runtime_tool_broker,
        reference_backend=runtime_reference_backend,
        sticky_notes=runtime_sticky_notes,
        computer_runtime=runtime_computer_runtime,
        skill_catalog=runtime_skill_catalog,
        model_target_catalog=runtime_model_registry_manager.target_catalog,
        builtin_plugins=builtin_plugins,
        plugins=configured_plugins,
    )
    runtime_plugin_manager.config = config
    runtime_plugin_manager.gateway = gateway
    runtime_plugin_manager.tool_broker = runtime_tool_broker
    runtime_plugin_manager.reference_backend = runtime_reference_backend
    runtime_plugin_manager.sticky_notes = runtime_sticky_notes
    runtime_plugin_manager.computer_runtime = runtime_computer_runtime
    runtime_plugin_manager.skill_catalog = runtime_skill_catalog
    runtime_plugin_manager.configure_builtin_plugins(builtin_plugins)
    runtime_plugin_manager.failed_plugin_import_paths = list(failed_plugin_import_paths)
    runtime_approval_resumer = approval_resumer or ToolApprovalResumer(
        thread_manager=runtime_thread_manager,
        agent_loader=runtime_agent_loader,
        tool_broker=runtime_tool_broker,
        computer_runtime=runtime_computer_runtime,
    )
    agent_runtime = ModelAgentRuntime(
        agent=agent,
        prompt_loader=prompt_loader,
        tool_runtime_resolver=runtime_tool_broker.build_tool_runtime,
        context_assembler=runtime_context_assembler,
        payload_json_writer=runtime_payload_json_writer,
    )
    outbox = Outbox(
        gateway=gateway,
        store=runtime_message_store,
        long_term_memory_ingestor=runtime_long_term_memory_ingestor,
    )
    pipeline = ThreadPipeline(
        agent_runtime=agent_runtime,
        outbox=outbox,
        run_manager=runtime_run_manager,
        thread_manager=runtime_thread_manager,
        memory_broker=runtime_memory_broker,
        retrieval_planner=runtime_retrieval_planner,
        context_compactor=runtime_context_compactor,
        computer_runtime=runtime_computer_runtime,
        message_preparation_service=runtime_message_preparation_service,
        tool_broker=runtime_tool_broker,
        plugin_manager=runtime_plugin_manager,
        soul_source=runtime_soul_source,
        sticky_notes_source=runtime_sticky_notes_source,
    )
    runtime_subagent_execution_service = LocalSubagentExecutionService(
        thread_manager=runtime_thread_manager,
        run_manager=runtime_run_manager,
        pipeline=pipeline,
        agent_loader=runtime_agent_loader,
        model_registry_manager=runtime_model_registry_manager,
        subagent_catalog=runtime_subagent_catalog,
    )
    runtime_subagent_delegator.execution_service = runtime_subagent_execution_service
    config_control_plane = RuntimeConfigControlPlane(
        config=config,
        router=runtime_router,
        default_frontstage_agent=default_frontstage_agent,
        session_bundle_loader=runtime_session_bundle_loader,
        prompt_loader=prompt_loader,
        model_registry_manager=runtime_model_registry_manager,
        skill_catalog=runtime_skill_catalog,
        subagent_catalog=runtime_subagent_catalog,
        plugin_manager=runtime_plugin_manager,
        tool_broker=runtime_tool_broker,
        subagent_delegator=runtime_subagent_delegator,
        builtin_plugin_factory=build_builtin_runtime_plugins,
        rebind_agent_loader=rebind_agent_loader,
    )
    app = RuntimeApp(
        gateway=gateway,
        router=runtime_router,
        thread_manager=runtime_thread_manager,
        run_manager=runtime_run_manager,
        channel_event_store=runtime_channel_event_store,
        pipeline=pipeline,
        agent_loader=runtime_agent_loader,
        approval_resumer=runtime_approval_resumer,
        reference_backend=runtime_reference_backend,
        plugin_manager=runtime_plugin_manager,
        model_registry_manager=runtime_model_registry_manager,
        computer_runtime=runtime_computer_runtime,
        long_term_memory_ingestor=runtime_long_term_memory_ingestor,
        backend_bridge=runtime_backend_bridge,
        backend_mode_registry=runtime_backend_mode_registry,
        backend_admin_actor_ids=runtime_backend_admin_actor_ids,
    )
    control_plane = RuntimeControlPlane(
        app=app,
        run_manager=runtime_run_manager,
        thread_manager=runtime_thread_manager,
        message_store=runtime_message_store,
        channel_event_store=runtime_channel_event_store,
        soul_source=runtime_soul_source,
        sticky_notes_source=runtime_sticky_notes_source,
        sticky_notes=runtime_sticky_notes,
        plugin_manager=runtime_plugin_manager,
        skill_catalog=runtime_skill_catalog,
        subagent_catalog=runtime_subagent_catalog,
        tool_broker=runtime_tool_broker,
        model_registry_manager=runtime_model_registry_manager,
        computer_runtime=runtime_computer_runtime,
        reference_backend=runtime_reference_backend,
        config_control_plane=config_control_plane,
        log_buffer=log_buffer,
        ltm_store=runtime_long_term_memory_store,
    )
    runtime_plugin_manager.attach_control_plane(control_plane)
    runtime_plugin_manager.attach_computer_runtime(runtime_computer_runtime)

    return RuntimeComponents(
        gateway=gateway,
        router=runtime_router,
        thread_manager=runtime_thread_manager,
        run_manager=runtime_run_manager,
        channel_event_store=runtime_channel_event_store,
        message_store=runtime_message_store,
        soul_source=runtime_soul_source,
        sticky_notes_source=runtime_sticky_notes_source,
        sticky_notes=runtime_sticky_notes,
        skill_catalog=runtime_skill_catalog,
        subagent_catalog=runtime_subagent_catalog,
        subagent_delegator=runtime_subagent_delegator,
        subagent_execution_service=runtime_subagent_execution_service,
        memory_broker=runtime_memory_broker,
        context_compactor=runtime_context_compactor,
        retrieval_planner=runtime_retrieval_planner,
        context_assembler=runtime_context_assembler,
        payload_json_writer=runtime_payload_json_writer,
        model_registry_manager=runtime_model_registry_manager,
        computer_runtime=runtime_computer_runtime,
        image_context_service=runtime_image_context_service,
        message_preparation_service=runtime_message_preparation_service,
        reference_backend=runtime_reference_backend,
        plugin_manager=runtime_plugin_manager,
        control_plane=control_plane,
        config_control_plane=config_control_plane,
        prompt_loader=prompt_loader,
        agent_loader=runtime_agent_loader,
        tool_broker=runtime_tool_broker,
        agent_runtime=agent_runtime,
        approval_resumer=runtime_approval_resumer,
        outbox=outbox,
        pipeline=pipeline,
        backend_bridge=runtime_backend_bridge,
        backend_mode_registry=runtime_backend_mode_registry,
        app=app,
        long_term_memory_ingestor=runtime_long_term_memory_ingestor,
    )


__all__ = ["RuntimeComponents", "build_runtime_components"]
