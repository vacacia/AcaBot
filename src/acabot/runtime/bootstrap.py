r"""runtime.bootstrap 提供 runtime 默认组装入口.

组件关系:

    Config
      |
      v
    build_runtime_components()
      |
      +-- RuntimeRouter
      +-- ThreadManager / RunManager
      +-- MessageStore / MemoryStore / ChannelEventStore
      +-- ModelAgentRuntime
      +-- Outbox
      `-- RuntimeApp

负责把默认主线接起来.
不关心具体业务策略, 只决定默认组件如何装配.


- computer 在这里先作为基础设施创建
- 再通过 plugin / tool adapter 暴露给 agent

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from acabot.agent import BaseAgent
from acabot.config import Config

from .agent_runtime import AgentRuntime
from .approval_resumer import ApprovalResumer, NoopApprovalResumer, ToolApprovalResumer
from .app import RuntimeApp
from .computer import ComputerPolicy, ComputerRuntime, ComputerRuntimeConfig, parse_computer_policy
from .config_control_plane import RuntimeConfigControlPlane
from .context_compactor import (
    ContextCompactionConfig,
    ContextCompactor,
    ModelContextSummarizer,
)
from .control_plane import RuntimeControlPlane
from .event_policy import EventPolicyRegistry
from .event_store import InMemoryChannelEventStore
from .gateway_protocol import GatewayProtocol
from .memory_broker import MemoryBroker
from .memory_item_store import InMemoryMemoryStore
from .memory_store import InMemoryMessageStore
from .model_agent_runtime import ModelAgentRuntime
from .model_registry import FileSystemModelRegistryManager
from .models import AgentProfile, BindingRule, EventPolicy, InboundRule
from .outbox import Outbox
from .pipeline import ThreadPipeline
from .plugin_manager import (
    RuntimePlugin,
    RuntimePluginManager,
    load_runtime_plugins_from_config,
)
from .plugins import ComputerToolAdapterPlugin, SkillToolPlugin, SubagentDelegationPlugin
from .profile_loader import (
    AgentProfileRegistry,
    ChainedPromptLoader,
    FileSystemBindingLoader,
    FileSystemEventPolicyLoader,
    FileSystemInboundRuleLoader,
    FileSystemProfileLoader,
    FileSystemPromptLoader,
    ProfileLoader,
    PromptLoader,
    ReloadablePromptLoader,
    StaticPromptLoader,
    parse_skill_assignments,
)
from .reference_backend import (
    LocalReferenceBackend,
    NullReferenceBackend,
    OpenVikingReferenceBackend,
    ReferenceBackend,
)
from .retrieval_planner import PromptAssemblyConfig, RetrievalPlanner
from .router import InboundRuleRegistry, RuntimeRouter
from .runs import InMemoryRunManager, RunManager, StoreBackedRunManager
from .skill_loader import FileSystemSkillPackageLoader
from .sqlite_stores import (
    SQLiteChannelEventStore,
    SQLiteMemoryStore,
    SQLiteMessageStore,
    SQLiteRunStore,
    SQLiteThreadStore,
)
from .sticky_notes import StickyNotesService
from .stores import ChannelEventStore, MemoryStore, MessageStore
from .structured_memory import StoreBackedMemoryRetriever, StructuredMemoryExtractor
from .skills import SkillCatalog
from .subagent_delegation import SubagentDelegationBroker, SubagentExecutorRegistry
from .subagent_execution import LocalSubagentExecutionService
from .tool_broker import ToolBroker
from .threads import InMemoryThreadManager, StoreBackedThreadManager, ThreadManager


def _build_builtin_runtime_plugins(
    profiles: dict[str, AgentProfile],
) -> list[RuntimePlugin]:
    """解析 runtime world 的系统内建插件集合."""

    builtin_plugins: list[RuntimePlugin] = [
        ComputerToolAdapterPlugin(),
        SkillToolPlugin(),
    ]
    if _profiles_have_delegated_skills(profiles) or len(profiles) > 1:
        builtin_plugins.append(SubagentDelegationPlugin())
    return builtin_plugins

# region RuntimeComponents
@dataclass(slots=True)
class RuntimeComponents:
    """runtime 组装结果.

    Attributes:
        gateway (GatewayProtocol): 当前 runtime 使用的 gateway.
        router (RuntimeRouter): 负责 route decision 的 router.
        thread_manager (ThreadManager): 管理 thread state 的 manager.
        run_manager (RunManager): 管理 run 生命周期的 manager.
        channel_event_store (ChannelEventStore): 保存 inbound event facts 的 ChannelEventStore.
        message_store (MessageStore): 保存 delivered facts 的 MessageStore.
        memory_store (MemoryStore): 保存长期记忆项的 MemoryStore.
        sticky_notes (StickyNotesService): sticky note 的受控服务层.
        skill_catalog (SkillCatalog): 统一 skill catalog.
        subagent_executor_registry (SubagentExecutorRegistry): subagent executor 注册表.
        subagent_delegator (SubagentDelegationBroker): subagent delegation 编排入口.
        subagent_execution_service (LocalSubagentExecutionService): 本地 child run delegation 服务.
        memory_broker (MemoryBroker): 长期记忆统一入口.
        context_compactor (ContextCompactor): 负责 token-aware working memory compaction 的 compactor.
        retrieval_planner (RetrievalPlanner): 负责 retrieval planning 和 prompt assembly 的 planner.
        model_registry_manager (FileSystemModelRegistryManager): 模型真源与 active registry 管理器.
        computer_runtime (ComputerRuntime): computer 基础设施入口.
        reference_backend (ReferenceBackend): on-demand `reference / notebook` provider.
        plugin_manager (RuntimePluginManager): runtime world 的插件管理器.
        control_plane (RuntimeControlPlane): 本地 control plane 入口.
        prompt_loader (PromptLoader): 按 `prompt_ref` 加载 system prompt 的 loader.
        profile_loader (ProfileLoader): 按 `RouteDecision` 加载 profile 的 loader.
        tool_broker (ToolBroker): runtime 侧统一工具入口.
        agent_runtime (AgentRuntime): 负责执行一次 run 的 agent runtime.
        approval_resumer (ApprovalResumer): approval 通过后的续执行器.
        outbox (Outbox): 唯一出站口.
        pipeline (ThreadPipeline): 单次 run 执行器.
        app (RuntimeApp): 对外暴露的 runtime 应用入口.
    """

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

# region 组装runtime
def build_runtime_components(
    config: Config,
    *,
    gateway: GatewayProtocol,
    agent: BaseAgent,
    message_store: MessageStore | None = None,
    memory_store: MemoryStore | None = None,
    router: RuntimeRouter | None = None,
    thread_manager: ThreadManager | None = None,
    run_manager: RunManager | None = None,
    channel_event_store: ChannelEventStore | None = None,
    memory_broker: MemoryBroker | None = None,
    context_compactor: ContextCompactor | None = None,
    retrieval_planner: RetrievalPlanner | None = None,
    model_registry_manager: FileSystemModelRegistryManager | None = None,
    reference_backend: ReferenceBackend | None = None,
    plugin_manager: RuntimePluginManager | None = None,
    tool_broker: ToolBroker | None = None,
    skill_catalog: SkillCatalog | None = None,
    subagent_executor_registry: SubagentExecutorRegistry | None = None,
    subagent_delegator: SubagentDelegationBroker | None = None,
    approval_resumer: ApprovalResumer | None = None,
    plugins: list[RuntimePlugin] | None = None,
) -> RuntimeComponents:
    """根据配置和注入依赖组装一套最小 runtime 组件.

    Args:
        config: 项目配置对象.
        gateway: 平台 Gateway 实现.
        agent: 满足新 `BaseAgent` 契约的 agent.
        message_store: 可选的 MessageStore 实现.
        memory_store: 可选的 MemoryStore 实现.
        router: 可选的 RuntimeRouter 实现.
        thread_manager: 可选的 ThreadManager 实现.
        run_manager: 可选的 RunManager 实现.
        channel_event_store: 可选的 ChannelEventStore 实现.
        memory_broker: 可选的 MemoryBroker 实现.
        context_compactor: 可选的 ContextCompactor 实现.
        retrieval_planner: 可选的 RetrievalPlanner 实现.
        model_registry_manager: 可选的模型注册表管理器.
        reference_backend: 可选的 ReferenceBackend 实现.
        plugin_manager: 可选的 RuntimePluginManager 实现.
        tool_broker: 可选的 ToolBroker 实现.
        skill_catalog: 可选的 SkillCatalog 实现.
        subagent_executor_registry: 可选的 subagent executor 注册表.
        subagent_delegator: 可选的 subagent delegation 编排入口.
        approval_resumer: 可选的 approval resumer.
        plugins: 启动时要加载的 runtime plugin 实例列表.

    Returns:
        一份包含 RuntimeApp 及其依赖组件的组装结果.
    """

    runtime_conf = config.get("runtime", {})
    profiles = _build_profiles(config)
    filesystem_profiles = _build_filesystem_profiles(config)
    profiles.update(filesystem_profiles)
    prompt_loader = ReloadablePromptLoader(_build_prompt_loader(config, profiles))
    default_agent_id = runtime_conf.get("default_agent_id", next(iter(profiles)))
    rules = _build_binding_rules(config) + _build_filesystem_binding_rules(config)
    inbound_rules = _build_inbound_rules(config) + _build_filesystem_inbound_rules(config)
    event_policies = _build_event_policies(config) + _build_filesystem_event_policies(config)
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
    runtime_thread_manager = thread_manager or _build_thread_manager(config)
    runtime_run_manager = run_manager or _build_run_manager(config)
    runtime_channel_event_store = channel_event_store or _build_channel_event_store(config)
    runtime_message_store = message_store or _build_message_store(config)
    runtime_memory_store = memory_store or _build_memory_store(config)
    runtime_sticky_notes = StickyNotesService(store=runtime_memory_store)
    runtime_skill_catalog = skill_catalog or _build_skill_catalog(config)
    runtime_subagent_executor_registry = subagent_executor_registry or SubagentExecutorRegistry()
    runtime_subagent_delegator = subagent_delegator or SubagentDelegationBroker(
        skill_catalog=runtime_skill_catalog,
        executor_registry=runtime_subagent_executor_registry,
    )
    runtime_memory_broker = memory_broker or _build_memory_broker(
        config,
        memory_store=runtime_memory_store,
    )
    runtime_context_compactor = context_compactor or _build_context_compactor(
        config,
        agent=agent,
    )
    runtime_retrieval_planner = retrieval_planner or _build_retrieval_planner(config)
    runtime_computer_runtime = _build_computer_runtime(
        config,
        gateway=gateway,
        run_manager=runtime_run_manager,
    )
    runtime_reference_backend = reference_backend or _build_reference_backend(config)
    runtime_model_registry_manager = model_registry_manager or _build_model_registry_manager(config)
    runtime_tool_broker = tool_broker or ToolBroker(
        skill_catalog=runtime_skill_catalog,
        subagent_executor_registry=runtime_subagent_executor_registry,
        default_agent_id=default_agent_id,
    )
    runtime_tool_broker.skill_catalog = runtime_skill_catalog
    builtin_plugins = _build_builtin_runtime_plugins(profiles)
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
    _register_local_subagent_executors(
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
        builtin_plugin_factory=_build_builtin_runtime_plugins,
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
        app=app,
    )


#  config.yaml 里提取
def _profiles_have_delegated_skills(profiles: dict[str, AgentProfile]) -> bool:
    """判断当前 profile 集合里是否存在 delegated skill.

    Args:
        profiles: 当前 runtime 已加载的 profile 映射.

    Returns:
        是否存在 `prefer_delegate` 或 `must_delegate` 的 skill assignment.
    """

    for profile in profiles.values():
        for assignment in profile.skill_assignments:
            if assignment.delegation_mode in {"prefer_delegate", "must_delegate"}:
                return True
    return False


def _register_local_subagent_executors(
    *,
    registry: SubagentExecutorRegistry,
    profiles: dict[str, AgentProfile],
    service: LocalSubagentExecutionService,
) -> None:
    """把已加载 profiles 注册成默认本地 subagent executors.

    Args:
        registry: subagent executor 注册表.
        profiles: 当前 runtime 已加载的 profile 映射.
        service: 复用 runtime 主线的本地 child run delegation 服务.
    """

    # region local profiles -> executors
    for profile in profiles.values():
        registry.register(
            profile.agent_id,
            service.execute,
            source="runtime:local_profile",
            metadata={
                "kind": "local_profile",
                "profile_name": profile.name,
            },
        )
    # endregion


#  config.yaml 里提取
def _build_profiles(config: Config) -> dict[str, AgentProfile]:
    """从配置对象构造 profile 映射.

    Args:
        config: 项目配置对象.

    Returns:
        `agent_id -> AgentProfile` 的映射表.
    """

    runtime_conf = config.get("runtime", {})
    agent_conf = config.get("agent", {})
    profiles_conf = runtime_conf.get("profiles", {})
    default_computer_policy = _build_default_computer_policy(config)
    if profiles_conf:
        profiles: dict[str, AgentProfile] = {}
        for agent_id, profile_conf in profiles_conf.items():
            profiles[agent_id] = AgentProfile(
                agent_id=agent_id,
                name=profile_conf.get("name", agent_id),
                prompt_ref=profile_conf.get("prompt_ref", f"prompt/{agent_id}"),
                default_model=profile_conf.get(
                    "default_model",
                    agent_conf.get("default_model", "gpt-4o-mini"),
                ),
                enabled_tools=list(profile_conf.get("enabled_tools", [])),
                skill_assignments=parse_skill_assignments(profile_conf.get("skill_assignments", [])),
                computer_policy=parse_computer_policy(
                    profile_conf.get("computer"),
                    defaults=default_computer_policy,
                ),
                config=dict(profile_conf),
            )
        return profiles

    default_agent_id = runtime_conf.get("default_agent_id", "default")
    return {
        default_agent_id: AgentProfile(
            agent_id=default_agent_id,
            name=runtime_conf.get("default_agent_name", default_agent_id),
            prompt_ref=runtime_conf.get("default_prompt_ref", "prompt/default"),
            default_model=agent_conf.get("default_model", "gpt-4o-mini"),
            enabled_tools=list(runtime_conf.get("enabled_tools", [])),
            skill_assignments=parse_skill_assignments(runtime_conf.get("skill_assignments", [])),
            computer_policy=default_computer_policy,
            config=dict(agent_conf),
        )
    }

# FS上的 profiles/
def _build_filesystem_profiles(config: Config) -> dict[str, AgentProfile]:
    """从 `profiles/` 目录构造 profile 映射.

    Args:
        config: 项目配置对象.

    Returns:
        文件系统中的 `agent_id -> AgentProfile` 映射表. 未启用时返回空映射.
    """

    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    # 拒绝未经允许的外部文件被加载
    if not bool(fs_conf.get("enabled", False)):
        return {}
    
    profiles_dir = _resolve_filesystem_path(
        config,
        fs_conf,
        key="profiles_dir",
        default="profiles",
    )
    default_model = str(
        runtime_conf.get("filesystem_default_model", "")
        or config.get("agent", {}).get("default_model", "gpt-4o-mini")
    )
    loader = FileSystemProfileLoader(
        profiles_dir,
        default_model=default_model,
        default_computer_policy=_build_default_computer_policy(config),
    )
    return loader.load_all()


def _build_prompt_map(
    config: Config,
    profiles: dict[str, AgentProfile],
) -> dict[str, str]:
    """从配置对象构造 prompt 文本映射.

    Args:
        config: 项目配置对象.
        profiles: 已经构造好的 profile 映射.

    Returns:
        `prompt_ref -> prompt text` 的映射表.
    """

    runtime_conf = config.get("runtime", {})
    agent_conf = config.get("agent", {})
    prompts = dict(runtime_conf.get("prompts", {}))
    default_prompt_text = str(agent_conf.get("system_prompt", "") or "")
    for profile in profiles.values():
        prompts.setdefault(profile.prompt_ref, default_prompt_text)
    return prompts


def _build_prompt_loader(
    config: Config,
    profiles: dict[str, AgentProfile],
) -> PromptLoader:
    """根据配置构造 prompt loader.

    Args:
        config: 项目配置对象.
        profiles: 当前可用的 profile 映射.

    Returns:
        PromptLoader 实例.
    """

    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    static_loader = StaticPromptLoader(_build_prompt_map(config, profiles))
    if not bool(fs_conf.get("enabled", False)):
        return static_loader

    prompts_dir = _resolve_filesystem_path(
        config,
        fs_conf,
        key="prompts_dir",
        default="prompts",
    )
    return ChainedPromptLoader(
        [
            FileSystemPromptLoader(prompts_dir),
            static_loader,
        ]
    )


def _resolve_filesystem_path(
    config: Config,
    fs_conf: dict[str, object],
    *,
    key: str,
    default: str,
) -> Path:
    """解析 runtime.filesystem 下的目录路径.

    Args:
        fs_conf: `runtime.filesystem` 配置字典.
        key: 要解析的字段名.
        default: 字段缺省时的目录名.

    Returns:
        解析后的 Path.
    """

    base_dir = Path(str(fs_conf.get("base_dir", ".") or "."))
    if not base_dir.is_absolute():
        base_dir = config.resolve_path(base_dir)
    raw_value = Path(str(fs_conf.get(key, default) or default))
    if raw_value.is_absolute():
        return raw_value
    return (base_dir / raw_value).resolve()


def _build_model_registry_manager(config: Config) -> FileSystemModelRegistryManager:
    """根据现有 filesystem layout 构造模型注册表管理器."""

    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    manager = FileSystemModelRegistryManager(
        providers_dir=_resolve_filesystem_path(
            config,
            fs_conf,
            key="model_providers_dir",
            default="models/providers",
        ),
        presets_dir=_resolve_filesystem_path(
            config,
            fs_conf,
            key="model_presets_dir",
            default="models/presets",
        ),
        bindings_dir=_resolve_filesystem_path(
            config,
            fs_conf,
            key="model_bindings_dir",
            default="models/bindings",
        ),
        legacy_global_default_model=str(config.get("agent", {}).get("default_model", "") or ""),
        legacy_summary_model=str(runtime_conf.get("context_compaction", {}).get("summary_model", "") or ""),
    )
    manager.reload_now()
    return manager


def _build_default_computer_policy(config: Config) -> ComputerPolicy:
    """根据 runtime.computer 构造全局默认 computer policy."""

    runtime_conf = config.get("runtime", {})
    computer_conf = dict(runtime_conf.get("computer", {}))
    defaults = ComputerPolicy(
        backend=str(computer_conf.get("backend", "host") or "host"),
        read_only=bool(computer_conf.get("read_only", False)),
        allow_write=bool(computer_conf.get("allow_write", True)),
        allow_exec=bool(computer_conf.get("allow_exec", True)),
        allow_sessions=bool(computer_conf.get("allow_sessions", True)),
        auto_stage_attachments=bool(computer_conf.get("auto_stage_attachments", True)),
        network_mode=str(computer_conf.get("network_mode", "enabled") or "enabled"),
    )
    return parse_computer_policy(computer_conf, defaults=defaults)

# region computer
def _build_computer_runtime(
    config: Config,
    *,
    gateway: GatewayProtocol,
    run_manager: RunManager,
) -> ComputerRuntime:
    """根据配置构造 computer 基础设施运行时入口."""

    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    computer_conf = dict(runtime_conf.get("computer", {}))
    root_dir = _resolve_filesystem_path(
        config,
        fs_conf,
        key="computer_root_dir",
        default=str(Path.home() / ".acabot" / "workspaces"),
    )
    skill_catalog_dir = _resolve_filesystem_path(
        config,
        fs_conf,
        key="skill_catalog_dir",
        default=str(root_dir / "catalog" / "skills"),
    )
    computer_config = ComputerRuntimeConfig(
        root_dir=str(root_dir),
        skill_catalog_dir=str(skill_catalog_dir),
        max_attachment_size_bytes=int(
            computer_conf.get("max_attachment_size_bytes", 64 * 1024 * 1024)
        ),
        max_total_attachment_bytes_per_run=int(
            computer_conf.get("max_total_attachment_bytes_per_run", 256 * 1024 * 1024)
        ),
        attachment_download_timeout_sec=int(
            computer_conf.get("attachment_download_timeout_sec", 30)
        ),
        attachment_download_retries=int(
            computer_conf.get("attachment_download_retries", 2)
        ),
        exec_stdout_window_bytes=int(
            computer_conf.get("exec_stdout_window_bytes", 256 * 1024)
        ),
        exec_stderr_window_bytes=int(
            computer_conf.get("exec_stderr_window_bytes", 256 * 1024)
        ),
        docker_image=str(computer_conf.get("docker_image", "python:3.12-slim") or "python:3.12-slim"),
        docker_network_mode=str(computer_conf.get("docker_network_mode", "bridge") or "bridge"),
        docker_read_only_rootfs=bool(computer_conf.get("docker_read_only_rootfs", True)),
    )
    return ComputerRuntime(
        config=computer_config,
        gateway=gateway,
        run_manager=run_manager,
        default_policy=_build_default_computer_policy(config),
    )


def _build_binding_rules(config: Config) -> list[BindingRule]:
    """从配置对象构造 binding rule 列表.

    Args:
        config: 项目配置对象.

    Returns:
        一个按配置声明顺序展开的 rule 列表.

    Raises:
        ValueError: 配置文件试图声明 runtime internal 的 `thread_id` rule.
    """

    runtime_conf = config.get("runtime", {})
    rules_conf = runtime_conf.get("binding_rules", [])
    rules: list[BindingRule] = []

    for index, rule_conf in enumerate(rules_conf):
        rules.append(
            _parse_binding_rule_config(
                rule_conf,
                default_rule_id=f"rule:{index}",
            )
        )

    return rules


def _build_filesystem_binding_rules(config: Config) -> list[BindingRule]:
    """从 `bindings/` 目录构造 binding rule 列表.

    Args:
        config: 项目配置对象.

    Returns:
        文件系统中的 binding rule 列表. 未启用时返回空列表.
    """

    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if not bool(fs_conf.get("enabled", False)):
        return []

    bindings_dir = _resolve_filesystem_path(
        config,
        fs_conf,
        key="bindings_dir",
        default="bindings",
    )
    loader = FileSystemBindingLoader(bindings_dir)
    rules: list[BindingRule] = []
    for index, rule_conf in enumerate(loader.load_all()):
        rules.append(
            _parse_binding_rule_config(
                rule_conf,
                default_rule_id=f"fs_rule:{index}",
            )
        )
    return rules


def _build_inbound_rules(config: Config) -> list[InboundRule]:
    """从配置对象构造 inbound rule 列表.

    Args:
        config: 项目配置对象.

    Returns:
        一个按配置声明顺序展开的 inbound rule 列表.
    """

    runtime_conf = config.get("runtime", {})
    rules_conf = runtime_conf.get("inbound_rules", [])
    rules: list[InboundRule] = []

    for index, rule_conf in enumerate(rules_conf):
        rules.append(
            _parse_inbound_rule_config(
                rule_conf,
                default_rule_id=f"inbound:{index}",
            )
        )

    return rules


def _build_filesystem_inbound_rules(config: Config) -> list[InboundRule]:
    """从 `inbound_rules/` 目录构造 inbound rule 列表.

    Args:
        config: 项目配置对象.

    Returns:
        文件系统中的 inbound rule 列表. 未启用时返回空列表.
    """

    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if not bool(fs_conf.get("enabled", False)):
        return []

    inbound_dir = _resolve_filesystem_path(
        config,
        fs_conf,
        key="inbound_rules_dir",
        default="inbound_rules",
    )
    loader = FileSystemInboundRuleLoader(inbound_dir)
    rules: list[InboundRule] = []
    for index, rule_conf in enumerate(loader.load_all()):
        rules.append(
            _parse_inbound_rule_config(
                rule_conf,
                default_rule_id=f"fs_inbound:{index}",
            )
        )
    return rules


def _build_event_policies(config: Config) -> list[EventPolicy]:
    """从配置对象构造 event policy 列表.

    Args:
        config: 项目配置对象.

    Returns:
        一个按配置声明顺序展开的 EventPolicy 列表.
    """

    runtime_conf = config.get("runtime", {})
    policies_conf = runtime_conf.get("event_policies", [])
    policies: list[EventPolicy] = []

    for index, policy_conf in enumerate(policies_conf):
        policies.append(
            _parse_event_policy_config(
                policy_conf,
                default_policy_id=f"event_policy:{index}",
            )
        )

    return policies


def _build_filesystem_event_policies(config: Config) -> list[EventPolicy]:
    """从 `event_policies/` 目录构造 event policy 列表.

    Args:
        config: 项目配置对象.

    Returns:
        文件系统中的 event policy 列表. 未启用时返回空列表.
    """

    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if not bool(fs_conf.get("enabled", False)):
        return []

    policies_dir = _resolve_filesystem_path(
        config,
        fs_conf,
        key="event_policies_dir",
        default="event_policies",
    )
    loader = FileSystemEventPolicyLoader(policies_dir)
    policies: list[EventPolicy] = []
    for index, policy_conf in enumerate(loader.load_all()):
        policies.append(
            _parse_event_policy_config(
                policy_conf,
                default_policy_id=f"fs_event_policy:{index}",
            )
        )
    return policies


# region persistence builders
def _build_thread_manager(config: Config) -> ThreadManager:
    """根据配置构造 ThreadManager.
    """

    sqlite_path = _get_persistence_sqlite_path(config)
    if sqlite_path is None:
        return InMemoryThreadManager()
    return StoreBackedThreadManager(SQLiteThreadStore(sqlite_path))


def _build_run_manager(config: Config) -> RunManager:
    """根据配置构造 RunManager.
    """

    sqlite_path = _get_persistence_sqlite_path(config)
    if sqlite_path is None:
        return InMemoryRunManager()
    return StoreBackedRunManager(SQLiteRunStore(sqlite_path))


def _build_message_store(config: Config) -> MessageStore:
    """根据配置构造 MessageStore.

    Args:
        config: 项目配置对象.

    Returns:
        默认的 MessageStore 实现.
    """

    sqlite_path = _get_persistence_sqlite_path(config)
    if sqlite_path is None:
        return InMemoryMessageStore()
    return SQLiteMessageStore(sqlite_path)


def _build_channel_event_store(config: Config) -> ChannelEventStore:
    """根据配置构造 ChannelEventStore.

    Args:
        config: 项目配置对象.

    Returns:
        默认的 ChannelEventStore 实现.
    """

    sqlite_path = _get_persistence_sqlite_path(config)
    if sqlite_path is None:
        return InMemoryChannelEventStore()
    return SQLiteChannelEventStore(sqlite_path)


def _build_memory_store(config: Config) -> MemoryStore:
    """根据配置构造 MemoryStore.

    Args:
        config: 项目配置对象.

    Returns:
        默认的 MemoryStore 实现.
    """

    sqlite_path = _get_persistence_sqlite_path(config)
    if sqlite_path is None:
        return InMemoryMemoryStore()
    return SQLiteMemoryStore(sqlite_path)


def _build_memory_broker(
    config: Config,
    *,
    memory_store: MemoryStore,
) -> MemoryBroker:
    """根据配置构造 MemoryBroker.

    Args:
        config: 项目配置对象.
        memory_store: 已经选定的 MemoryStore.

    Returns:
        默认的 MemoryBroker 实现.
    """

    _ = config
    return MemoryBroker(
        retriever=StoreBackedMemoryRetriever(memory_store),
        extractor=StructuredMemoryExtractor(memory_store),
    )


def _build_reference_backend(config: Config) -> ReferenceBackend:
    """根据配置构造 ReferenceBackend.

    Args:
        config: 项目配置对象.

    Returns:
        默认的 ReferenceBackend 实现.
    """

    runtime_conf = config.get("runtime", {})
    reference_conf = runtime_conf.get("reference", {})
    if not bool(reference_conf.get("enabled", False)):
        return NullReferenceBackend()

    provider = str(reference_conf.get("provider", "local"))
    if provider == "local":
        local_conf = dict(reference_conf.get("local", {}))
        sqlite_path = (
            local_conf.get("sqlite_path")
            or reference_conf.get("sqlite_path")
            or _get_persistence_sqlite_path(config)
            or "data/reference.sqlite3"
        )
        return LocalReferenceBackend(str(_resolve_runtime_path(config, sqlite_path)))

    if provider == "openviking":
        openviking_conf = dict(reference_conf.get("openviking", {}))
        return OpenVikingReferenceBackend(
            mode=str(openviking_conf.get("mode", "embedded")),
            path=_optional_str(openviking_conf.get("path")),
            base_uri=str(openviking_conf.get("base_uri", "viking://resources/acabot")),
        )

    raise ValueError(f"unsupported runtime.reference provider: {provider}")


def _build_retrieval_planner(
    config: Config,
) -> RetrievalPlanner:
    """根据配置构造 RetrievalPlanner.

    Args:
        config: 项目配置对象.
    Returns:
        默认的 RetrievalPlanner 实现.
    """

    runtime_conf = config.get("runtime", {})
    # prompt_assembly 配置
    prompt_conf = dict(runtime_conf.get("prompt_assembly", {}))
    
    return RetrievalPlanner(
        PromptAssemblyConfig(
            # sticky_notes 插入位置: 默认 system_message
            sticky_slot_position=str(prompt_conf.get("sticky_slot_position", "system_message")),
            # summary 插入位置: 默认 history_prefix 历史消息之前
            summary_slot_position=str(prompt_conf.get("summary_slot_position", "history_prefix")),
            # retrieved_memory 插入位置: 默认 system_message
            retrieval_slot_position=str(
                prompt_conf.get("retrieval_slot_position", "system_message")
            ),
            sticky_message_role=str(prompt_conf.get("sticky_message_role", "system")),
            summary_message_role=str(prompt_conf.get("summary_message_role", "user")),
            retrieval_message_role=str(prompt_conf.get("retrieval_message_role", "system")),
            sticky_intro=str(
                prompt_conf.get(
                    "sticky_intro",
                    "以下是稳定事实和长期规则. 默认可信, 除非当前上下文明确冲突.",
                )
            ),
            summary_prefix=str(
                prompt_conf.get(
                    "summary_prefix",
                    (
                        "The conversation history before this point was compacted into the following "
                        "summary:\n\n<summary>\n"
                    ),
                )
            ),
            summary_suffix=str(prompt_conf.get("summary_suffix", "\n</summary>")),
            retrieval_intro=str(
                prompt_conf.get(
                    "retrieval_intro",
                    "以下是按需检索到的记忆. 可能不完全准确, 需要结合当前上下文判断.",
                )
            ),
            # 默认检索范围(未指定时使用)
            default_scopes=[
                str(value) for value in prompt_conf.get(
                    "default_scopes",
                    ["relationship", "user", "channel", "global"],
                )
            ],
            # 默认读取的记忆类型
            default_memory_types=[
                str(value) for value in prompt_conf.get(
                    "default_memory_types",
                    ["sticky_note", "semantic", "relationship", "episodic"],
                )
            ],
        ),
    )


def _build_skill_catalog(config: Config) -> SkillCatalog:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    computer_root_dir = _resolve_filesystem_path(
        config,
        fs_conf,
        key="computer_root_dir",
        default=str(Path.home() / ".acabot" / "workspaces"),
    )
    skill_catalog_dir = _resolve_filesystem_path(
        config,
        fs_conf,
        key="skill_catalog_dir",
        default=str(computer_root_dir / "catalog" / "skills"),
    )
    catalog = SkillCatalog(FileSystemSkillPackageLoader(skill_catalog_dir))
    catalog.reload()
    return catalog


def _build_context_compactor(
    config: Config,
    *,
    agent: BaseAgent,
) -> ContextCompactor:
    """根据配置构造 ContextCompactor.

    Args:
        config: 项目配置对象.
        agent: 当前 runtime 使用的默认 agent.

    Returns:
        默认的 ContextCompactor 实现.
    """

    runtime_conf = config.get("runtime", {})
    compaction_conf = dict(runtime_conf.get("context_compaction", {}))
    compaction_config = ContextCompactionConfig(
        enabled=bool(compaction_conf.get("enabled", True)),
        strategy=str(compaction_conf.get("strategy", "truncate")),
        max_context_ratio=float(compaction_conf.get("max_context_ratio", 0.7)),
        preserve_recent_turns=int(compaction_conf.get("preserve_recent_turns", 6)),
        # 为固定 system prompt 预留的 token
        system_prompt_reserve_tokens=int(
            compaction_conf.get("system_prompt_reserve_tokens", 1500)
        ),
        # 为动态 prompt slots 预留的 token
        prompt_slot_reserve_tokens=int(
            compaction_conf.get("prompt_slot_reserve_tokens", 2500)
        ),
        # 为 tool schema 预留的 token
        tool_schema_reserve_tokens=int(
            compaction_conf.get("tool_schema_reserve_tokens", 3000)
        ),
        summary_model=str(compaction_conf.get("summary_model", "")),
        # 摘要最大字符数
        summary_max_chars=int(compaction_conf.get("summary_max_chars", 2400)),
        # 首次摘要的 system prompt
        summary_system_prompt=str(
            compaction_conf.get(
                "summary_system_prompt",
                ContextCompactionConfig.summary_system_prompt,
            )
        ),
        # 增量摘要的 system prompt
        update_summary_system_prompt=str(
            compaction_conf.get(
                "update_summary_system_prompt",
                ContextCompactionConfig.update_summary_system_prompt,
            )
        ),
        fallback_context_window=int(
            compaction_conf.get("fallback_context_window", 64000)
        ),
    )
    return ContextCompactor(
        compaction_config,
        summarizer=ModelContextSummarizer(agent=agent, config=compaction_config),
    )


def _get_persistence_sqlite_path(config: Config) -> str | None:
    """读取 runtime persistence 的 SQLite 路径.

    Args:
        config: 项目配置对象.

    Returns:
        配置中的 SQLite 路径. 未配置时返回 None.
    """

    runtime_conf = config.get("runtime", {})
    persistence_conf = runtime_conf.get("persistence", {})
    sqlite_path = persistence_conf.get("sqlite_path")
    if sqlite_path in (None, ""):
        return None
    return str(_resolve_runtime_path(config, sqlite_path))


def _resolve_runtime_path(config: Config, raw_path: object) -> Path:
    """把 runtime 配置中的路径解析到配置文件目录下."""

    return config.resolve_path(str(raw_path))
# endregion


def _optional_str(value: object) -> str | None:
    """把配置值转换成可选字符串.

    Args:
        value: 原始配置值.

    Returns:
        非空值时返回字符串, 空值时返回 None.
    """

    if value in (None, ""):
        return None
    return str(value)


def _parse_binding_rule_config(
    rule_conf: dict[str, object],
    *,
    default_rule_id: str,
) -> BindingRule:
    """把原始配置映射解析成 BindingRule.

    Args:
        rule_conf: 原始 rule 配置映射.
        default_rule_id: 配置未声明 rule_id 时使用的默认值.

    Returns:
        解析后的 BindingRule.

    Raises:
        ValueError: 配置文件试图声明 runtime internal 的 `thread_id`.
        KeyError: 配置缺少 `agent_id`.
    """

    match_conf = dict(rule_conf.get("match", {}))
    if "thread_id" in match_conf:
        raise ValueError("binding_rules in config must not declare thread_id")
    return BindingRule(
        rule_id=str(rule_conf.get("rule_id", default_rule_id)),
        agent_id=str(rule_conf["agent_id"]),
        priority=int(rule_conf.get("priority", 100)),
        thread_id=None,
        event_type=_optional_str(match_conf.get("event_type")),
        message_subtype=_optional_str(match_conf.get("message_subtype")),
        notice_type=_optional_str(match_conf.get("notice_type")),
        notice_subtype=_optional_str(match_conf.get("notice_subtype")),
        actor_id=_optional_str(match_conf.get("actor_id")),
        channel_scope=_optional_str(match_conf.get("channel_scope")),
        targets_self=_optional_bool(match_conf.get("targets_self")),
        mentioned_everyone=_optional_bool(match_conf.get("mentioned_everyone")),
        sender_roles=[str(role) for role in match_conf.get("sender_roles", [])],
        metadata=dict(rule_conf.get("metadata", {})),
    )


def _parse_inbound_rule_config(
    rule_conf: dict[str, object],
    *,
    default_rule_id: str,
) -> InboundRule:
    """把原始配置映射解析成 InboundRule.

    Args:
        rule_conf: 原始 inbound rule 配置映射.
        default_rule_id: 配置未声明 rule_id 时使用的默认值.

    Returns:
        解析后的 InboundRule.
    """

    match_conf = dict(rule_conf.get("match", {}))
    return InboundRule(
        rule_id=str(rule_conf.get("rule_id", default_rule_id)),
        run_mode=_parse_run_mode(rule_conf.get("run_mode", "respond")),
        priority=int(rule_conf.get("priority", 100)),
        platform=_optional_str(match_conf.get("platform")),
        event_type=_optional_str(match_conf.get("event_type")),
        message_subtype=_optional_str(match_conf.get("message_subtype")),
        notice_type=_optional_str(match_conf.get("notice_type")),
        notice_subtype=_optional_str(match_conf.get("notice_subtype")),
        actor_id=_optional_str(match_conf.get("actor_id")),
        channel_scope=_optional_str(match_conf.get("channel_scope")),
        targets_self=_optional_bool(match_conf.get("targets_self")),
        mentioned_everyone=_optional_bool(match_conf.get("mentioned_everyone")),
        sender_roles=[str(role) for role in match_conf.get("sender_roles", [])],
        metadata=dict(rule_conf.get("metadata", {})),
    )


def _parse_event_policy_config(
    policy_conf: dict[str, object],
    *,
    default_policy_id: str,
) -> EventPolicy:
    """把原始配置映射解析成 EventPolicy.

    Args:
        policy_conf: 原始 event policy 配置映射.
        default_policy_id: 配置未声明 policy_id 时使用的默认值.

    Returns:
        解析后的 EventPolicy.
    """

    match_conf = dict(policy_conf.get("match", {}))
    return EventPolicy(
        policy_id=str(policy_conf.get("policy_id", default_policy_id)),
        priority=int(policy_conf.get("priority", 100)),
        platform=_optional_str(match_conf.get("platform")),
        event_type=_optional_str(match_conf.get("event_type")),
        message_subtype=_optional_str(match_conf.get("message_subtype")),
        notice_type=_optional_str(match_conf.get("notice_type")),
        notice_subtype=_optional_str(match_conf.get("notice_subtype")),
        actor_id=_optional_str(match_conf.get("actor_id")),
        channel_scope=_optional_str(match_conf.get("channel_scope")),
        targets_self=_optional_bool(match_conf.get("targets_self")),
        mentioned_everyone=_optional_bool(match_conf.get("mentioned_everyone")),
        sender_roles=[str(role) for role in match_conf.get("sender_roles", [])],
        persist_event=bool(policy_conf.get("persist_event", True)),
        extract_to_memory=bool(policy_conf.get("extract_to_memory", False)),
        memory_scopes=[str(scope) for scope in policy_conf.get("memory_scopes", [])],
        tags=[str(tag) for tag in policy_conf.get("tags", [])],
        metadata=dict(policy_conf.get("metadata", {})),
    )


def _optional_bool(value: object) -> bool | None:
    """把配置值转换成可选布尔值.

    Args:
        value: 原始配置值.

    Returns:
        `True`, `False`, 或 `None`.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return bool(value)


def _parse_run_mode(value: object) -> str:
    """校验并规范化 run_mode 配置值.

    Args:
        value: 原始配置值.

    Returns:
        合法的 run_mode 字符串.

    Raises:
        ValueError: run_mode 不合法.
    """

    normalized = str(value)
    if normalized not in {"respond", "record_only", "silent_drop"}:
        raise ValueError(f"Unsupported run_mode: {normalized}")
    return normalized
