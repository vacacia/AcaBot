"""runtime.bootstrap.config 定义 bootstrap 期使用的配置解析辅助函数."""

from __future__ import annotations

from pathlib import Path

from acabot.config import Config

from ..contracts import BindingRule, EventPolicy, InboundRule


def resolve_filesystem_path(
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


def resolve_runtime_path(config: Config, raw_path: object) -> Path:
    return config.resolve_path(str(raw_path))


def get_persistence_sqlite_path(config: Config) -> str | None:
    runtime_conf = config.get("runtime", {})
    persistence_conf = runtime_conf.get("persistence", {})
    sqlite_path = persistence_conf.get("sqlite_path")
    if sqlite_path in (None, ""):
        return None
    return str(resolve_runtime_path(config, sqlite_path))


def optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def optional_bool(value: object) -> bool | None:
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


def parse_run_mode(value: object) -> str:
    normalized = str(value)
    if normalized not in {"respond", "record_only", "silent_drop"}:
        raise ValueError(f"Unsupported run_mode: {normalized}")
    return normalized


def parse_binding_rule_config(
    rule_conf: dict[str, object],
    *,
    default_rule_id: str,
) -> BindingRule:
    match_conf = dict(rule_conf.get("match", {}))
    if "thread_id" in match_conf:
        raise ValueError("binding_rules in config must not declare thread_id")
    return BindingRule(
        rule_id=str(rule_conf.get("rule_id", default_rule_id)),
        agent_id=str(rule_conf["agent_id"]),
        priority=int(rule_conf.get("priority", 100)),
        thread_id=None,
        event_type=optional_str(match_conf.get("event_type")),
        message_subtype=optional_str(match_conf.get("message_subtype")),
        notice_type=optional_str(match_conf.get("notice_type")),
        notice_subtype=optional_str(match_conf.get("notice_subtype")),
        actor_id=optional_str(match_conf.get("actor_id")),
        channel_scope=optional_str(match_conf.get("channel_scope")),
        targets_self=optional_bool(match_conf.get("targets_self")),
        mentions_self=optional_bool(match_conf.get("mentions_self")),
        mentioned_everyone=optional_bool(match_conf.get("mentioned_everyone")),
        reply_targets_self=optional_bool(match_conf.get("reply_targets_self")),
        sender_roles=[str(role) for role in match_conf.get("sender_roles", [])],
        metadata=dict(rule_conf.get("metadata", {})),
    )


def parse_inbound_rule_config(
    rule_conf: dict[str, object],
    *,
    default_rule_id: str,
) -> InboundRule:
    match_conf = dict(rule_conf.get("match", {}))
    return InboundRule(
        rule_id=str(rule_conf.get("rule_id", default_rule_id)),
        run_mode=parse_run_mode(rule_conf.get("run_mode", "respond")),
        priority=int(rule_conf.get("priority", 100)),
        platform=optional_str(match_conf.get("platform")),
        event_type=optional_str(match_conf.get("event_type")),
        message_subtype=optional_str(match_conf.get("message_subtype")),
        notice_type=optional_str(match_conf.get("notice_type")),
        notice_subtype=optional_str(match_conf.get("notice_subtype")),
        actor_id=optional_str(match_conf.get("actor_id")),
        channel_scope=optional_str(match_conf.get("channel_scope")),
        targets_self=optional_bool(match_conf.get("targets_self")),
        mentions_self=optional_bool(match_conf.get("mentions_self")),
        mentioned_everyone=optional_bool(match_conf.get("mentioned_everyone")),
        reply_targets_self=optional_bool(match_conf.get("reply_targets_self")),
        sender_roles=[str(role) for role in match_conf.get("sender_roles", [])],
        metadata=dict(rule_conf.get("metadata", {})),
    )


def parse_event_policy_config(
    policy_conf: dict[str, object],
    *,
    default_policy_id: str,
) -> EventPolicy:
    match_conf = dict(policy_conf.get("match", {}))
    return EventPolicy(
        policy_id=str(policy_conf.get("policy_id", default_policy_id)),
        priority=int(policy_conf.get("priority", 100)),
        platform=optional_str(match_conf.get("platform")),
        event_type=optional_str(match_conf.get("event_type")),
        message_subtype=optional_str(match_conf.get("message_subtype")),
        notice_type=optional_str(match_conf.get("notice_type")),
        notice_subtype=optional_str(match_conf.get("notice_subtype")),
        actor_id=optional_str(match_conf.get("actor_id")),
        channel_scope=optional_str(match_conf.get("channel_scope")),
        targets_self=optional_bool(match_conf.get("targets_self")),
        mentions_self=optional_bool(match_conf.get("mentions_self")),
        mentioned_everyone=optional_bool(match_conf.get("mentioned_everyone")),
        reply_targets_self=optional_bool(match_conf.get("reply_targets_self")),
        sender_roles=[str(role) for role in match_conf.get("sender_roles", [])],
        persist_event=bool(policy_conf.get("persist_event", True)),
        extract_to_memory=bool(policy_conf.get("extract_to_memory", False)),
        memory_scopes=[str(scope) for scope in policy_conf.get("memory_scopes", [])],
        tags=[str(tag) for tag in policy_conf.get("tags", [])],
        metadata=dict(policy_conf.get("metadata", {})),
    )


__all__ = [
    "get_persistence_sqlite_path",
    "optional_bool",
    "optional_str",
    "parse_binding_rule_config",
    "parse_event_policy_config",
    "parse_inbound_rule_config",
    "parse_run_mode",
    "resolve_filesystem_path",
    "resolve_runtime_path",
]
