"""runtime.bootstrap.loaders 构造 profile、prompt 和 session-runtime."""

from __future__ import annotations

from acabot.config import Config

from ..computer import ComputerPolicy, parse_computer_policy
from ..contracts import AgentProfile
from ..control.profile_loader import (
    ChainedPromptLoader,
    FileSystemProfileLoader,
    FileSystemPromptLoader,
    PromptLoader,
    StaticPromptLoader,
    normalize_enabled_tools,
    normalize_profile_config,
    resolve_profile_skills,
)
from ..control.session_loader import ConfigBackedSessionConfigLoader, SessionConfigLoader
from ..control.session_runtime import SessionRuntime
from ..subagents import SubagentCatalog
from .config import resolve_filesystem_path


def build_profiles(config: Config, *, default_computer_policy: ComputerPolicy) -> dict[str, AgentProfile]:
    """从运行配置构造 inline profiles.

    Args:
        config: 当前 runtime 配置.
        default_computer_policy: profile 未声明 computer 时的默认 policy.

    Returns:
        dict[str, AgentProfile]: 解析后的 profile 映射.
    """

    runtime_conf = dict(config.get("runtime", {}) or {})
    agent_conf = dict(config.get("agent", {}) or {})
    profiles_conf = runtime_conf.get("profiles", {})
    if profiles_conf:
        profiles: dict[str, AgentProfile] = {}
        for agent_id, profile_conf in profiles_conf.items():
            normalized = normalize_profile_config(dict(profile_conf or {}))
            profiles[agent_id] = AgentProfile(
                agent_id=agent_id,
                name=normalized.get("name", agent_id),
                prompt_ref=normalized.get("prompt_ref", f"prompt/{agent_id}"),
                enabled_tools=list(normalized.get("enabled_tools", [])),
                skills=resolve_profile_skills(normalized),
                computer_policy=parse_computer_policy(
                    normalized.get("computer"),
                    defaults=default_computer_policy,
                ),
                config=dict(normalized),
            )
        return profiles

    default_agent_id = runtime_conf.get("default_agent_id", "default")
    return {
        default_agent_id: AgentProfile(
            agent_id=default_agent_id,
            name=runtime_conf.get("default_agent_name", default_agent_id),
            prompt_ref=runtime_conf.get("default_prompt_ref", "prompt/default"),
            enabled_tools=normalize_enabled_tools(runtime_conf.get("enabled_tools", [])),
            skills=resolve_profile_skills(dict(runtime_conf)),
            computer_policy=default_computer_policy,
            config=dict(agent_conf),
        )
    }


def build_filesystem_profiles(config: Config, *, default_computer_policy: ComputerPolicy) -> dict[str, AgentProfile]:
    """从文件系统加载 profiles.

    Args:
        config: 当前 runtime 配置.
        default_computer_policy: profile 未声明 computer 时的默认 policy.

    Returns:
        dict[str, AgentProfile]: 文件系统 profile 映射.
    """

    runtime_conf = dict(config.get("runtime", {}) or {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if not bool(fs_conf.get("enabled", False)):
        return {}
    profiles_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="profiles_dir",
        default="profiles",
    )
    loader = FileSystemProfileLoader(
        profiles_dir,
        default_computer_policy=default_computer_policy,
    )
    return loader.load_all()


def build_prompt_map(
    config: Config,
    profiles: dict[str, AgentProfile],
) -> dict[str, str]:
    """构造 inline prompt 映射.

    Args:
        config: 当前 runtime 配置.
        profiles: 当前 profile 映射.

    Returns:
        dict[str, str]: `prompt_ref -> text` 映射.
    """

    runtime_conf = dict(config.get("runtime", {}) or {})
    agent_conf = dict(config.get("agent", {}) or {})
    prompts = dict(runtime_conf.get("prompts", {}))
    default_prompt_text = str(agent_conf.get("system_prompt", "") or "")
    for profile in profiles.values():
        prompts.setdefault(profile.prompt_ref, default_prompt_text)
    return prompts


def build_prompt_loader(
    config: Config,
    profiles: dict[str, AgentProfile],
    *,
    subagent_catalog: SubagentCatalog | None = None,
) -> PromptLoader:
    """构造 prompt loader.

    Args:
        config: 当前 runtime 配置.
        profiles: 当前 profile 映射.
        subagent_catalog: 可选的 subagent catalog, 用于注入 subagent prompt.

    Returns:
        PromptLoader: 当前有效 prompt loader.
    """

    runtime_conf = dict(config.get("runtime", {}) or {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    prompt_map = build_prompt_map(config, profiles)
    prompt_map.update(_build_subagent_prompt_map(subagent_catalog))
    static_loader = StaticPromptLoader(prompt_map)
    if not bool(fs_conf.get("enabled", False)):
        return static_loader
    prompts_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="prompts_dir",
        default="prompts",
    )
    return ChainedPromptLoader([
        FileSystemPromptLoader(prompts_dir),
        static_loader,
    ])


def _build_subagent_prompt_map(subagent_catalog: SubagentCatalog | None) -> dict[str, str]:
    """构造 subagent prompt 映射."""

    if subagent_catalog is None:
        return {}

    prompts: dict[str, str] = {}
    seen: set[str] = set()
    for manifest in subagent_catalog.list_all():
        subagent_name = manifest.subagent_name
        if subagent_name in seen:
            continue
        prompts[f"subagent/{subagent_name}"] = subagent_catalog.read(subagent_name).body_markdown
        seen.add(subagent_name)
    return prompts


def build_session_runtime(config: Config) -> SessionRuntime:
    """构造 session-config 驱动的决策运行时.

    Args:
        config: 当前 runtime 配置.

    Returns:
        SessionRuntime: 正式 session-config 决策运行时.
    """

    runtime_conf = dict(config.get("runtime", {}) or {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if "sessions_dir" in fs_conf:
        sessions_dir = resolve_filesystem_path(
            config,
            fs_conf,
            key="sessions_dir",
            default="sessions",
        )
        return SessionRuntime(SessionConfigLoader(config_root=sessions_dir))
    return SessionRuntime(ConfigBackedSessionConfigLoader(config))


__all__ = [
    "build_filesystem_profiles",
    "build_profiles",
    "build_prompt_loader",
    "build_session_runtime",
]
