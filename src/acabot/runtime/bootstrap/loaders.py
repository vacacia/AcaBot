"""runtime.bootstrap.loaders 构造 profile、prompt 和事件规则."""

from __future__ import annotations

from pathlib import Path

from acabot.config import Config

from ..computer import ComputerPolicy, parse_computer_policy
from ..contracts import AgentProfile, BindingRule, EventPolicy, InboundRule
from ..control.profile_loader import (
    ChainedPromptLoader,
    FileSystemBindingLoader,
    FileSystemEventPolicyLoader,
    FileSystemInboundRuleLoader,
    FileSystemProfileLoader,
    FileSystemPromptLoader,
    PromptLoader,
    StaticPromptLoader,
    normalize_profile_config,
    resolve_profile_skills,
)
from ..control.session_loader import SessionConfigLoader
from ..control.session_runtime import SessionRuntime
from .config import (
    parse_binding_rule_config,
    parse_event_policy_config,
    parse_inbound_rule_config,
    resolve_filesystem_path,
)


def build_profiles(config: Config, *, default_computer_policy: ComputerPolicy) -> dict[str, AgentProfile]:
    runtime_conf = config.get("runtime", {})
    agent_conf = config.get("agent", {})
    profiles_conf = runtime_conf.get("profiles", {})
    if profiles_conf:
        profiles: dict[str, AgentProfile] = {}
        for agent_id, profile_conf in profiles_conf.items():
            normalized = normalize_profile_config(dict(profile_conf or {}))
            profiles[agent_id] = AgentProfile(
                agent_id=agent_id,
                name=normalized.get("name", agent_id),
                prompt_ref=normalized.get("prompt_ref", f"prompt/{agent_id}"),
                default_model=normalized.get(
                    "default_model",
                    agent_conf.get("default_model", "gpt-4o-mini"),
                ),
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
            default_model=agent_conf.get("default_model", "gpt-4o-mini"),
            enabled_tools=list(runtime_conf.get("enabled_tools", [])),
            skills=resolve_profile_skills(dict(runtime_conf)),
            computer_policy=default_computer_policy,
            config=dict(agent_conf),
        )
    }


def build_filesystem_profiles(config: Config, *, default_computer_policy: ComputerPolicy) -> dict[str, AgentProfile]:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if not bool(fs_conf.get("enabled", False)):
        return {}
    profiles_dir = resolve_filesystem_path(
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
        default_computer_policy=default_computer_policy,
    )
    return loader.load_all()


def build_prompt_map(
    config: Config,
    profiles: dict[str, AgentProfile],
) -> dict[str, str]:
    runtime_conf = config.get("runtime", {})
    agent_conf = config.get("agent", {})
    prompts = dict(runtime_conf.get("prompts", {}))
    default_prompt_text = str(agent_conf.get("system_prompt", "") or "")
    for profile in profiles.values():
        prompts.setdefault(profile.prompt_ref, default_prompt_text)
    return prompts


def build_prompt_loader(
    config: Config,
    profiles: dict[str, AgentProfile],
) -> PromptLoader:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    static_loader = StaticPromptLoader(build_prompt_map(config, profiles))
    if not bool(fs_conf.get("enabled", False)):
        return static_loader
    prompts_dir = resolve_filesystem_path(
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


def build_binding_rules(config: Config) -> list[BindingRule]:
    runtime_conf = config.get("runtime", {})
    rules_conf = runtime_conf.get("binding_rules", [])
    return [
        parse_binding_rule_config(rule_conf, default_rule_id=f"rule:{index}")
        for index, rule_conf in enumerate(rules_conf)
    ]


def build_filesystem_binding_rules(config: Config) -> list[BindingRule]:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if not bool(fs_conf.get("enabled", False)):
        return []
    bindings_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="bindings_dir",
        default="bindings",
    )
    loader = FileSystemBindingLoader(bindings_dir)
    return [
        parse_binding_rule_config(rule_conf, default_rule_id=f"fs_rule:{index}")
        for index, rule_conf in enumerate(loader.load_all())
    ]


def build_inbound_rules(config: Config) -> list[InboundRule]:
    runtime_conf = config.get("runtime", {})
    rules_conf = runtime_conf.get("inbound_rules", [])
    return [
        parse_inbound_rule_config(rule_conf, default_rule_id=f"inbound:{index}")
        for index, rule_conf in enumerate(rules_conf)
    ]


def build_filesystem_inbound_rules(config: Config) -> list[InboundRule]:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if not bool(fs_conf.get("enabled", False)):
        return []
    inbound_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="inbound_rules_dir",
        default="inbound_rules",
    )
    loader = FileSystemInboundRuleLoader(inbound_dir)
    return [
        parse_inbound_rule_config(rule_conf, default_rule_id=f"fs_inbound:{index}")
        for index, rule_conf in enumerate(loader.load_all())
    ]


def build_event_policies(config: Config) -> list[EventPolicy]:
    runtime_conf = config.get("runtime", {})
    policies_conf = runtime_conf.get("event_policies", [])
    return [
        parse_event_policy_config(policy_conf, default_policy_id=f"event_policy:{index}")
        for index, policy_conf in enumerate(policies_conf)
    ]


def build_session_runtime(config: Config) -> SessionRuntime:
    """构造 session-config 驱动的决策运行时.

    Args:
        config: 当前 runtime 配置.

    Returns:
        SessionRuntime: 读取 `sessions/**/*.yaml` 的会话决策运行时.
    """

    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    sessions_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="sessions_dir",
        default="sessions",
    )
    return SessionRuntime(SessionConfigLoader(config_root=sessions_dir))


def build_filesystem_event_policies(config: Config) -> list[EventPolicy]:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if not bool(fs_conf.get("enabled", False)):
        return []
    policies_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="event_policies_dir",
        default="event_policies",
    )
    loader = FileSystemEventPolicyLoader(policies_dir)
    return [
        parse_event_policy_config(policy_conf, default_policy_id=f"fs_event_policy:{index}")
        for index, policy_conf in enumerate(loader.load_all())
    ]


__all__ = [
    "build_binding_rules",
    "build_event_policies",
    "build_filesystem_binding_rules",
    "build_filesystem_event_policies",
    "build_filesystem_inbound_rules",
    "build_filesystem_profiles",
    "build_profiles",
    "build_inbound_rules",
    "build_prompt_loader",
    "build_session_runtime",
]
