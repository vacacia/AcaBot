"""runtime.config_control_plane 提供 WebUI 需要的配置真源读写与热刷新."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import importlib
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from acabot.config import Config

from ..computer import ComputerPolicy, parse_computer_policy
from .event_policy import EventPolicyRegistry
from ..contracts import AgentProfile, BindingRule, EventPolicy, InboundRule, SkillAssignment
from ..plugin_manager import RuntimePluginManager
from .profile_loader import (
    AgentProfileRegistry,
    ChainedPromptLoader,
    FileSystemBindingLoader,
    FileSystemEventPolicyLoader,
    FileSystemInboundRuleLoader,
    FileSystemProfileLoader,
    FileSystemPromptLoader,
    PromptLoader,
    ReloadablePromptLoader,
    StaticPromptLoader,
    parse_skill_assignments,
)
from ..router import InboundRuleRegistry, RuntimeRouter
from ..skills import SkillCatalog
from ..subagents import SubagentExecutorRegistry


def _resolve_filesystem_path(
    config: Config,
    fs_conf: dict[str, object],
    *,
    key: str,
    default: str,
) -> Path:
    base_dir = Path(str(fs_conf.get("base_dir", ".") or "."))
    if not base_dir.is_absolute():
        base_dir = config.resolve_path(base_dir)
    raw_value = Path(str(fs_conf.get(key, default) or default))
    if raw_value.is_absolute():
        return raw_value
    return (base_dir / raw_value).resolve()


def _default_computer_policy(config: Config) -> ComputerPolicy:
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


def _build_profiles(config: Config) -> dict[str, AgentProfile]:
    runtime_conf = config.get("runtime", {})
    agent_conf = config.get("agent", {})
    profiles_conf = runtime_conf.get("profiles", {})
    default_policy = _default_computer_policy(config)
    if profiles_conf:
        profiles: dict[str, AgentProfile] = {}
        for agent_id, profile_conf in dict(profiles_conf).items():
            profile_map = dict(profile_conf or {})
            profiles[agent_id] = AgentProfile(
                agent_id=agent_id,
                name=str(profile_map.get("name", agent_id) or agent_id),
                prompt_ref=str(profile_map.get("prompt_ref", f"prompt/{agent_id}") or f"prompt/{agent_id}"),
                default_model=str(
                    profile_map.get("default_model", agent_conf.get("default_model", "gpt-4o-mini"))
                    or agent_conf.get("default_model", "gpt-4o-mini")
                ),
                enabled_tools=[str(item) for item in list(profile_map.get("enabled_tools", []) or [])],
                skill_assignments=parse_skill_assignments(profile_map.get("skill_assignments", [])),
                computer_policy=parse_computer_policy(
                    profile_map.get("computer"),
                    defaults=default_policy,
                ),
                config=dict(profile_map),
            )
        return profiles

    default_agent_id = str(runtime_conf.get("default_agent_id", "default") or "default")
    return {
        default_agent_id: AgentProfile(
            agent_id=default_agent_id,
            name=str(runtime_conf.get("default_agent_name", default_agent_id) or default_agent_id),
            prompt_ref=str(runtime_conf.get("default_prompt_ref", "prompt/default") or "prompt/default"),
            default_model=str(agent_conf.get("default_model", "gpt-4o-mini") or "gpt-4o-mini"),
            enabled_tools=[str(item) for item in list(runtime_conf.get("enabled_tools", []) or [])],
            skill_assignments=parse_skill_assignments(runtime_conf.get("skill_assignments", [])),
            computer_policy=default_policy,
            config=dict(agent_conf),
        )
    }


def _build_filesystem_profiles(config: Config) -> dict[str, AgentProfile]:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if not bool(fs_conf.get("enabled", False)):
        return {}
    profiles_dir = _resolve_filesystem_path(config, fs_conf, key="profiles_dir", default="profiles")
    default_model = str(
        runtime_conf.get("filesystem_default_model", "")
        or config.get("agent", {}).get("default_model", "gpt-4o-mini")
    )
    loader = FileSystemProfileLoader(
        profiles_dir,
        default_model=default_model,
        default_computer_policy=_default_computer_policy(config),
    )
    return loader.load_all()


def _build_prompt_map(config: Config, profiles: dict[str, AgentProfile]) -> dict[str, str]:
    runtime_conf = config.get("runtime", {})
    agent_conf = config.get("agent", {})
    prompts = dict(runtime_conf.get("prompts", {}) or {})
    default_prompt_text = str(agent_conf.get("system_prompt", "") or "")
    for profile in profiles.values():
        prompts.setdefault(profile.prompt_ref, default_prompt_text)
    return prompts


def _build_prompt_loader(config: Config, profiles: dict[str, AgentProfile]) -> PromptLoader:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    static_loader = StaticPromptLoader(_build_prompt_map(config, profiles))
    if not bool(fs_conf.get("enabled", False)):
        return static_loader
    prompts_dir = _resolve_filesystem_path(config, fs_conf, key="prompts_dir", default="prompts")
    return ChainedPromptLoader(
        [
            FileSystemPromptLoader(prompts_dir),
            static_loader,
        ]
    )


def _optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_bool(value: object) -> bool | None:
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
    normalized = str(value or "respond")
    if normalized not in {"respond", "record_only", "silent_drop"}:
        raise ValueError(f"Unsupported run_mode: {normalized}")
    return normalized


def _parse_binding_rule_config(rule_conf: dict[str, object], *, default_rule_id: str) -> BindingRule:
    match_conf = dict(rule_conf.get("match", {}))
    if "thread_id" in match_conf:
        raise ValueError("binding_rules in config must not declare thread_id")
    return BindingRule(
        rule_id=str(rule_conf.get("rule_id", default_rule_id) or default_rule_id),
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
        mentions_self=_optional_bool(match_conf.get("mentions_self")),
        mentioned_everyone=_optional_bool(match_conf.get("mentioned_everyone")),
        reply_targets_self=_optional_bool(match_conf.get("reply_targets_self")),
        sender_roles=[str(role) for role in list(match_conf.get("sender_roles", []) or [])],
        metadata=dict(rule_conf.get("metadata", {}) or {}),
    )


def _parse_inbound_rule_config(rule_conf: dict[str, object], *, default_rule_id: str) -> InboundRule:
    match_conf = dict(rule_conf.get("match", {}))
    return InboundRule(
        rule_id=str(rule_conf.get("rule_id", default_rule_id) or default_rule_id),
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
        mentions_self=_optional_bool(match_conf.get("mentions_self")),
        mentioned_everyone=_optional_bool(match_conf.get("mentioned_everyone")),
        reply_targets_self=_optional_bool(match_conf.get("reply_targets_self")),
        sender_roles=[str(role) for role in list(match_conf.get("sender_roles", []) or [])],
        metadata=dict(rule_conf.get("metadata", {}) or {}),
    )


def _parse_event_policy_config(policy_conf: dict[str, object], *, default_policy_id: str) -> EventPolicy:
    match_conf = dict(policy_conf.get("match", {}))
    return EventPolicy(
        policy_id=str(policy_conf.get("policy_id", default_policy_id) or default_policy_id),
        priority=int(policy_conf.get("priority", 100)),
        platform=_optional_str(match_conf.get("platform")),
        event_type=_optional_str(match_conf.get("event_type")),
        message_subtype=_optional_str(match_conf.get("message_subtype")),
        notice_type=_optional_str(match_conf.get("notice_type")),
        notice_subtype=_optional_str(match_conf.get("notice_subtype")),
        actor_id=_optional_str(match_conf.get("actor_id")),
        channel_scope=_optional_str(match_conf.get("channel_scope")),
        targets_self=_optional_bool(match_conf.get("targets_self")),
        mentions_self=_optional_bool(match_conf.get("mentions_self")),
        mentioned_everyone=_optional_bool(match_conf.get("mentioned_everyone")),
        reply_targets_self=_optional_bool(match_conf.get("reply_targets_self")),
        sender_roles=[str(role) for role in list(match_conf.get("sender_roles", []) or [])],
        persist_event=bool(policy_conf.get("persist_event", True)),
        extract_to_memory=bool(policy_conf.get("extract_to_memory", False)),
        memory_scopes=[str(scope) for scope in list(policy_conf.get("memory_scopes", []) or [])],
        tags=[str(tag) for tag in list(policy_conf.get("tags", []) or [])],
        metadata=dict(policy_conf.get("metadata", {}) or {}),
    )


def _build_binding_rules(config: Config) -> list[BindingRule]:
    runtime_conf = config.get("runtime", {})
    rules: list[BindingRule] = []
    for index, rule_conf in enumerate(list(runtime_conf.get("binding_rules", []) or [])):
        rules.append(_parse_binding_rule_config(dict(rule_conf or {}), default_rule_id=f"rule:{index}"))
    return rules


def _build_filesystem_binding_rules(config: Config) -> list[BindingRule]:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if not bool(fs_conf.get("enabled", False)):
        return []
    loader = FileSystemBindingLoader(_resolve_filesystem_path(config, fs_conf, key="bindings_dir", default="bindings"))
    return [
        _parse_binding_rule_config(dict(rule_conf or {}), default_rule_id=f"fs_rule:{index}")
        for index, rule_conf in enumerate(loader.load_all())
    ]


def _build_inbound_rules(config: Config) -> list[InboundRule]:
    runtime_conf = config.get("runtime", {})
    rules: list[InboundRule] = []
    for index, rule_conf in enumerate(list(runtime_conf.get("inbound_rules", []) or [])):
        rules.append(_parse_inbound_rule_config(dict(rule_conf or {}), default_rule_id=f"inbound:{index}"))
    return rules


def _build_filesystem_inbound_rules(config: Config) -> list[InboundRule]:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if not bool(fs_conf.get("enabled", False)):
        return []
    loader = FileSystemInboundRuleLoader(
        _resolve_filesystem_path(config, fs_conf, key="inbound_rules_dir", default="inbound_rules")
    )
    return [
        _parse_inbound_rule_config(dict(rule_conf or {}), default_rule_id=f"fs_inbound:{index}")
        for index, rule_conf in enumerate(loader.load_all())
    ]


def _build_event_policies(config: Config) -> list[EventPolicy]:
    runtime_conf = config.get("runtime", {})
    policies: list[EventPolicy] = []
    for index, policy_conf in enumerate(list(runtime_conf.get("event_policies", []) or [])):
        policies.append(
            _parse_event_policy_config(dict(policy_conf or {}), default_policy_id=f"event_policy:{index}")
        )
    return policies


def _build_filesystem_event_policies(config: Config) -> list[EventPolicy]:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if not bool(fs_conf.get("enabled", False)):
        return []
    loader = FileSystemEventPolicyLoader(
        _resolve_filesystem_path(config, fs_conf, key="event_policies_dir", default="event_policies")
    )
    return [
        _parse_event_policy_config(dict(policy_conf or {}), default_policy_id=f"fs_event_policy:{index}")
        for index, policy_conf in enumerate(loader.load_all())
    ]


def _profile_to_config(profile: AgentProfile) -> dict[str, Any]:
    data = dict(profile.config)
    data["agent_id"] = profile.agent_id
    data["name"] = profile.name
    data["prompt_ref"] = profile.prompt_ref
    data["default_model"] = profile.default_model
    data["enabled_tools"] = list(profile.enabled_tools)
    data["skill_assignments"] = [_skill_assignment_to_config(item) for item in profile.skill_assignments]
    if profile.computer_policy is not None:
        data["computer"] = {
            "backend": profile.computer_policy.backend,
            "read_only": profile.computer_policy.read_only,
            "allow_write": profile.computer_policy.allow_write,
            "allow_exec": profile.computer_policy.allow_exec,
            "allow_sessions": profile.computer_policy.allow_sessions,
            "auto_stage_attachments": profile.computer_policy.auto_stage_attachments,
            "network_mode": profile.computer_policy.network_mode,
        }
    return data


def _skill_assignment_to_config(item: SkillAssignment) -> dict[str, Any]:
    data: dict[str, Any] = {"skill_name": item.skill_name}
    if item.delegation_mode != "inline":
        data["delegation_mode"] = item.delegation_mode
    if item.delegate_agent_id:
        data["delegate_agent_id"] = item.delegate_agent_id
    if item.notes:
        data["notes"] = item.notes
    data.update(dict(item.metadata))
    return data


def _binding_rule_to_config(rule: BindingRule) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "agent_id": rule.agent_id,
        "priority": rule.priority,
        "match": {
            key: value
            for key, value in {
                "event_type": rule.event_type,
                "message_subtype": rule.message_subtype,
                "notice_type": rule.notice_type,
                "notice_subtype": rule.notice_subtype,
                "actor_id": rule.actor_id,
                "channel_scope": rule.channel_scope,
                "targets_self": rule.targets_self,
                "mentions_self": rule.mentions_self,
                "mentioned_everyone": rule.mentioned_everyone,
                "reply_targets_self": rule.reply_targets_self,
                "sender_roles": list(rule.sender_roles) or None,
            }.items()
            if value not in (None, "", [])
        },
        "metadata": dict(rule.metadata),
    }


def _inbound_rule_to_config(rule: InboundRule) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "run_mode": rule.run_mode,
        "priority": rule.priority,
        "match": {
            key: value
            for key, value in {
                "platform": rule.platform,
                "event_type": rule.event_type,
                "message_subtype": rule.message_subtype,
                "notice_type": rule.notice_type,
                "notice_subtype": rule.notice_subtype,
                "actor_id": rule.actor_id,
                "channel_scope": rule.channel_scope,
                "targets_self": rule.targets_self,
                "mentions_self": rule.mentions_self,
                "mentioned_everyone": rule.mentioned_everyone,
                "reply_targets_self": rule.reply_targets_self,
                "sender_roles": list(rule.sender_roles) or None,
            }.items()
            if value not in (None, "", [])
        },
        "metadata": dict(rule.metadata),
    }


def _event_policy_to_config(policy: EventPolicy) -> dict[str, Any]:
    return {
        "policy_id": policy.policy_id,
        "priority": policy.priority,
        "match": {
            key: value
            for key, value in {
                "platform": policy.platform,
                "event_type": policy.event_type,
                "message_subtype": policy.message_subtype,
                "notice_type": policy.notice_type,
                "notice_subtype": policy.notice_subtype,
                "actor_id": policy.actor_id,
                "channel_scope": policy.channel_scope,
                "targets_self": policy.targets_self,
                "mentions_self": policy.mentions_self,
                "mentioned_everyone": policy.mentioned_everyone,
                "reply_targets_self": policy.reply_targets_self,
                "sender_roles": list(policy.sender_roles) or None,
            }.items()
            if value not in (None, "", [])
        },
        "persist_event": policy.persist_event,
        "extract_to_memory": policy.extract_to_memory,
        "memory_scopes": list(policy.memory_scopes),
        "tags": list(policy.tags),
        "metadata": dict(policy.metadata),
    }


class RuntimeConfigControlPlane:
    """面向 WebUI 的 runtime 配置读写与热刷新服务."""

    def __init__(
        self,
        *,
        config: Config,
        router: RuntimeRouter,
        profile_registry: AgentProfileRegistry,
        inbound_registry: InboundRuleRegistry,
        event_policy_registry: EventPolicyRegistry,
        prompt_loader: ReloadablePromptLoader,
        skill_catalog: SkillCatalog | None = None,
        plugin_manager: RuntimePluginManager | None = None,
        subagent_executor_registry: SubagentExecutorRegistry | None = None,
        local_subagent_executor: Callable[[Any], Awaitable[Any]] | None = None,
        builtin_plugin_factory: Callable[[dict[str, AgentProfile]], list[Any]] | None = None,
    ) -> None:
        self.config = config
        self.router = router
        self.profile_registry = profile_registry
        self.inbound_registry = inbound_registry
        self.event_policy_registry = event_policy_registry
        self.prompt_loader = prompt_loader
        self.skill_catalog = skill_catalog
        self.plugin_manager = plugin_manager
        self.subagent_executor_registry = subagent_executor_registry
        self.local_subagent_executor = local_subagent_executor
        self.builtin_plugin_factory = builtin_plugin_factory

    def storage_mode(self) -> str:
        runtime_conf = self.config.get("runtime", {})
        fs_conf = dict(runtime_conf.get("filesystem", {}))
        return "filesystem" if bool(fs_conf.get("enabled", False)) else "inline"

    async def reload_runtime_configuration(self) -> dict[str, Any]:
        self.config.reload_from_file()
        runtime_conf = self.config.get("runtime", {})
        profiles = _build_profiles(self.config)
        profiles.update(_build_filesystem_profiles(self.config))
        if not profiles:
            raise ValueError("runtime configuration must contain at least one profile")
        default_agent_id = str(runtime_conf.get("default_agent_id", next(iter(profiles))) or next(iter(profiles)))
        rules = _build_binding_rules(self.config) + _build_filesystem_binding_rules(self.config)
        inbound_rules = _build_inbound_rules(self.config) + _build_filesystem_inbound_rules(self.config)
        event_policies = _build_event_policies(self.config) + _build_filesystem_event_policies(self.config)

        self.profile_registry.reload(
            profiles=profiles,
            default_agent_id=default_agent_id,
            rules=rules,
        )
        self.inbound_registry.reload(inbound_rules)
        self.event_policy_registry.reload(event_policies)
        self.prompt_loader.replace_loader(_build_prompt_loader(self.config, profiles))
        self.router.default_agent_id = default_agent_id
        if self.skill_catalog is not None:
            self.skill_catalog.reload()
        if self.subagent_executor_registry is not None:
            self.subagent_executor_registry.unregister_source("runtime:local_profile")
            if self.local_subagent_executor is not None:
                for profile in profiles.values():
                    self.subagent_executor_registry.register(
                        profile.agent_id,
                        self.local_subagent_executor,
                        source="runtime:local_profile",
                        metadata={
                            "kind": "local_profile",
                            "profile_name": profile.name,
                        },
                    )
        if self.plugin_manager is not None:
            builtin_plugins = (
                self.builtin_plugin_factory(profiles)
                if self.builtin_plugin_factory is not None
                else []
            )
            await self.plugin_manager.replace_builtin_plugins(builtin_plugins)
        return {
            "default_agent_id": default_agent_id,
            "profile_count": len(profiles),
            "binding_rule_count": len(rules),
            "inbound_rule_count": len(inbound_rules),
            "event_policy_count": len(event_policies),
            "storage_mode": self.storage_mode(),
        }

    def list_profiles(self) -> list[dict[str, Any]]:
        return [_profile_to_config(item) for item in self.profile_registry.list_profiles()]

    def get_gateway_config(self) -> dict[str, Any]:
        gateway_conf = dict(self.config.get("gateway", {}) or {})
        return {
            "host": str(gateway_conf.get("host", "0.0.0.0") or "0.0.0.0"),
            "port": int(gateway_conf.get("port", 8080) or 8080),
            "timeout": float(gateway_conf.get("timeout", 10.0) or 10.0),
            "token": str(gateway_conf.get("token", "") or ""),
        }

    async def upsert_gateway_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        gateway_conf = self.get_gateway_config()
        next_conf = {
            "host": str(payload.get("host", gateway_conf["host"]) or gateway_conf["host"]),
            "port": int(payload.get("port", gateway_conf["port"]) or gateway_conf["port"]),
            "timeout": float(payload.get("timeout", gateway_conf["timeout"]) or gateway_conf["timeout"]),
            "token": str(payload.get("token", gateway_conf["token"]) or ""),
        }
        data = self.config.to_dict()
        data["gateway"] = next_conf
        self.config.replace(data)
        self.config.save()
        return self.get_gateway_config()

    def get_profile(self, agent_id: str) -> dict[str, Any] | None:
        profile = self.profile_registry.profiles.get(agent_id)
        if profile is None:
            return None
        return _profile_to_config(profile)

    async def upsert_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(payload.get("agent_id", "") or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        normalized = dict(payload)
        normalized["agent_id"] = agent_id
        normalized.setdefault("name", agent_id)
        normalized.setdefault("prompt_ref", f"prompt/{agent_id}")
        normalized.setdefault("enabled_tools", [])
        normalized.setdefault("skill_assignments", [])
        if self.storage_mode() == "filesystem":
            path = self._profiles_dir() / f"{agent_id}.yaml"
            self._write_yaml(path, normalized)
        else:
            data = self.config.to_dict()
            runtime_conf = dict(data.get("runtime", {}) or {})
            profiles_conf = dict(runtime_conf.get("profiles", {}) or {})
            profile_payload = dict(normalized)
            profile_payload.pop("agent_id", None)
            profiles_conf[agent_id] = profile_payload
            runtime_conf["profiles"] = profiles_conf
            data["runtime"] = runtime_conf
            self.config.replace(data)
            self.config.save()
        await self.reload_runtime_configuration()
        result = self.get_profile(agent_id)
        if result is None:
            raise RuntimeError("profile reload failed")
        return result

    async def delete_profile(self, agent_id: str) -> bool:
        existed = False
        if self.storage_mode() == "filesystem":
            path = self._profiles_dir() / f"{agent_id}.yaml"
            if path.exists():
                path.unlink()
                existed = True
        else:
            data = self.config.to_dict()
            runtime_conf = dict(data.get("runtime", {}) or {})
            profiles_conf = dict(runtime_conf.get("profiles", {}) or {})
            if agent_id in profiles_conf:
                existed = True
                profiles_conf.pop(agent_id, None)
                runtime_conf["profiles"] = profiles_conf
                data["runtime"] = runtime_conf
                self.config.replace(data)
                self.config.save()
        if existed:
            await self.reload_runtime_configuration()
        return existed

    def list_prompts(self) -> list[dict[str, Any]]:
        prompts: list[dict[str, Any]] = []
        seen: set[str] = set()
        runtime_conf = self.config.get("runtime", {})
        for prompt_ref, content in sorted(dict(runtime_conf.get("prompts", {}) or {}).items()):
            prompts.append({
                "prompt_ref": str(prompt_ref),
                "content": str(content or ""),
                "source": "inline",
            })
            seen.add(str(prompt_ref))
        if self.storage_mode() == "filesystem":
            prompts_dir = self._prompts_dir()
            if prompts_dir.exists():
                for path in sorted(prompts_dir.rglob("*")):
                    if not path.is_file() or path.suffix not in {".md", ".txt", ".prompt"}:
                        continue
                    prompt_ref = self._prompt_ref_from_path(path)
                    if prompt_ref in seen:
                        continue
                    prompts.append({
                        "prompt_ref": prompt_ref,
                        "content": path.read_text(encoding="utf-8"),
                        "source": "filesystem",
                    })
                    seen.add(prompt_ref)
        return prompts

    def get_prompt(self, prompt_ref: str) -> dict[str, Any] | None:
        prompt_ref = str(prompt_ref or "").strip()
        if not prompt_ref:
            return None
        runtime_conf = self.config.get("runtime", {})
        prompts_conf = dict(runtime_conf.get("prompts", {}) or {})
        if prompt_ref in prompts_conf:
            return {
                "prompt_ref": prompt_ref,
                "content": str(prompts_conf[prompt_ref] or ""),
                "source": "inline",
            }
        if self.storage_mode() != "filesystem":
            return None
        path = self._resolve_prompt_path(prompt_ref)
        if path is None or not path.exists():
            return None
        return {
            "prompt_ref": prompt_ref,
            "content": path.read_text(encoding="utf-8"),
            "source": "filesystem",
        }

    async def upsert_prompt(self, prompt_ref: str, content: str) -> dict[str, Any]:
        prompt_ref = str(prompt_ref or "").strip()
        if not prompt_ref.startswith("prompt/"):
            raise ValueError("prompt_ref must start with 'prompt/'")
        if self.storage_mode() == "filesystem":
            path = self._path_for_prompt_ref(prompt_ref)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        else:
            data = self.config.to_dict()
            runtime_conf = dict(data.get("runtime", {}) or {})
            prompts_conf = dict(runtime_conf.get("prompts", {}) or {})
            prompts_conf[prompt_ref] = str(content)
            runtime_conf["prompts"] = prompts_conf
            data["runtime"] = runtime_conf
            self.config.replace(data)
            self.config.save()
        await self.reload_runtime_configuration()
        result = self.get_prompt(prompt_ref)
        if result is None:
            raise RuntimeError("prompt reload failed")
        return result

    async def delete_prompt(self, prompt_ref: str) -> bool:
        existed = False
        if self.storage_mode() == "filesystem":
            path = self._resolve_prompt_path(prompt_ref)
            if path is None:
                path = self._path_for_prompt_ref(prompt_ref)
            if path.exists():
                path.unlink()
                existed = True
        else:
            data = self.config.to_dict()
            runtime_conf = dict(data.get("runtime", {}) or {})
            prompts_conf = dict(runtime_conf.get("prompts", {}) or {})
            if prompt_ref in prompts_conf:
                prompts_conf.pop(prompt_ref, None)
                runtime_conf["prompts"] = prompts_conf
                data["runtime"] = runtime_conf
                self.config.replace(data)
                self.config.save()
                existed = True
        if existed:
            await self.reload_runtime_configuration()
        return existed

    def list_plugin_configs(self) -> list[dict[str, Any]]:
        """返回 runtime.plugins 的配置视图, 供 WebUI 开关插件使用."""

        runtime_conf = dict(self.config.get("runtime", {}) or {})
        raw_plugins = list(runtime_conf.get("plugins", []) or [])
        items: list[dict[str, Any]] = []
        for raw in raw_plugins:
            if isinstance(raw, str):
                items.append({
                    "path": raw,
                    "enabled": True,
                    "name": self._plugin_name_from_path(raw),
                })
                continue
            if isinstance(raw, dict):
                import_path = str(raw.get("path", "") or raw.get("import_path", "") or "")
                if not import_path:
                    continue
                items.append({
                    "path": import_path,
                    "enabled": bool(raw.get("enabled", True)),
                    "name": self._plugin_name_from_path(import_path),
                })
        return items

    async def replace_plugin_configs(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """整批替换 runtime.plugins 配置并热刷新."""

        normalized: list[dict[str, Any]] = []
        for item in items:
            import_path = str(item.get("path", "") or item.get("import_path", "") or "").strip()
            if not import_path:
                continue
            normalized.append({
                "path": import_path,
                "enabled": bool(item.get("enabled", True)),
            })
        data = self.config.to_dict()
        runtime_conf = dict(data.get("runtime", {}) or {})
        runtime_conf["plugins"] = normalized
        data["runtime"] = runtime_conf
        self.config.replace(data)
        self.config.save()
        await self.reload_runtime_configuration()
        return self.list_plugin_configs()

    @staticmethod
    def _plugin_name_from_path(import_path: str) -> str:
        module_path, _, symbol_name = str(import_path).partition(":")
        if symbol_name:
            return symbol_name
        return module_path.rsplit(".", 1)[-1]

    def list_binding_rules(self) -> list[dict[str, Any]]:
        return [_binding_rule_to_config(item) for item in self.profile_registry.list_rules()]

    def get_binding_rule(self, rule_id: str) -> dict[str, Any] | None:
        rule = self.profile_registry.get_rule(rule_id)
        if rule is None:
            return None
        return _binding_rule_to_config(rule)

    async def upsert_binding_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        rule_id = str(payload.get("rule_id", "") or "").strip()
        if not rule_id:
            raise ValueError("rule_id is required")
        normalized = dict(payload)
        normalized["rule_id"] = rule_id
        if self.storage_mode() == "filesystem":
            self._write_yaml(self._bindings_dir() / f"{rule_id}.yaml", normalized)
        else:
            data = self.config.to_dict()
            runtime_conf = dict(data.get("runtime", {}) or {})
            rules_conf = list(runtime_conf.get("binding_rules", []) or [])
            replaced = False
            for index, item in enumerate(rules_conf):
                if str(dict(item or {}).get("rule_id", "") or "") == rule_id:
                    rules_conf[index] = normalized
                    replaced = True
                    break
            if not replaced:
                rules_conf.append(normalized)
            runtime_conf["binding_rules"] = rules_conf
            data["runtime"] = runtime_conf
            self.config.replace(data)
            self.config.save()
        await self.reload_runtime_configuration()
        result = self.get_binding_rule(rule_id)
        if result is None:
            raise RuntimeError("binding rule reload failed")
        return result

    async def delete_binding_rule(self, rule_id: str) -> bool:
        return await self._delete_rule_entry(
            entry_id=rule_id,
            filesystem_dir=self._bindings_dir(),
            inline_key="binding_rules",
            id_key="rule_id",
        )

    def list_inbound_rules(self) -> list[dict[str, Any]]:
        return [_inbound_rule_to_config(item) for item in self.inbound_registry.list_all()]

    def get_inbound_rule(self, rule_id: str) -> dict[str, Any] | None:
        rule = self.inbound_registry.get(rule_id)
        if rule is None:
            return None
        return _inbound_rule_to_config(rule)

    async def upsert_inbound_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        rule_id = str(payload.get("rule_id", "") or "").strip()
        if not rule_id:
            raise ValueError("rule_id is required")
        normalized = dict(payload)
        normalized["rule_id"] = rule_id
        if self.storage_mode() == "filesystem":
            self._write_yaml(self._inbound_rules_dir() / f"{rule_id}.yaml", normalized)
        else:
            data = self.config.to_dict()
            runtime_conf = dict(data.get("runtime", {}) or {})
            rules_conf = list(runtime_conf.get("inbound_rules", []) or [])
            replaced = False
            for index, item in enumerate(rules_conf):
                if str(dict(item or {}).get("rule_id", "") or "") == rule_id:
                    rules_conf[index] = normalized
                    replaced = True
                    break
            if not replaced:
                rules_conf.append(normalized)
            runtime_conf["inbound_rules"] = rules_conf
            data["runtime"] = runtime_conf
            self.config.replace(data)
            self.config.save()
        await self.reload_runtime_configuration()
        result = self.get_inbound_rule(rule_id)
        if result is None:
            raise RuntimeError("inbound rule reload failed")
        return result

    async def delete_inbound_rule(self, rule_id: str) -> bool:
        return await self._delete_rule_entry(
            entry_id=rule_id,
            filesystem_dir=self._inbound_rules_dir(),
            inline_key="inbound_rules",
            id_key="rule_id",
        )

    def list_event_policies(self) -> list[dict[str, Any]]:
        return [_event_policy_to_config(item) for item in self.event_policy_registry.list_all()]

    def get_event_policy(self, policy_id: str) -> dict[str, Any] | None:
        policy = self.event_policy_registry.get(policy_id)
        if policy is None:
            return None
        return _event_policy_to_config(policy)

    async def upsert_event_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        policy_id = str(payload.get("policy_id", "") or "").strip()
        if not policy_id:
            raise ValueError("policy_id is required")
        normalized = dict(payload)
        normalized["policy_id"] = policy_id
        if self.storage_mode() == "filesystem":
            self._write_yaml(self._event_policies_dir() / f"{policy_id}.yaml", normalized)
        else:
            data = self.config.to_dict()
            runtime_conf = dict(data.get("runtime", {}) or {})
            policies_conf = list(runtime_conf.get("event_policies", []) or [])
            replaced = False
            for index, item in enumerate(policies_conf):
                if str(dict(item or {}).get("policy_id", "") or "") == policy_id:
                    policies_conf[index] = normalized
                    replaced = True
                    break
            if not replaced:
                policies_conf.append(normalized)
            runtime_conf["event_policies"] = policies_conf
            data["runtime"] = runtime_conf
            self.config.replace(data)
            self.config.save()
        await self.reload_runtime_configuration()
        result = self.get_event_policy(policy_id)
        if result is None:
            raise RuntimeError("event policy reload failed")
        return result

    async def delete_event_policy(self, policy_id: str) -> bool:
        return await self._delete_rule_entry(
            entry_id=policy_id,
            filesystem_dir=self._event_policies_dir(),
            inline_key="event_policies",
            id_key="policy_id",
        )

    async def _delete_rule_entry(
        self,
        *,
        entry_id: str,
        filesystem_dir: Path,
        inline_key: str,
        id_key: str,
    ) -> bool:
        existed = False
        if self.storage_mode() == "filesystem":
            path = filesystem_dir / f"{entry_id}.yaml"
            if path.exists():
                path.unlink()
                existed = True
        else:
            data = self.config.to_dict()
            runtime_conf = dict(data.get("runtime", {}) or {})
            items = list(runtime_conf.get(inline_key, []) or [])
            filtered = [item for item in items if str(dict(item or {}).get(id_key, "") or "") != entry_id]
            existed = len(filtered) != len(items)
            if existed:
                runtime_conf[inline_key] = filtered
                data["runtime"] = runtime_conf
                self.config.replace(data)
                self.config.save()
        if existed:
            await self.reload_runtime_configuration()
        return existed

    def _filesystem_conf(self) -> dict[str, object]:
        runtime_conf = self.config.get("runtime", {})
        return dict(runtime_conf.get("filesystem", {}) or {})

    def _profiles_dir(self) -> Path:
        return _resolve_filesystem_path(self.config, self._filesystem_conf(), key="profiles_dir", default="profiles")

    def _prompts_dir(self) -> Path:
        return _resolve_filesystem_path(self.config, self._filesystem_conf(), key="prompts_dir", default="prompts")

    def _bindings_dir(self) -> Path:
        return _resolve_filesystem_path(self.config, self._filesystem_conf(), key="bindings_dir", default="bindings")

    def _inbound_rules_dir(self) -> Path:
        return _resolve_filesystem_path(self.config, self._filesystem_conf(), key="inbound_rules_dir", default="inbound_rules")

    def _event_policies_dir(self) -> Path:
        return _resolve_filesystem_path(self.config, self._filesystem_conf(), key="event_policies_dir", default="event_policies")

    def _path_for_prompt_ref(self, prompt_ref: str) -> Path:
        relative = prompt_ref.removeprefix("prompt/")
        raw_path = Path(relative)
        if raw_path.suffix:
            return self._prompts_dir() / raw_path
        return self._prompts_dir() / raw_path.with_suffix(".md")

    def _resolve_prompt_path(self, prompt_ref: str) -> Path | None:
        loader = FileSystemPromptLoader(self._prompts_dir())
        return loader._resolve_prompt_path(prompt_ref)

    def _prompt_ref_from_path(self, path: Path) -> str:
        relative = path.relative_to(self._prompts_dir())
        if relative.name.startswith("index."):
            normalized = relative.parent
        else:
            normalized = relative.with_suffix("")
        return f"prompt/{normalized.as_posix()}".rstrip("/")

    @staticmethod
    def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            delete=False,
            suffix=path.suffix or ".yaml",
        ) as handle:
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
            tmp_path = Path(handle.name)
        tmp_path.replace(path)
