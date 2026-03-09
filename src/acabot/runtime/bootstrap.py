"""runtime.bootstrap 提供新的 runtime 组装入口.

把 Config, gateway 和 legacy agent 接到新的 RuntimeApp 上.
让主线先能通过配置跑起来, 后续逐步替换旧 main 入口.
"""

from __future__ import annotations

from dataclasses import dataclass

from acabot.config import Config

from .agent_runtime import AgentRuntime
from .app import RuntimeApp
from .gateway_protocol import GatewayProtocol
from .legacy_agent_runtime import LegacyAgentProtocol, LegacyAgentRuntime
from .memory_store import InMemoryMessageStore
from .models import AgentProfile
from .outbox import Outbox
from .pipeline import ThreadPipeline
from .profile_loader import ProfileLoader, PromptLoader, StaticProfileLoader, StaticPromptLoader
from .router import RuntimeRouter
from .runs import InMemoryRunManager, RunManager
from .stores import MessageStore
from .threads import InMemoryThreadManager, ThreadManager


@dataclass(slots=True)
class RuntimeComponents:
    """runtime 组装结果.

    把会用到的关键组件集中返回, 便于 main 层接线和测试验证.
    """

    gateway: GatewayProtocol
    router: RuntimeRouter
    thread_manager: ThreadManager
    run_manager: RunManager
    message_store: MessageStore
    prompt_loader: PromptLoader
    profile_loader: ProfileLoader
    agent_runtime: AgentRuntime
    outbox: Outbox
    pipeline: ThreadPipeline
    app: RuntimeApp


def build_runtime_components(
    config: Config,
    *,
    gateway: GatewayProtocol,
    agent: LegacyAgentProtocol,
    message_store: MessageStore | None = None,
    router: RuntimeRouter | None = None,
    thread_manager: ThreadManager | None = None,
    run_manager: RunManager | None = None,
) -> RuntimeComponents:
    """根据配置和注入依赖组装一套最小 runtime 组件.

    Returns:
        一份包含 RuntimeApp 及其依赖组件的组装结果.
    """

    profiles = _build_profiles(config)
    prompt_loader = StaticPromptLoader(_build_prompt_map(config, profiles))
    runtime_conf = config.get("runtime", {})
    default_agent_id = runtime_conf.get("default_agent_id", next(iter(profiles)))

    profile_loader = StaticProfileLoader(
        profiles=profiles,
        default_agent_id=default_agent_id,
    )
    runtime_router = router or RuntimeRouter(default_agent_id=default_agent_id)
    runtime_thread_manager = thread_manager or InMemoryThreadManager()
    runtime_run_manager = run_manager or InMemoryRunManager()
    runtime_message_store = message_store or InMemoryMessageStore()
    agent_runtime = LegacyAgentRuntime(agent=agent, prompt_loader=prompt_loader)
    outbox = Outbox(gateway=gateway, store=runtime_message_store)
    pipeline = ThreadPipeline(
        agent_runtime=agent_runtime,
        outbox=outbox,
        run_manager=runtime_run_manager,
        thread_manager=runtime_thread_manager,
    )
    app = RuntimeApp(
        gateway=gateway,
        router=runtime_router,
        thread_manager=runtime_thread_manager,
        run_manager=runtime_run_manager,
        pipeline=pipeline,
        profile_loader=profile_loader.load,
    )

    return RuntimeComponents(
        gateway=gateway,
        router=runtime_router,
        thread_manager=runtime_thread_manager,
        run_manager=runtime_run_manager,
        message_store=runtime_message_store,
        prompt_loader=prompt_loader,
        profile_loader=profile_loader,
        agent_runtime=agent_runtime,
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
