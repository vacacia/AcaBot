"""runtime.control.session_shell 提供 Session 产品壳映射服务.

组件关系:

    RuntimeControlPlane
           |
           v
    SessionShellControlOps
           |
           +--> RuntimeConfigControlPlane
           +--> RuntimeModelControlOps
           +--> AgentProfileRegistry

这一层负责:
- 把底层 profile / binding / inbound / event policy 投影成 Session 产品壳
- 把前端的 `AI / 消息响应 / 其他` 设置写回真实真源
- 对前端隐藏 `rule_id / policy_id` 这些实现细节
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any

from ..model.model_registry import ModelBinding
from .config_control_plane import RuntimeConfigControlPlane
from .model_ops import RuntimeModelControlOps
from .profile_loader import AgentProfileRegistry
from .session_templates import (
    SESSION_EVENT_TYPE_OPTIONS,
    default_session_channel_template_id,
    get_session_channel_template,
    public_event_types_for_template,
)


def _string_list(values: object) -> list[str]:
    """把任意值整理成去重后的字符串列表.

    Args:
        values: 原始值.

    Returns:
        过滤空值后的字符串列表, 保留原始顺序.
    """

    items: list[str] = []
    seen: set[str] = set()
    for raw in list(values or []) if isinstance(values, (list, tuple, set)) else []:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        items.append(item)
        seen.add(item)
    return items


# region session shell
@dataclass(slots=True)
class SessionShellControlOps:
    """Session 产品壳控制服务.

    Attributes:
        config_control_plane (RuntimeConfigControlPlane | None): runtime 配置控制面.
        model_ops (RuntimeModelControlOps): 模型绑定控制入口.
        profile_registry (AgentProfileRegistry | None): profile registry, 用于识别默认 bot.
    """

    config_control_plane: RuntimeConfigControlPlane | None
    model_ops: RuntimeModelControlOps
    profile_registry: AgentProfileRegistry | None

    async def list_sessions(self) -> list[dict[str, Any]]:
        """列出当前全部 Session 产品壳对象.

        Returns:
            不带底层 rule 概念的 Session 列表.
        """

        index = await self._build_session_index()
        items = [self._to_public_record(item) for item in index.values()]
        return sorted(items, key=lambda item: str(item.get("display_name", "") or item.get("channel_scope", "")))

    async def get_session(self, *, channel_scope: str) -> dict[str, Any] | None:
        """读取一个 Session 产品壳对象.

        Args:
            channel_scope: Session 对应的 channel scope.

        Returns:
            Session 产品壳对象; 不存在时返回 `None`.
        """

        normalized_scope = str(channel_scope or "").strip()
        if not normalized_scope:
            raise ValueError("channel_scope is required")
        index = await self._build_session_index()
        item = index.get(normalized_scope)
        if item is None:
            return None
        return self._to_public_record(item)

    async def upsert_session(self, *, channel_scope: str, payload: dict[str, Any]) -> dict[str, Any]:
        """按产品壳字段保存一个 Session.

        Args:
            channel_scope: Session 对应的 channel scope.
            payload: 前端提交的 Session 壳对象.

        Returns:
            保存后的 Session 产品壳对象.
        """

        if self.config_control_plane is None:
            raise RuntimeError("runtime config control plane unavailable")
        normalized_scope = str(channel_scope or payload.get("channel_scope", "") or "").strip()
        if not normalized_scope:
            raise ValueError("channel_scope is required")

        index = await self._build_session_index()
        context = await self._load_context()
        existing = index.get(normalized_scope)
        fallback = (
            self._to_public_record(existing)
            if existing is not None
            else self._default_public_record(
                channel_scope=normalized_scope,
                default_ai=context["default_ai"],
            )
        )
        normalized = self._normalize_payload(
            channel_scope=normalized_scope,
            payload=payload,
            fallback=fallback,
        )
        agent_id = self._resolve_session_agent_id(
            channel_scope=normalized_scope,
            existing=existing,
            profiles_by_id=context["profiles_by_id"],
        )
        await self._save_ai_config(
            channel_scope=normalized_scope,
            display_name=str(normalized["display_name"]),
            agent_id=agent_id,
            ai_payload=dict(normalized["ai"]),
            context=context,
        )
        await self._save_binding_config(
            channel_scope=normalized_scope,
            display_name=str(normalized["display_name"]),
            channel_template_id=str(normalized["channel_template_id"]),
            other_payload=dict(normalized["other"]),
            agent_id=agent_id,
            existing=existing,
        )
        await self._save_message_response(
            channel_scope=normalized_scope,
            display_name=str(normalized["display_name"]),
            message_response=dict(normalized["message_response"]),
            existing=existing,
        )
        saved = await self.get_session(channel_scope=normalized_scope)
        if saved is None:
            raise RuntimeError("session reload failed")
        return saved

    async def _build_session_index(self) -> dict[str, dict[str, Any]]:
        """从底层真源构造 Session 内部索引.

        Returns:
            以 `channel_scope` 为键的内部索引.
        """

        context = await self._load_context()
        index: dict[str, dict[str, Any]] = {}
        specific_message_rule_scopes = self._specific_message_rule_scopes(
            inbound_rules=context["inbound_rules"],
            event_policies=context["event_policies"],
        )

        def ensure(scope: str) -> dict[str, Any]:
            """确保某个 Session 索引项存在.

            Args:
                scope: channel scope.

            Returns:
                内部索引项.
            """

            normalized_scope = str(scope or "").strip()
            if normalized_scope not in index:
                index[normalized_scope] = self._default_internal_record(
                    channel_scope=normalized_scope,
                    default_ai=context["default_ai"],
                )
            return index[normalized_scope]

        for rule in context["binding_rules"]:
            match = dict(rule.get("match", {}) or {})
            scope = str(match.get("channel_scope", "") or "").strip()
            if not scope:
                continue
            item = ensure(scope)
            metadata = dict(rule.get("metadata", {}) or {})
            agent_id = str(rule.get("agent_id", "") or "").strip()
            item["_binding_rule_id"] = str(rule.get("rule_id", "") or "")
            item["_agent_id"] = agent_id
            item["channel_template_id"] = str(
                metadata.get("channel_template_id", "") or item.get("channel_template_id", "")
            ).strip() or default_session_channel_template_id(scope)
            self._ensure_template_rules(item)
            if metadata.get("display_name"):
                item["display_name"] = str(metadata.get("display_name", "") or scope)
            if agent_id:
                profile = context["profiles_by_id"].get(agent_id)
                if profile is not None:
                    item["ai"] = self._build_ai_payload(
                        profile=profile,
                        model_preset_id=context["model_binding_by_agent_id"].get(agent_id, ""),
                        fallback=item["ai"],
                    )

        for rule in context["inbound_rules"]:
            match = dict(rule.get("match", {}) or {})
            scope = str(match.get("channel_scope", "") or "").strip()
            event_type = str(match.get("event_type", "") or "").strip()
            if not scope or not event_type:
                continue
            item = ensure(scope)
            self._ensure_template_rules(item)
            metadata = dict(rule.get("metadata", {}) or {})
            persisted_run_mode = str(rule.get("run_mode", "respond") or "respond")
            preferred_run_mode = str(metadata.get("webui_run_mode", "") or "").strip()
            public_event_types = self._public_event_types_for_match(
                event_type=event_type,
                channel_scope=scope,
                channel_template_id=str(item.get("channel_template_id", "") or ""),
                match=match,
                metadata=metadata,
                specific_message_rules_exist=scope in specific_message_rule_scopes,
            )
            for public_event_type in public_event_types:
                message_rule = item["_message_rules"].get(public_event_type)
                if message_rule is None:
                    continue
                message_rule["enabled"] = persisted_run_mode != "silent_drop"
                if not message_rule["enabled"] and preferred_run_mode in {"respond", "record_only"}:
                    message_rule["run_mode"] = preferred_run_mode
                else:
                    message_rule["run_mode"] = persisted_run_mode

        for policy in context["event_policies"]:
            match = dict(policy.get("match", {}) or {})
            scope = str(match.get("channel_scope", "") or "").strip()
            event_type = str(match.get("event_type", "") or "").strip()
            if not scope or not event_type:
                continue
            item = ensure(scope)
            self._ensure_template_rules(item)
            metadata = dict(policy.get("metadata", {}) or {})
            public_event_types = self._public_event_types_for_match(
                event_type=event_type,
                channel_scope=scope,
                channel_template_id=str(item.get("channel_template_id", "") or ""),
                match=match,
                metadata=metadata,
                specific_message_rules_exist=scope in specific_message_rule_scopes,
            )
            for public_event_type in public_event_types:
                message_rule = item["_message_rules"].get(public_event_type)
                if message_rule is None:
                    continue
                message_rule["persist_event"] = bool(policy.get("persist_event", True))
                message_rule["memory_scopes"] = _string_list(policy.get("memory_scopes", []))

        return index

    async def _load_context(self) -> dict[str, Any]:
        """读取 Session 映射所需的底层上下文.

        Returns:
            一个包含 profile、rules 和模型绑定的上下文字典.
        """

        profiles: list[dict[str, Any]] = []
        binding_rules: list[dict[str, Any]] = []
        inbound_rules: list[dict[str, Any]] = []
        event_policies: list[dict[str, Any]] = []
        if self.config_control_plane is not None:
            profiles = self.config_control_plane.list_profiles()
            binding_rules = self.config_control_plane.list_binding_rules()
            inbound_rules = self.config_control_plane.list_inbound_rules()
            event_policies = self.config_control_plane.list_event_policies()

        model_bindings = await self.model_ops.list_model_bindings()
        model_presets = await self.model_ops.list_model_presets()
        profiles_by_id = {
            str(item.get("agent_id", "") or ""): item
            for item in profiles
            if str(item.get("agent_id", "") or "").strip()
        }
        model_binding_records: dict[str, ModelBinding] = {}
        model_binding_by_agent_id: dict[str, str] = {}
        for item in model_bindings:
            if item.target_type != "agent":
                continue
            model_binding_records[item.target_id] = item
            preset_id = str(item.preset_id or "")
            if not preset_id and item.preset_ids:
                preset_id = str(item.preset_ids[0] or "")
            model_binding_by_agent_id[item.target_id] = preset_id

        preset_model_names = {
            item.preset_id: item.model
            for item in model_presets
            if str(item.preset_id or "").strip()
        }
        default_agent_id = self._default_agent_id(profiles)
        default_profile = profiles_by_id.get(default_agent_id) if default_agent_id else None
        default_ai = self._build_ai_payload(
            profile=default_profile,
            model_preset_id=model_binding_by_agent_id.get(default_agent_id, ""),
            fallback=None,
        )
        return {
            "profiles": profiles,
            "profiles_by_id": profiles_by_id,
            "binding_rules": binding_rules,
            "inbound_rules": inbound_rules,
            "event_policies": event_policies,
            "model_binding_records": model_binding_records,
            "model_binding_by_agent_id": model_binding_by_agent_id,
            "preset_model_names": preset_model_names,
            "default_agent_id": default_agent_id,
            "default_ai": default_ai,
        }

    def _default_agent_id(self, profiles: list[dict[str, Any]]) -> str:
        """返回默认 bot 的 agent id.

        Args:
            profiles: 当前全部 profile.

        Returns:
            默认 bot 的 agent id.
        """

        if self.profile_registry is not None:
            default_agent_id = str(getattr(self.profile_registry, "default_agent_id", "") or "").strip()
            if default_agent_id:
                return default_agent_id
        if profiles:
            return str(profiles[0].get("agent_id", "") or "").strip()
        return ""

    def _default_internal_record(
        self,
        *,
        channel_scope: str,
        default_ai: dict[str, Any],
    ) -> dict[str, Any]:
        """构造内部默认 Session 记录.

        Args:
            channel_scope: Session 对应的 channel scope.
            default_ai: 默认 bot 的 AI 设置.

        Returns:
            内部 Session 记录.
        """

        channel_template_id = default_session_channel_template_id(channel_scope)
        template = get_session_channel_template(channel_template_id, channel_scope=channel_scope)
        return {
            "display_name": channel_scope,
            "thread_id": channel_scope,
            "channel_scope": channel_scope,
            "channel_template_id": channel_template_id,
            "ai": deepcopy(default_ai),
            "other": {},
            "_binding_rule_id": "",
            "_agent_id": "",
            "_message_rules": {
                event_type: self._default_message_rule(
                    event_type=event_type,
                    channel_template_id=channel_template_id,
                )
                for event_type in template.event_types
            },
        }

    def _default_public_record(
        self,
        *,
        channel_scope: str,
        default_ai: dict[str, Any],
    ) -> dict[str, Any]:
        """构造对前端可见的默认 Session 记录.

        Args:
            channel_scope: Session 对应的 channel scope.
            default_ai: 默认 bot 的 AI 设置.

        Returns:
            面向前端的 Session 记录.
        """

        return self._to_public_record(
            self._default_internal_record(
                channel_scope=channel_scope,
                default_ai=default_ai,
            )
        )

    def _build_ai_payload(
        self,
        *,
        profile: dict[str, Any] | None,
        model_preset_id: str,
        fallback: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """从 profile 和模型绑定构造 AI 区块.

        Args:
            profile: 目标 profile.
            model_preset_id: 主模型 preset id.
            fallback: 缺省回退值.

        Returns:
            `Session / AI` 区块.
        """

        base = deepcopy(fallback or {})
        source = dict(profile or {})
        return {
            "prompt_ref": str(source.get("prompt_ref", "") or base.get("prompt_ref", "") or ""),
            "model_preset_id": str(model_preset_id or base.get("model_preset_id", "") or ""),
            "summary_model_preset_id": str(
                source.get("summary_model_preset_id", "") or base.get("summary_model_preset_id", "") or ""
            ),
            "context_management": {
                "strategy": self._normalize_context_management_strategy(
                    dict(source.get("context_management", {}) or {}).get(
                        "strategy",
                        dict(base.get("context_management", {}) or {}).get("strategy", ""),
                    )
                ),
            },
            "enabled_tools": _string_list(source.get("enabled_tools", base.get("enabled_tools", []))),
            "skills": _string_list(source.get("skills", base.get("skills", []))),
        }

    def _normalize_context_management_strategy(self, value: object) -> str:
        """规范化 Session 的上下文管理策略值."""

        strategy = str(value or "").strip()
        if strategy not in {"", "truncate", "summarize"}:
            raise ValueError(f"unsupported context_management.strategy: {strategy}")
        return strategy

    def _allowed_event_types(
        self,
        *,
        channel_scope: str,
        channel_template_id: str,
    ) -> list[str]:
        """返回某个 Session 模板允许前端展示的事件类型列表."""

        template = get_session_channel_template(channel_template_id, channel_scope=channel_scope)
        return [str(event_type) for event_type in public_event_types_for_template(template)]

    def _supports_split_message_rules(
        self,
        *,
        channel_scope: str,
        channel_template_id: str,
    ) -> bool:
        """判断当前模板是否需要把消息拆成多条公开规则."""

        template = get_session_channel_template(channel_template_id, channel_scope=channel_scope)
        return len(public_event_types_for_template(template)) > len(template.event_types)

    def _ensure_template_rules(self, item: dict[str, Any]) -> None:
        """按当前渠道模板收口内部规则集合."""

        channel_scope = str(item.get("channel_scope", "") or "")
        channel_template_id = str(
            item.get("channel_template_id", "") or default_session_channel_template_id(channel_scope)
        )
        item["channel_template_id"] = channel_template_id
        raw_rules = dict(item.get("_message_rules", {}) or {})
        item["_message_rules"] = {
            event_type: {
                **self._default_message_rule(
                    event_type=event_type,
                    channel_template_id=channel_template_id,
                ),
                **dict(raw_rules.get(event_type, {}) or {}),
            }
            for event_type in self._allowed_event_types(
                channel_scope=channel_scope,
                channel_template_id=channel_template_id,
            )
        }

    def _default_message_rule(
        self,
        *,
        event_type: str,
        channel_template_id: str,
    ) -> dict[str, Any]:
        """返回单个事件类型的默认消息响应规则.

        Args:
            event_type: 事件类型.
            channel_template_id: 当前渠道模板 ID.

        Returns:
            默认规则对象.
        """

        return {
            "event_type": event_type,
            "enabled": True,
            "run_mode": "respond",
            "persist_event": True,
            "memory_scopes": [],
        }

    def _to_public_record(self, item: dict[str, Any]) -> dict[str, Any]:
        """把内部索引项转换成前端可见结构.

        Args:
            item: 内部索引项.

        Returns:
            面向前端的 Session 产品壳对象.
        """

        self._ensure_template_rules(item)
        message_rules = []
        raw_rules = dict(item.get("_message_rules", {}) or {})
        channel_scope = str(item.get("channel_scope", "") or "")
        channel_template_id = str(item.get("channel_template_id", "") or "")
        for event_type in self._allowed_event_types(
            channel_scope=channel_scope,
            channel_template_id=channel_template_id,
        ):
            rule = dict(
                raw_rules.get(
                    event_type,
                    self._default_message_rule(
                        event_type=event_type,
                        channel_template_id=channel_template_id,
                    ),
                )
            )
            rule["event_type"] = event_type
            message_rules.append(rule)
        return {
            "display_name": str(item.get("display_name", "") or item.get("channel_scope", "") or ""),
            "thread_id": str(item.get("thread_id", "") or item.get("channel_scope", "") or ""),
            "channel_scope": str(item.get("channel_scope", "") or ""),
            "channel_template_id": channel_template_id,
            "ai": deepcopy(dict(item.get("ai", {}) or {})),
            "message_response": {"rules": message_rules},
            "other": {},
        }

    def _normalize_payload(
        self,
        *,
        channel_scope: str,
        payload: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        """规范化前端提交的 Session 壳 payload.

        Args:
            channel_scope: Session 对应的 channel scope.
            payload: 原始提交内容.
            fallback: 回退值.

        Returns:
            规范化后的 Session 壳 payload.
        """

        display_name = str(payload.get("display_name", "") or fallback.get("display_name", "") or channel_scope).strip()
        channel_template_id = str(
            payload.get("channel_template_id", "")
            or fallback.get("channel_template_id", "")
            or default_session_channel_template_id(channel_scope)
        ).strip()
        ai_payload = {
            **dict(fallback.get("ai", {}) or {}),
            **dict(payload.get("ai", {}) or {}),
        }
        normalized_ai = {
            "prompt_ref": str(ai_payload.get("prompt_ref", "") or "").strip(),
            "model_preset_id": str(ai_payload.get("model_preset_id", "") or "").strip(),
            "summary_model_preset_id": str(ai_payload.get("summary_model_preset_id", "") or "").strip(),
            "context_management": {
                "strategy": self._normalize_context_management_strategy(
                    dict(ai_payload.get("context_management", {}) or {}).get("strategy", "")
                ),
            },
            "enabled_tools": _string_list(ai_payload.get("enabled_tools", [])),
            "skills": _string_list(ai_payload.get("skills", [])),
        }

        allowed_event_types = self._allowed_event_types(
            channel_scope=channel_scope,
            channel_template_id=channel_template_id,
        )
        rule_map = {
            str(item.get("event_type", "") or ""): {
                key: value
                for key, value in dict(item).items()
                if key != "event_type"
            }
            for item in list(dict(fallback.get("message_response", {}) or {}).get("rules", []) or [])
            if str(dict(item).get("event_type", "") or "").strip() in allowed_event_types
        }
        for raw in list(dict(payload.get("message_response", {}) or {}).get("rules", []) or []):
            raw_map = dict(raw or {})
            raw_event_type = str(raw_map.get("event_type", "") or "").strip()
            if not raw_event_type:
                continue
            normalized_event_types = self._normalize_public_event_types_from_payload(
                raw_event_type=raw_event_type,
                raw_rule=raw_map,
                channel_scope=channel_scope,
                channel_template_id=channel_template_id,
            )
            for event_type in normalized_event_types:
                if event_type not in SESSION_EVENT_TYPE_OPTIONS:
                    raise ValueError(f"unsupported event_type: {event_type}")
                if event_type not in allowed_event_types:
                    raise ValueError(f"event_type not allowed by template: {event_type}")
                base = dict(
                    rule_map.get(
                        event_type,
                        self._default_message_rule(
                            event_type=event_type,
                            channel_template_id=channel_template_id,
                        ),
                    )
                )
                run_mode = str(raw_map.get("run_mode", base.get("run_mode", "respond")) or "respond")
                if run_mode not in {"respond", "record_only", "silent_drop"}:
                    raise ValueError(f"unsupported run_mode: {run_mode}")
                rule_map[event_type] = {
                    "enabled": bool(raw_map.get("enabled", base.get("enabled", True))),
                    "run_mode": run_mode,
                    "persist_event": bool(raw_map.get("persist_event", base.get("persist_event", True))),
                    "memory_scopes": _string_list(raw_map.get("memory_scopes", base.get("memory_scopes", []))),
                }
        normalized_rules = []
        for event_type in allowed_event_types:
            base = dict(
                rule_map.get(
                    event_type,
                    self._default_message_rule(
                        event_type=event_type,
                        channel_template_id=channel_template_id,
                    ),
                )
            )
            normalized_rules.append(
                {
                    "event_type": event_type,
                    "enabled": bool(base.get("enabled", True)),
                    "run_mode": str(base.get("run_mode", "respond") or "respond"),
                    "persist_event": bool(base.get("persist_event", True)),
                    "memory_scopes": _string_list(base.get("memory_scopes", [])),
                }
            )

        return {
            "display_name": display_name or channel_scope,
            "channel_scope": channel_scope,
            "channel_template_id": channel_template_id,
            "ai": normalized_ai,
            "message_response": {"rules": normalized_rules},
            "other": {},
        }

    def _normalize_public_event_types_from_payload(
        self,
        *,
        raw_event_type: str,
        raw_rule: dict[str, Any],
        channel_scope: str,
        channel_template_id: str,
    ) -> list[str]:
        """把前端或旧版 payload 的事件类型转换成公开事件类型列表."""

        if raw_event_type != "message" or not self._supports_split_message_rules(
            channel_scope=channel_scope,
            channel_template_id=channel_template_id,
        ):
            return [raw_event_type]
        message_filter = str(raw_rule.get("message_filter", "") or "").strip()
        if message_filter == "mention_only":
            return ["message_mention"]
        if message_filter == "reply_only":
            return ["message_reply"]
        if message_filter == "mention_or_reply":
            return ["message", "message_mention", "message_reply"]
        return ["message"]

    def _specific_message_rule_scopes(
        self,
        *,
        inbound_rules: list[dict[str, Any]],
        event_policies: list[dict[str, Any]],
    ) -> set[str]:
        """返回已经存在具体艾特/引用规则的 Session scope 集合."""

        scopes: set[str] = set()
        for entry in [*inbound_rules, *event_policies]:
            match = dict(entry.get("match", {}) or {})
            if str(match.get("event_type", "") or "").strip() != "message":
                continue
            scope = str(match.get("channel_scope", "") or "").strip()
            if not scope:
                continue
            metadata = dict(entry.get("metadata", {}) or {})
            public_event_type = str(metadata.get("public_event_type", "") or "").strip()
            if public_event_type in {"message_mention", "message_reply"}:
                scopes.add(scope)
                continue
            if bool(match.get("mentions_self")) or bool(match.get("reply_targets_self")):
                scopes.add(scope)
        return scopes

    def _public_event_types_for_match(
        self,
        *,
        event_type: str,
        channel_scope: str,
        channel_template_id: str,
        match: dict[str, Any],
        metadata: dict[str, Any],
        specific_message_rules_exist: bool,
    ) -> list[str]:
        """根据底层 match 恢复公开事件类型."""

        stored = str(metadata.get("public_event_type", "") or "").strip()
        if stored in SESSION_EVENT_TYPE_OPTIONS:
            return [stored]
        if event_type != "message" or not self._supports_split_message_rules(
            channel_scope=channel_scope,
            channel_template_id=channel_template_id,
        ):
            return [event_type]
        if bool(match.get("mentions_self")):
            return ["message_mention"]
        if bool(match.get("reply_targets_self")):
            return ["message_reply"]
        if specific_message_rules_exist:
            return ["message"]
        return ["message", "message_mention", "message_reply"]

    def _message_rule_variant(
        self,
        *,
        channel_scope: str,
        public_event_type: str,
        run_mode: str,
        persist_event: bool,
        memory_scopes: list[str],
    ) -> dict[str, Any]:
        """把一条公开消息规则转换成一条真实运行时规则."""

        if public_event_type == "message_mention":
            return {
                "variant": "mention",
                "storage_event_type": "message",
                "priority": 111,
                "run_mode": run_mode,
                "match": {
                    "channel_scope": channel_scope,
                    "event_type": "message",
                    "mentions_self": True,
                },
                "persist_event": persist_event,
                "memory_scopes": list(memory_scopes),
            }
        if public_event_type == "message_reply":
            return {
                "variant": "reply",
                "storage_event_type": "message",
                "priority": 110,
                "run_mode": run_mode,
                "match": {
                    "channel_scope": channel_scope,
                    "event_type": "message",
                    "reply_targets_self": True,
                },
                "persist_event": persist_event,
                "memory_scopes": list(memory_scopes),
            }
        return {
            "variant": "ambient" if public_event_type == "message" else "direct",
            "storage_event_type": "message" if public_event_type == "message" else public_event_type,
            "priority": 100,
            "run_mode": run_mode,
            "match": {
                "channel_scope": channel_scope,
                "event_type": "message" if public_event_type == "message" else public_event_type,
            },
            "persist_event": persist_event,
            "memory_scopes": list(memory_scopes),
        }

    def _session_rule_metadata(
        self,
        *,
        channel_scope: str,
        display_name: str,
        public_event_type: str,
    ) -> dict[str, Any]:
        """构造 Session 壳托管规则的公共元数据."""

        return {
            "display_name": display_name,
            "managed_by": "webui_session",
            "session_key": channel_scope,
            "public_event_type": public_event_type,
        }

    def _rule_entry_id(self, entry: dict[str, Any]) -> str:
        """读取 rule/policy 配置项的稳定 ID."""

        return str(entry.get("rule_id", "") or entry.get("policy_id", "") or "").strip()

    def _is_session_managed_rule_entry(
        self,
        *,
        entry: dict[str, Any],
        channel_scope: str,
    ) -> bool:
        """判断一条 inbound/event policy 是否属于 Session 壳托管范围."""

        match = dict(entry.get("match", {}) or {})
        if str(match.get("channel_scope", "") or "").strip() != channel_scope:
            return False
        metadata = dict(entry.get("metadata", {}) or {})
        managed_by = str(metadata.get("managed_by", "") or "").strip()
        session_key = str(metadata.get("session_key", "") or "").strip()
        if managed_by in {"webui_session", "webui_v2_session"} or session_key == channel_scope:
            return True
        entry_id = self._rule_entry_id(entry)
        return entry_id.startswith("session_") or entry_id.startswith("session-")

    async def _delete_managed_session_message_rules(self, *, channel_scope: str) -> None:
        """删除一个 Session 已托管的 inbound / event policy 规则."""

        if self.config_control_plane is None:
            raise RuntimeError("runtime config control plane unavailable")
        for rule in list(self.config_control_plane.list_inbound_rules()):
            if not self._is_session_managed_rule_entry(entry=rule, channel_scope=channel_scope):
                continue
            rule_id = str(rule.get("rule_id", "") or "").strip()
            if rule_id:
                await self.config_control_plane.delete_inbound_rule(rule_id)
        for policy in list(self.config_control_plane.list_event_policies()):
            if not self._is_session_managed_rule_entry(entry=policy, channel_scope=channel_scope):
                continue
            policy_id = str(policy.get("policy_id", "") or "").strip()
            if policy_id:
                await self.config_control_plane.delete_event_policy(policy_id)

    def _resolve_session_agent_id(
        self,
        *,
        channel_scope: str,
        existing: dict[str, Any] | None,
        profiles_by_id: dict[str, dict[str, Any]],
    ) -> str:
        """决定 Session 保存时应使用哪个 agent.

        Args:
            channel_scope: Session 对应的 channel scope.
            existing: 现有内部索引项.
            profiles_by_id: 当前 profile 索引.

        Returns:
            应该写入 binding 的 agent id.
        """

        if existing is not None:
            agent_id = str(existing.get("_agent_id", "") or "").strip()
            if self._is_session_managed_agent(
                agent_id=agent_id,
                channel_scope=channel_scope,
                profiles_by_id=profiles_by_id,
            ):
                return agent_id
        return self._session_agent_id(channel_scope)

    def _is_session_managed_agent(
        self,
        *,
        agent_id: str,
        channel_scope: str,
        profiles_by_id: dict[str, dict[str, Any]],
    ) -> bool:
        """判断一个 agent 是否是 Session 自己管理的 profile.

        Args:
            agent_id: 待判断的 agent id.
            channel_scope: Session 对应的 channel scope.
            profiles_by_id: 当前 profile 索引.

        Returns:
            是 Session 自己管理的 profile 时返回 `True`.
        """

        if not agent_id:
            return False
        profile = profiles_by_id.get(agent_id)
        if profile is None:
            return False
        metadata = dict(profile.get("metadata", {}) or {})
        managed_by = str(metadata.get("managed_by", "") or "").strip()
        session_key = str(metadata.get("session_key", "") or "").strip()
        return managed_by in {"webui_session", "webui_v2_session"} or session_key == channel_scope

    async def _save_ai_config(
        self,
        *,
        channel_scope: str,
        display_name: str,
        agent_id: str,
        ai_payload: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        """保存 Session 的 AI 设置.

        Args:
            channel_scope: Session 对应的 channel scope.
            display_name: Session 展示名.
            agent_id: 绑定的 agent id.
            ai_payload: `Session / AI` 区块.
            context: 当前底层上下文.
        """

        if self.config_control_plane is None:
            raise RuntimeError("runtime config control plane unavailable")
        existing_profile = context["profiles_by_id"].get(agent_id, {})
        metadata = dict(existing_profile.get("metadata", {}) or {})
        metadata.update(
            {
                "managed_by": "webui_session",
                "session_key": channel_scope,
            }
        )
        default_model = self._resolve_profile_default_model(
            agent_id=agent_id,
            ai_payload=ai_payload,
            context=context,
        )
        updated_profile = deepcopy(existing_profile)
        updated_profile.update(
            {
                "agent_id": agent_id,
                "name": display_name,
                "prompt_ref": str(ai_payload.get("prompt_ref", "") or existing_profile.get("prompt_ref", "") or ""),
                "default_model": default_model,
                "summary_model_preset_id": str(
                    ai_payload.get("summary_model_preset_id", "")
                    or existing_profile.get("summary_model_preset_id", "")
                    or ""
                ),
                "context_management": {
                    "strategy": self._normalize_context_management_strategy(
                        dict(ai_payload.get("context_management", {}) or {}).get(
                            "strategy",
                            dict(existing_profile.get("context_management", {}) or {}).get("strategy", ""),
                        )
                    ),
                },
                "enabled_tools": _string_list(ai_payload.get("enabled_tools", [])),
                "skills": _string_list(ai_payload.get("skills", [])),
                "metadata": metadata,
            }
        )
        await self.config_control_plane.upsert_profile(updated_profile)
        await self._sync_model_binding(
            channel_scope=channel_scope,
            agent_id=agent_id,
            model_preset_id=str(ai_payload.get("model_preset_id", "") or ""),
            context=context,
        )

    def _resolve_profile_default_model(
        self,
        *,
        agent_id: str,
        ai_payload: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        """决定 profile.default_model 应写入什么值.

        Args:
            agent_id: 目标 agent id.
            ai_payload: `Session / AI` 区块.
            context: 当前底层上下文.

        Returns:
            profile.default_model 字段值.
        """

        existing_profile = context["profiles_by_id"].get(agent_id, {})
        preset_id = str(ai_payload.get("model_preset_id", "") or "").strip()
        if preset_id:
            model_name = str(context["preset_model_names"].get(preset_id, "") or "").strip()
            if model_name:
                return model_name
        return str(existing_profile.get("default_model", "") or "")

    async def _sync_model_binding(
        self,
        *,
        channel_scope: str,
        agent_id: str,
        model_preset_id: str,
        context: dict[str, Any],
    ) -> None:
        """同步 Session agent 的模型绑定.

        Args:
            channel_scope: Session 对应的 channel scope.
            agent_id: 目标 agent id.
            model_preset_id: 目标主模型 preset id.
            context: 当前底层上下文.
        """

        existing_binding = context["model_binding_records"].get(agent_id)
        if model_preset_id:
            binding_id = (
                existing_binding.binding_id
                if existing_binding is not None
                else self._session_model_binding_id(channel_scope)
            )
            await self.model_ops.upsert_model_binding(
                ModelBinding(
                    binding_id=binding_id,
                    target_type="agent",
                    target_id=agent_id,
                    preset_id=model_preset_id,
                )
            )
            return
        if existing_binding is not None:
            await self.model_ops.delete_model_binding(existing_binding.binding_id)

    async def _save_binding_config(
        self,
        *,
        channel_scope: str,
        display_name: str,
        channel_template_id: str,
        other_payload: dict[str, Any],
        agent_id: str,
        existing: dict[str, Any] | None,
    ) -> None:
        """保存 Session 的基础绑定和其他补充字段.

        Args:
            channel_scope: Session 对应的 channel scope.
            display_name: Session 展示名.
            channel_template_id: 渠道模板 ID.
            other_payload: `Session / 其他` 区块.
            agent_id: 应绑定的 agent id.
            existing: 现有内部索引项.
        """

        if self.config_control_plane is None:
            raise RuntimeError("runtime config control plane unavailable")
        _ = other_payload
        binding_rule_id = (
            str(existing.get("_binding_rule_id", "") or "").strip()
            if existing is not None
            else ""
        )
        await self.config_control_plane.upsert_binding_rule(
            {
                "rule_id": binding_rule_id or self._session_binding_rule_id(channel_scope),
                "agent_id": agent_id,
                "priority": 100,
                "match": {"channel_scope": channel_scope},
                "metadata": {
                    "display_name": display_name,
                    "managed_by": "webui_session",
                    "session_key": channel_scope,
                    "channel_template_id": channel_template_id,
                },
            }
        )

    async def _save_message_response(
        self,
        *,
        channel_scope: str,
        display_name: str,
        message_response: dict[str, Any],
        existing: dict[str, Any] | None,
    ) -> None:
        """保存 Session 的消息响应区块.

        Args:
            channel_scope: Session 对应的 channel scope.
            display_name: Session 展示名.
            message_response: `Session / 消息响应` 区块.
            existing: 现有内部索引项.
        """

        if self.config_control_plane is None:
            raise RuntimeError("runtime config control plane unavailable")
        await self._delete_managed_session_message_rules(channel_scope=channel_scope)
        for raw in list(message_response.get("rules", []) or []):
            rule = dict(raw or {})
            public_event_type = str(rule.get("event_type", "") or "").strip()
            if not public_event_type:
                continue
            enabled = bool(rule.get("enabled", True))
            run_mode = str(rule.get("run_mode", "respond") or "respond")
            normalized_run_mode = run_mode if enabled else "silent_drop"
            memory_scopes = _string_list(rule.get("memory_scopes", []))
            variant = self._message_rule_variant(
                channel_scope=channel_scope,
                public_event_type=public_event_type,
                run_mode=normalized_run_mode,
                persist_event=bool(rule.get("persist_event", True)),
                memory_scopes=memory_scopes,
            )
            variant_name = str(variant["variant"])
            storage_event_type = str(variant["storage_event_type"])
            match = dict(variant["match"])
            metadata = self._session_rule_metadata(
                channel_scope=channel_scope,
                display_name=display_name,
                public_event_type=public_event_type,
            )
            if normalized_run_mode == "silent_drop" and run_mode in {"respond", "record_only"}:
                metadata["webui_run_mode"] = run_mode
            await self.config_control_plane.upsert_inbound_rule(
                {
                    "rule_id": self._session_inbound_rule_id(
                        channel_scope,
                        storage_event_type,
                        variant=variant_name,
                    ),
                    "run_mode": str(variant["run_mode"]),
                    "priority": int(variant["priority"]),
                    "match": match,
                    "metadata": metadata,
                }
            )
            variant_memory_scopes = _string_list(variant.get("memory_scopes", []))
            await self.config_control_plane.upsert_event_policy(
                {
                    "policy_id": self._session_policy_id(
                        channel_scope,
                        storage_event_type,
                        variant=variant_name,
                    ),
                    "priority": int(variant["priority"]),
                    "match": match,
                    "persist_event": bool(variant.get("persist_event", True)),
                    "extract_to_memory": bool(variant_memory_scopes),
                    "memory_scopes": variant_memory_scopes,
                    "tags": [],
                    "metadata": metadata,
                }
            )

    def _session_agent_id(self, channel_scope: str) -> str:
        """根据 channel scope 生成稳定的 Session agent id.

        Args:
            channel_scope: Session 对应的 channel scope.

        Returns:
            稳定的 Session agent id.
        """

        return f"session_{self._slug(channel_scope)}"

    def _session_binding_rule_id(self, channel_scope: str) -> str:
        """根据 channel scope 生成稳定的 binding rule id.

        Args:
            channel_scope: Session 对应的 channel scope.

        Returns:
            稳定的 binding rule id.
        """

        return f"session_binding_{self._slug(channel_scope)}"

    def _session_inbound_rule_id(
        self,
        channel_scope: str,
        event_type: str,
        *,
        variant: str = "direct",
    ) -> str:
        """根据 channel scope 和事件类型生成稳定的 inbound rule id.

        Args:
            channel_scope: Session 对应的 channel scope.
            event_type: 事件类型.
            variant: 规则展开后的具体变体名.

        Returns:
            稳定的 inbound rule id.
        """

        return (
            f"session_inbound_{self._slug(channel_scope)}_"
            f"{self._slug(event_type)}_{self._slug(variant)}"
        )

    def _session_policy_id(
        self,
        channel_scope: str,
        event_type: str,
        *,
        variant: str = "direct",
    ) -> str:
        """根据 channel scope 和事件类型生成稳定的 event policy id.

        Args:
            channel_scope: Session 对应的 channel scope.
            event_type: 事件类型.
            variant: 规则展开后的具体变体名.

        Returns:
            稳定的 event policy id.
        """

        return (
            f"session_policy_{self._slug(channel_scope)}_"
            f"{self._slug(event_type)}_{self._slug(variant)}"
        )

    def _session_model_binding_id(self, channel_scope: str) -> str:
        """根据 channel scope 生成稳定的模型绑定 id.

        Args:
            channel_scope: Session 对应的 channel scope.

        Returns:
            稳定的模型绑定 id.
        """

        return f"session_model_{self._slug(channel_scope)}"

    def _slug(self, raw: str) -> str:
        """把任意 Session 标识转换成稳定 slug.

        Args:
            raw: 原始文本.

        Returns:
            适合拼接到 id 里的 slug.
        """

        normalized = re.sub(r"[^a-zA-Z0-9]+", "_", str(raw or "").strip()).strip("_").lower()
        return normalized or "session"


# endregion
