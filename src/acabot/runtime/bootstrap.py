r"""runtime.bootstrap 提供 runtime 默认组装入口.

组件关系:

    Config
      |
      v
    build_runtime_components()
      |
      +-- RuntimeRouter
      +-- ThreadManager / RunManager / MessageStore
      +-- ModelAgentRuntime
      +-- Outbox
      `-- RuntimeApp

负责把默认主线接起来.
不关心具体业务策略, 只决定默认组件如何装配.
"""

from __future__ import annotations

from dataclasses import dataclass

from acabot.agent import BaseAgent
from acabot.config import Config

from .agent_runtime import AgentRuntime
from .approval_resumer import ApprovalResumer, NoopApprovalResumer
from .app import RuntimeApp
from .event_policy import EventPolicyRegistry
from .event_store import InMemoryChannelEventStore
from .gateway_protocol import GatewayProtocol
from .memory_store import InMemoryMessageStore
from .model_agent_runtime import ModelAgentRuntime
from .models import AgentProfile, BindingRule, EventPolicy, InboundRule
from .outbox import Outbox
from .pipeline import ThreadPipeline
from .profile_loader import (
    AgentProfileRegistry,
    ProfileLoader,
    PromptLoader,
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
from .stores import ChannelEventStore, MessageStore
from .tool_broker import ToolBroker
from .threads import InMemoryThreadManager, StoreBackedThreadManager, ThreadManager


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
    prompt_loader: PromptLoader
    profile_loader: ProfileLoader
    tool_broker: ToolBroker
    agent_runtime: AgentRuntime
    approval_resumer: ApprovalResumer
    outbox: Outbox
    pipeline: ThreadPipeline
    app: RuntimeApp


def build_runtime_components(
    config: Config,
    *,
    gateway: GatewayProtocol,
    agent: BaseAgent,
    message_store: MessageStore | None = None,
    router: RuntimeRouter | None = None,
    thread_manager: ThreadManager | None = None,
    run_manager: RunManager | None = None,
    channel_event_store: ChannelEventStore | None = None,
    tool_broker: ToolBroker | None = None,
    approval_resumer: ApprovalResumer | None = None,
) -> RuntimeComponents:
    """根据配置和注入依赖组装一套最小 runtime 组件.

    Args:
        config: 项目配置对象.
        gateway: 平台 Gateway 实现.
        agent: 满足新 `BaseAgent` 契约的 agent.
        message_store: 可选的 MessageStore 实现.
        router: 可选的 RuntimeRouter 实现.
        thread_manager: 可选的 ThreadManager 实现.
        run_manager: 可选的 RunManager 实现.
        channel_event_store: 可选的 ChannelEventStore 实现.
        tool_broker: 可选的 ToolBroker 实现.
        approval_resumer: 可选的 approval resumer.

    Returns:
        一份包含 RuntimeApp 及其依赖组件的组装结果.
    """

    profiles = _build_profiles(config)
    prompt_loader = StaticPromptLoader(_build_prompt_map(config, profiles))
    runtime_conf = config.get("runtime", {})
    default_agent_id = runtime_conf.get("default_agent_id", next(iter(profiles)))
    rules = _build_binding_rules(config)
    inbound_rules = _build_inbound_rules(config)
    event_policies = _build_event_policies(config)
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
    runtime_tool_broker = tool_broker or ToolBroker()
    runtime_approval_resumer = approval_resumer or NoopApprovalResumer()
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
        tool_broker=runtime_tool_broker,
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
    )

    return RuntimeComponents(
        gateway=gateway,
        router=runtime_router,
        thread_manager=runtime_thread_manager,
        run_manager=runtime_run_manager,
        channel_event_store=runtime_channel_event_store,
        message_store=runtime_message_store,
        prompt_loader=prompt_loader,
        profile_loader=profile_registry,
        tool_broker=runtime_tool_broker,
        agent_runtime=agent_runtime,
        approval_resumer=runtime_approval_resumer,
        outbox=outbox,
        pipeline=pipeline,
        app=app,
    )


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
            config=dict(agent_conf),
        )
    }


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
        match_conf = dict(rule_conf.get("match", {}))
        if "thread_id" in match_conf:
            # thread_id 是 runtime internal
            # 配置文件只允许声明稳定的匹配条件 -> event_type, actor_id, channel_scope, sender_roles
            raise ValueError("binding_rules in config must not declare thread_id")
        rules.append(
            BindingRule(
                rule_id=str(rule_conf.get("rule_id", f"rule:{index}")),
                agent_id=str(rule_conf["agent_id"]),
                priority=int(rule_conf.get("priority", 100)),
                thread_id=None,
                event_type=_optional_str(match_conf.get("event_type")),
                actor_id=_optional_str(match_conf.get("actor_id")),
                channel_scope=_optional_str(match_conf.get("channel_scope")),
                sender_roles=[str(role) for role in match_conf.get("sender_roles", [])],
                metadata=dict(rule_conf.get("metadata", {})),
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
        match_conf = dict(rule_conf.get("match", {}))
        rules.append(
            InboundRule(
                rule_id=str(rule_conf.get("rule_id", f"inbound:{index}")),
                run_mode=_parse_run_mode(rule_conf.get("run_mode", "respond")),
                priority=int(rule_conf.get("priority", 100)),
                platform=_optional_str(match_conf.get("platform")),
                event_type=_optional_str(match_conf.get("event_type")),
                actor_id=_optional_str(match_conf.get("actor_id")),
                channel_scope=_optional_str(match_conf.get("channel_scope")),
                sender_roles=[str(role) for role in match_conf.get("sender_roles", [])],
                metadata=dict(rule_conf.get("metadata", {})),
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
        match_conf = dict(policy_conf.get("match", {}))
        policies.append(
            EventPolicy(
                policy_id=str(policy_conf.get("policy_id", f"event_policy:{index}")),
                priority=int(policy_conf.get("priority", 100)),
                platform=_optional_str(match_conf.get("platform")),
                event_type=_optional_str(match_conf.get("event_type")),
                actor_id=_optional_str(match_conf.get("actor_id")),
                channel_scope=_optional_str(match_conf.get("channel_scope")),
                sender_roles=[str(role) for role in match_conf.get("sender_roles", [])],
                persist_event=bool(policy_conf.get("persist_event", True)),
                extract_to_memory=bool(policy_conf.get("extract_to_memory", False)),
                memory_scopes=[str(scope) for scope in policy_conf.get("memory_scopes", [])],
                tags=[str(tag) for tag in policy_conf.get("tags", [])],
                metadata=dict(policy_conf.get("metadata", {})),
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
    return str(sqlite_path)
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
