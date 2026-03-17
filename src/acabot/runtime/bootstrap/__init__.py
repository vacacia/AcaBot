r"""runtime.bootstrap 提供 runtime 默认组装入口."""

from __future__ import annotations

from acabot.agent import BaseAgent
from acabot.config import Config

from ..agent_runtime import AgentRuntime
from ..approval_resumer import ApprovalResumer, ToolApprovalResumer
from ..app import RuntimeApp
from ..backend.bridge import BackendBridge
from ..backend.mode_registry import BackendModeRegistry
from ..backend.session import BackendSessionBindingStore, BackendSessionService
from ..control.config_control_plane import RuntimeConfigControlPlane
from ..control.control_plane import RuntimeControlPlane
from ..control.event_policy import EventPolicyRegistry
from ..gateway_protocol import GatewayProtocol
from ..inbound.image_context import ImageContextService
from ..inbound.message_preparation import MessagePreparationService
from ..inbound.message_projection import MessageProjectionService
from ..inbound.message_resolution import MessageResolutionService
from ..memory.sticky_notes import StickyNotesService
from ..model.model_agent_runtime import ModelAgentRuntime
from ..outbox import Outbox
from ..pipeline import ThreadPipeline
from ..plugin_manager import RuntimePlugin, RuntimePluginManager, load_runtime_plugins_from_config
from ..control.profile_loader import AgentProfileRegistry, ProfileLoader, PromptLoader, ReloadablePromptLoader
from ..router import InboundRuleRegistry, RuntimeRouter
from ..subagents import SubagentDelegationBroker, SubagentExecutorRegistry
from ..subagents.execution import LocalSubagentExecutionService
from ..tool_broker import ToolBroker
from .builders import (
    build_builtin_runtime_plugins,
    build_channel_event_store,
    build_computer_runtime,
    build_context_compactor,
    build_default_computer_policy,
    build_memory_broker,
    build_memory_store,
    build_message_store,
    build_model_registry_manager,
    build_reference_backend,
    build_retrieval_planner,
    build_run_manager,
    build_skill_catalog,
    build_thread_manager,
    register_local_subagent_executors,
)
from .config import resolve_runtime_path
from .components import RuntimeComponents
from .loaders import (
    build_binding_rules,
    build_event_policies,
    build_filesystem_binding_rules,
    build_filesystem_event_policies,
    build_filesystem_inbound_rules,
    build_filesystem_profiles,
    build_inbound_rules,
    build_profiles,
    build_prompt_loader,
)


def build_runtime_components(
    config: Config,
    *,
    gateway: GatewayProtocol,
    agent: BaseAgent,
    message_store=None,
    memory_store=None,
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
    subagent_executor_registry=None,
    subagent_delegator=None,
    approval_resumer: ApprovalResumer | None = None,
    plugins: list[RuntimePlugin] | None = None,
) -> RuntimeComponents:
    """根据配置和注入依赖组装一套最小 runtime 组件."""

    runtime_conf = config.get("runtime", {})
    default_computer_policy = build_default_computer_policy(config)
    profiles = build_profiles(config, default_computer_policy=default_computer_policy)
    filesystem_profiles = build_filesystem_profiles(
        config,
        default_computer_policy=default_computer_policy,
    )
    profiles.update(filesystem_profiles)
    prompt_loader = ReloadablePromptLoader(build_prompt_loader(config, profiles))
    default_agent_id = runtime_conf.get("default_agent_id", next(iter(profiles)))
    rules = build_binding_rules(config) + build_filesystem_binding_rules(config)
    inbound_rules = build_inbound_rules(config) + build_filesystem_inbound_rules(config)
    event_policies = build_event_policies(config) + build_filesystem_event_policies(config)

    profile_registry = AgentProfileRegistry(
        profiles=profiles,
        default_agent_id=default_agent_id,
    )
    for rule in rules:
        profile_registry.add_rule(rule)
    inbound_registry = InboundRuleRegistry(inbound_rules)
    event_policy_registry = EventPolicyRegistry(event_policies)

    runtime_router = router or RuntimeRouter(
        default_agent_id=default_agent_id,
        decide_run_mode=inbound_registry.resolve,
        resolve_agent=profile_registry.resolve_agent,
        resolve_event_policy=event_policy_registry.resolve,
    )
    runtime_thread_manager = thread_manager or build_thread_manager(config)
    runtime_run_manager = run_manager or build_run_manager(config)
    runtime_channel_event_store = channel_event_store or build_channel_event_store(config)
    runtime_message_store = message_store or build_message_store(config)
    runtime_memory_store = memory_store or build_memory_store(config)
    runtime_sticky_notes = StickyNotesService(store=runtime_memory_store)
    runtime_skill_catalog = skill_catalog or build_skill_catalog(config)
    runtime_subagent_executor_registry = subagent_executor_registry or SubagentExecutorRegistry()
    runtime_subagent_delegator = subagent_delegator or SubagentDelegationBroker(
        skill_catalog=runtime_skill_catalog,
        executor_registry=runtime_subagent_executor_registry,
    )
    runtime_memory_broker = memory_broker or build_memory_broker(
        config,
        memory_store=runtime_memory_store,
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
    )
    runtime_reference_backend = reference_backend or build_reference_backend(config)
    runtime_model_registry_manager = model_registry_manager or build_model_registry_manager(config)
    backend_conf = dict(runtime_conf.get("backend", {}))
    runtime_backend_mode_registry = BackendModeRegistry()
    backend_session_path = resolve_runtime_path(
        config,
        backend_conf.get("session_binding_path", ".acabot-runtime/backend/session.json"),
    )
    runtime_backend_session_service = BackendSessionService(
        BackendSessionBindingStore(backend_session_path)
    )
    runtime_backend_bridge = BackendBridge(session=runtime_backend_session_service)
    runtime_backend_admin_actor_ids = {
        str(value)
        for value in list(backend_conf.get("admin_actor_ids", []) or [])
        if str(value)
    }
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
        subagent_executor_registry=runtime_subagent_executor_registry,
        default_agent_id=default_agent_id,
        backend_bridge=runtime_backend_bridge,
    )
    runtime_tool_broker.skill_catalog = runtime_skill_catalog
    runtime_tool_broker.backend_bridge = runtime_backend_bridge
    builtin_plugins = build_builtin_runtime_plugins(profiles)
    configured_plugins = plugins if plugins is not None else load_runtime_plugins_from_config(config)
    runtime_plugin_manager = plugin_manager or RuntimePluginManager(
        config=config,
        gateway=gateway,
        tool_broker=runtime_tool_broker,
        reference_backend=runtime_reference_backend,
        sticky_notes=runtime_sticky_notes,
        computer_runtime=runtime_computer_runtime,
        skill_catalog=runtime_skill_catalog,
        subagent_delegator=runtime_subagent_delegator,
        builtin_plugins=builtin_plugins,
        plugins=configured_plugins,
    )
    runtime_approval_resumer = approval_resumer or ToolApprovalResumer(
        thread_manager=runtime_thread_manager,
        profile_loader=profile_registry.load,
        tool_broker=runtime_tool_broker,
        computer_runtime=runtime_computer_runtime,
    )
    agent_runtime = ModelAgentRuntime(
        agent=agent,
        prompt_loader=prompt_loader,
        tool_runtime_resolver=runtime_tool_broker.build_tool_runtime,
    )
    outbox = Outbox(gateway=gateway, store=runtime_message_store)
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
    )
    runtime_subagent_execution_service = LocalSubagentExecutionService(
        thread_manager=runtime_thread_manager,
        run_manager=runtime_run_manager,
        pipeline=pipeline,
        profile_loader=profile_registry.load,
        model_registry_manager=runtime_model_registry_manager,
    )
    register_local_subagent_executors(
        registry=runtime_subagent_executor_registry,
        profiles=profiles,
        service=runtime_subagent_execution_service,
    )
    config_control_plane = RuntimeConfigControlPlane(
        config=config,
        router=runtime_router,
        profile_registry=profile_registry,
        inbound_registry=inbound_registry,
        event_policy_registry=event_policy_registry,
        prompt_loader=prompt_loader,
        skill_catalog=runtime_skill_catalog,
        plugin_manager=runtime_plugin_manager,
        subagent_executor_registry=runtime_subagent_executor_registry,
        local_subagent_executor=runtime_subagent_execution_service.execute,
        builtin_plugin_factory=build_builtin_runtime_plugins,
    )
    app = RuntimeApp(
        gateway=gateway,
        router=runtime_router,
        thread_manager=runtime_thread_manager,
        run_manager=runtime_run_manager,
        channel_event_store=runtime_channel_event_store,
        pipeline=pipeline,
        profile_loader=profile_registry.load,
        approval_resumer=runtime_approval_resumer,
        reference_backend=runtime_reference_backend,
        plugin_manager=runtime_plugin_manager,
        model_registry_manager=runtime_model_registry_manager,
        computer_runtime=runtime_computer_runtime,
        backend_bridge=runtime_backend_bridge,
        backend_mode_registry=runtime_backend_mode_registry,
        backend_admin_actor_ids=runtime_backend_admin_actor_ids,
    )
    control_plane = RuntimeControlPlane(
        app=app,
        run_manager=runtime_run_manager,
        thread_manager=runtime_thread_manager,
        memory_store=runtime_memory_store,
        message_store=runtime_message_store,
        channel_event_store=runtime_channel_event_store,
        profile_registry=profile_registry,
        plugin_manager=runtime_plugin_manager,
        skill_catalog=runtime_skill_catalog,
        subagent_executor_registry=runtime_subagent_executor_registry,
        tool_broker=runtime_tool_broker,
        model_registry_manager=runtime_model_registry_manager,
        computer_runtime=runtime_computer_runtime,
        reference_backend=runtime_reference_backend,
        config_control_plane=config_control_plane,
    )
    runtime_plugin_manager.attach_control_plane(control_plane)
    runtime_plugin_manager.attach_subagent_delegator(runtime_subagent_delegator)
    runtime_plugin_manager.attach_computer_runtime(runtime_computer_runtime)

    return RuntimeComponents(
        gateway=gateway,
        router=runtime_router,
        thread_manager=runtime_thread_manager,
        run_manager=runtime_run_manager,
        channel_event_store=runtime_channel_event_store,
        message_store=runtime_message_store,
        memory_store=runtime_memory_store,
        sticky_notes=runtime_sticky_notes,
        skill_catalog=runtime_skill_catalog,
        subagent_executor_registry=runtime_subagent_executor_registry,
        subagent_delegator=runtime_subagent_delegator,
        subagent_execution_service=runtime_subagent_execution_service,
        memory_broker=runtime_memory_broker,
        context_compactor=runtime_context_compactor,
        retrieval_planner=runtime_retrieval_planner,
        model_registry_manager=runtime_model_registry_manager,
        computer_runtime=runtime_computer_runtime,
        image_context_service=runtime_image_context_service,
        message_preparation_service=runtime_message_preparation_service,
        reference_backend=runtime_reference_backend,
        plugin_manager=runtime_plugin_manager,
        control_plane=control_plane,
        config_control_plane=config_control_plane,
        prompt_loader=prompt_loader,
        profile_loader=profile_registry,
        tool_broker=runtime_tool_broker,
        agent_runtime=agent_runtime,
        approval_resumer=runtime_approval_resumer,
        outbox=outbox,
        pipeline=pipeline,
        backend_bridge=runtime_backend_bridge,
        backend_mode_registry=runtime_backend_mode_registry,
        app=app,
    )


__all__ = ["RuntimeComponents", "build_runtime_components"]
