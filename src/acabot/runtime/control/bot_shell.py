"""runtime.control.bot_shell 提供默认 Bot 的产品壳映射服务.

组件关系:

    RuntimeControlPlane
           |
           v
      BotShellControlOps
           |
           +--> RuntimeConfigControlPlane
           +--> RuntimeModelControlOps
           +--> AgentProfileRegistry

这一层负责:
- 把默认 Bot 的配置投影成前端直接可编辑的产品字段
- 把前端提交的名称 / Prompt / 模型 / 管理员 / Tools / Skills 写回真实真源
- 把默认输入处理映射到底层 inbound rule / event policy
- 对前端隐藏模型绑定和 rule id 等底层实现细节
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
from .ui_catalog import UI_EVENT_TYPE_OPTIONS


def _string_list(values: object) -> list[str]:
    """把任意值整理成去重后的字符串列表.

    Args:
        values: 原始值.

    Returns:
        去重并去掉空值后的字符串列表.
    """

    items: list[str] = []
    seen: set[str] = set()
    raw_values = list(values or []) if isinstance(values, (list, tuple, set)) else []
    for raw in raw_values:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        items.append(item)
        seen.add(item)
    return items


@dataclass(slots=True)
class BotShellControlOps:
    """默认 Bot 的产品壳控制服务.

    Attributes:
        config_control_plane (RuntimeConfigControlPlane | None): runtime 配置控制面.
        model_ops (RuntimeModelControlOps): 模型控制入口.
        profile_registry (AgentProfileRegistry | None): profile registry, 用于定位默认 bot.
    """

    config_control_plane: RuntimeConfigControlPlane | None
    model_ops: RuntimeModelControlOps
    profile_registry: AgentProfileRegistry | None

    async def get_bot(self) -> dict[str, Any]:
        """读取默认 Bot 的产品壳对象.

        Returns:
            默认 Bot 的产品字段对象.
        """

        context = await self._load_context()
        profile = context["profile"]
        if profile is None:
            raise RuntimeError("default bot profile unavailable")
        return self._to_public_record(profile=profile, context=context)

    async def upsert_bot(self, payload: dict[str, Any]) -> dict[str, Any]:
        """保存默认 Bot 的产品壳对象.

        Args:
            payload: 前端提交的 Bot 设置.

        Returns:
            保存后的默认 Bot 产品字段对象.
        """

        if self.config_control_plane is None:
            raise RuntimeError("runtime config control plane unavailable")

        context = await self._load_context()
        profile = context["profile"]
        agent_id = str(context["agent_id"] or "").strip()
        if profile is None or not agent_id:
            raise RuntimeError("default bot profile unavailable")

        fallback = self._to_public_record(profile=profile, context=context)
        normalized = self._normalize_payload(payload=payload, fallback=fallback, agent_id=agent_id)
        updated_profile = deepcopy(profile)
        updated_profile.update(
            {
                "agent_id": agent_id,
                "name": str(normalized["name"] or agent_id),
                "prompt_ref": str(normalized["prompt_ref"]),
                "default_model": self._resolve_profile_default_model(
                    model_preset_id=str(normalized["model_preset_id"]),
                    context=context,
                    existing_profile=profile,
                ),
                "summary_model_preset_id": str(normalized["summary_model_preset_id"]),
                "admin_actor_ids": _string_list(normalized["admin_actor_ids"]),
                "enabled_tools": _string_list(normalized["enabled_tools"]),
                "skill_assignments": self._build_skill_assignments(
                    skill_names=_string_list(normalized["skills"]),
                    existing_profile=profile,
                ),
            }
        )
        await self.config_control_plane.upsert_profile(updated_profile)
        self._clear_legacy_backend_admin_actor_ids()
        await self._sync_agent_model_binding(
            agent_id=agent_id,
            model_preset_id=str(normalized["model_preset_id"]),
            context=context,
        )
        await self._sync_summary_model_binding(
            summary_model_preset_id=str(normalized["summary_model_preset_id"]),
            context=context,
        )
        await self._save_default_input(default_input=dict(normalized["default_input"]), context=context)
        return await self.get_bot()

    async def upsert_admins(self, admin_actor_ids: list[str]) -> list[str]:
        """只更新共享管理员列表.

        Args:
            admin_actor_ids: 共享管理员 actor 列表.

        Returns:
            保存后的管理员列表.
        """

        if self.config_control_plane is None:
            raise RuntimeError("runtime config control plane unavailable")

        context = await self._load_context()
        profile = context["profile"]
        agent_id = str(context["agent_id"] or "").strip()
        if profile is None or not agent_id:
            raise RuntimeError("default bot profile unavailable")

        updated_profile = deepcopy(profile)
        updated_profile.update(
            {
                "agent_id": agent_id,
                "admin_actor_ids": _string_list(admin_actor_ids),
            }
        )
        await self.config_control_plane.upsert_profile(updated_profile)
        self._clear_legacy_backend_admin_actor_ids()
        saved_profile = self.config_control_plane.get_profile(agent_id)
        if saved_profile is None:
            raise RuntimeError("default bot profile unavailable after save")
        return _string_list(saved_profile.get("admin_actor_ids", []))

    async def _load_context(self) -> dict[str, Any]:
        """加载默认 Bot 壳需要的底层上下文.

        Returns:
            包含默认 agent、profile、模型预设、管理员回退值和默认输入处理状态的上下文字典.
        """

        profiles = self.config_control_plane.list_profiles() if self.config_control_plane is not None else []
        inbound_rules = self.config_control_plane.list_inbound_rules() if self.config_control_plane is not None else []
        event_policies = (
            self.config_control_plane.list_event_policies() if self.config_control_plane is not None else []
        )
        profiles_by_id = {
            str(item.get("agent_id", "") or ""): dict(item)
            for item in profiles
            if str(item.get("agent_id", "") or "").strip()
        }
        agent_id = self._default_agent_id(profiles)
        profile = profiles_by_id.get(agent_id)

        presets = await self.model_ops.list_model_presets()
        bindings = await self.model_ops.list_model_bindings()
        main_binding = next(
            (item for item in bindings if item.target_type == "agent" and item.target_id == agent_id),
            None,
        )
        summary_binding = next(
            (
                item
                for item in bindings
                if item.target_type == "system" and item.target_id == "compactor_summary"
            ),
            None,
        )
        effective_main = await self.model_ops.preview_effective_agent_model(agent_id) if agent_id else None
        effective_summary = await self.model_ops.preview_effective_summary_model()

        default_input_rules = {
            event_type: self._default_input_rule(event_type=event_type)
            for event_type in UI_EVENT_TYPE_OPTIONS
        }
        default_input_inbound_ids: dict[str, str] = {}
        default_input_policy_ids: dict[str, str] = {}
        for rule in inbound_rules:
            match = dict(rule.get("match", {}) or {})
            if not self._is_bot_default_input_match(match):
                continue
            event_type = str(match.get("event_type", "") or "").strip()
            default_rule = default_input_rules.get(event_type)
            if default_rule is None:
                continue
            metadata = dict(rule.get("metadata", {}) or {})
            persisted_run_mode = str(rule.get("run_mode", "respond") or "respond")
            preferred_run_mode = str(metadata.get("webui_run_mode", "") or "").strip()
            default_rule["enabled"] = persisted_run_mode != "silent_drop"
            if not default_rule["enabled"] and preferred_run_mode in {"respond", "record_only"}:
                default_rule["run_mode"] = preferred_run_mode
            else:
                default_rule["run_mode"] = persisted_run_mode
            default_input_inbound_ids[event_type] = str(rule.get("rule_id", "") or "")
        for policy in event_policies:
            match = dict(policy.get("match", {}) or {})
            if not self._is_bot_default_input_match(match):
                continue
            event_type = str(match.get("event_type", "") or "").strip()
            default_rule = default_input_rules.get(event_type)
            if default_rule is None:
                continue
            default_rule["persist_event"] = bool(policy.get("persist_event", True))
            default_rule["memory_scopes"] = _string_list(policy.get("memory_scopes", []))
            default_rule["tags"] = _string_list(policy.get("tags", []))
            default_input_policy_ids[event_type] = str(policy.get("policy_id", "") or "")

        return {
            "agent_id": agent_id,
            "profile": profile,
            "profiles_by_id": profiles_by_id,
            "preset_model_names": {item.preset_id: item.model for item in presets},
            "main_binding": main_binding,
            "summary_binding": summary_binding,
            "fallback_admin_actor_ids": self._legacy_backend_admin_actor_ids(),
            "default_input_rules": default_input_rules,
            "default_input_inbound_ids": default_input_inbound_ids,
            "default_input_policy_ids": default_input_policy_ids,
            "effective_main_preset_id": (
                str(getattr(getattr(effective_main, "request", None), "preset_id", "") or "")
                if effective_main is not None
                else ""
            ),
            "effective_summary_preset_id": str(
                getattr(getattr(effective_summary, "request", None), "preset_id", "") or ""
            ),
        }

    def _default_agent_id(self, profiles: list[dict[str, Any]]) -> str:
        """决定默认 Bot 的 agent id.

        Args:
            profiles: 当前可见的 profile 列表.

        Returns:
            默认 Bot 的 agent id; 如果无法确定则返回空字符串.
        """

        if self.profile_registry is not None:
            agent_id = str(getattr(self.profile_registry, "default_agent_id", "") or "").strip()
            if agent_id:
                return agent_id
        for item in profiles:
            agent_id = str(item.get("agent_id", "") or "").strip()
            if agent_id:
                return agent_id
        return ""

    def _to_public_record(self, *, profile: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """把默认 Bot 的底层真源投影成前端对象.

        Args:
            profile: 默认 Bot 对应的 profile.
            context: `_load_context` 返回的上下文.

        Returns:
            前端可直接消费的 Bot 对象.
        """

        skill_names = [
            str(item.get("skill_name", "") or "")
            for item in list(profile.get("skill_assignments", []) or [])
            if str(dict(item).get("skill_name", "") or "").strip()
        ]
        return {
            "agent_id": str(context["agent_id"] or ""),
            "name": str(profile.get("name", "") or context["agent_id"] or ""),
            "prompt_ref": str(profile.get("prompt_ref", "") or ""),
            "model_preset_id": str(context["effective_main_preset_id"] or ""),
            "summary_model_preset_id": str(
                profile.get("summary_model_preset_id", "")
                or self._binding_first_preset_id(context["summary_binding"])
                or context["effective_summary_preset_id"]
                or ""
            ),
            "admin_actor_ids": _string_list(
                profile.get("admin_actor_ids", context["fallback_admin_actor_ids"])
            ),
            "enabled_tools": _string_list(profile.get("enabled_tools", [])),
            "skills": _string_list(skill_names),
            "default_input": self._default_input_payload(context=context),
        }

    def _normalize_payload(
        self,
        *,
        payload: dict[str, Any],
        fallback: dict[str, Any],
        agent_id: str,
    ) -> dict[str, Any]:
        """把前端提交的 Bot 设置整理成稳定形状.

        Args:
            payload: 前端提交值.
            fallback: 当前已有公开对象, 用于补默认值.
            agent_id: 默认 Bot 的 agent id.

        Returns:
            归一化后的 Bot 设置字典.
        """

        return {
            "agent_id": agent_id,
            "name": str(payload.get("name", "") or fallback.get("name", "") or agent_id).strip(),
            "prompt_ref": str(payload.get("prompt_ref", "") or fallback.get("prompt_ref", "") or "").strip(),
            "model_preset_id": str(
                payload.get("model_preset_id", "") or fallback.get("model_preset_id", "") or ""
            ).strip(),
            "summary_model_preset_id": str(
                payload.get("summary_model_preset_id", "")
                or fallback.get("summary_model_preset_id", "")
                or ""
            ).strip(),
            "admin_actor_ids": _string_list(
                payload.get("admin_actor_ids", fallback.get("admin_actor_ids", []))
            ),
            "enabled_tools": _string_list(payload.get("enabled_tools", fallback.get("enabled_tools", []))),
            "skills": _string_list(payload.get("skills", fallback.get("skills", []))),
            "default_input": self._normalize_default_input(
                payload=dict(payload.get("default_input", {}) or {}),
                fallback=dict(fallback.get("default_input", {}) or {}),
            ),
        }

    def _default_input_rule(self, *, event_type: str) -> dict[str, Any]:
        """返回单个事件类型的默认输入处理规则.

        Args:
            event_type: 事件类型.

        Returns:
            默认输入处理规则对象.
        """

        return {
            "event_type": event_type,
            "enabled": True,
            "run_mode": "respond",
            "persist_event": True,
            "memory_scopes": [],
            "tags": [],
        }

    def _default_input_payload(self, *, context: dict[str, Any]) -> dict[str, Any]:
        """把默认输入处理上下文转换成前端对象.

        Args:
            context: `_load_context` 返回的上下文.

        Returns:
            前端可消费的默认输入处理区块.
        """

        rules = []
        raw_rules = dict(context.get("default_input_rules", {}) or {})
        for event_type in UI_EVENT_TYPE_OPTIONS:
            rule = dict(raw_rules.get(event_type, self._default_input_rule(event_type=event_type)))
            rule["event_type"] = event_type
            rules.append(rule)
        return {"rules": rules}

    def _normalize_default_input(
        self,
        *,
        payload: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        """规范化默认输入处理 payload.

        Args:
            payload: 原始默认输入处理区块.
            fallback: 回退值.

        Returns:
            规范化后的默认输入处理区块.
        """

        rule_map = {
            str(item.get("event_type", "") or ""): {
                key: value
                for key, value in dict(item).items()
                if key != "event_type"
            }
            for item in list(dict(fallback or {}).get("rules", []) or [])
            if str(dict(item).get("event_type", "") or "").strip()
        }
        for raw in list(dict(payload or {}).get("rules", []) or []):
            raw_map = dict(raw or {})
            event_type = str(raw_map.get("event_type", "") or "").strip()
            if event_type not in UI_EVENT_TYPE_OPTIONS:
                continue
            base = dict(rule_map.get(event_type, self._default_input_rule(event_type=event_type)))
            run_mode = str(raw_map.get("run_mode", base.get("run_mode", "respond")) or "respond")
            if run_mode not in {"respond", "record_only", "silent_drop"}:
                raise ValueError(f"unsupported run_mode: {run_mode}")
            rule_map[event_type] = {
                "enabled": bool(raw_map.get("enabled", base.get("enabled", True))),
                "run_mode": run_mode,
                "persist_event": bool(raw_map.get("persist_event", base.get("persist_event", True))),
                "memory_scopes": _string_list(raw_map.get("memory_scopes", base.get("memory_scopes", []))),
                "tags": _string_list(raw_map.get("tags", base.get("tags", []))),
            }
        normalized_rules = []
        for event_type in UI_EVENT_TYPE_OPTIONS:
            base = dict(rule_map.get(event_type, self._default_input_rule(event_type=event_type)))
            normalized_rules.append(
                {
                    "event_type": event_type,
                    "enabled": bool(base.get("enabled", True)),
                    "run_mode": str(base.get("run_mode", "respond") or "respond"),
                    "persist_event": bool(base.get("persist_event", True)),
                    "memory_scopes": _string_list(base.get("memory_scopes", [])),
                    "tags": _string_list(base.get("tags", [])),
                }
            )
        return {"rules": normalized_rules}

    def _is_bot_default_input_match(self, match: dict[str, Any]) -> bool:
        """判断一条规则是否属于默认 Bot 输入处理.

        Args:
            match: 底层 rule/policy 的 match 字段.

        Returns:
            属于默认 Bot 输入处理时返回 `True`.
        """

        event_type = str(match.get("event_type", "") or "").strip()
        if not event_type or event_type not in UI_EVENT_TYPE_OPTIONS:
            return False
        if str(match.get("channel_scope", "") or "").strip():
            return False
        for key in (
            "platform",
            "message_subtype",
            "notice_type",
            "notice_subtype",
            "actor_id",
            "targets_self",
            "mentions_self",
            "mentioned_everyone",
            "reply_targets_self",
        ):
            if match.get(key) not in (None, "", [], False):
                return False
        if list(match.get("sender_roles", []) or []):
            return False
        return True

    def _build_skill_assignments(
        self,
        *,
        skill_names: list[str],
        existing_profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """把 skill 名列表转换成 profile skill assignments.

        Args:
            skill_names: 前端选择的 skill 名列表.
            existing_profile: 已有 profile, 用于保留旧的委派信息.

        Returns:
            可直接写回 profile 的 skill assignments.
        """

        existing_map = {
            str(item.get("skill_name", "") or ""): dict(item)
            for item in list(existing_profile.get("skill_assignments", []) or [])
            if str(dict(item).get("skill_name", "") or "").strip()
        }
        items: list[dict[str, Any]] = []
        for skill_name in skill_names:
            items.append(dict(existing_map.get(skill_name, {"skill_name": skill_name})))
        return items

    def _resolve_profile_default_model(
        self,
        *,
        model_preset_id: str,
        context: dict[str, Any],
        existing_profile: dict[str, Any],
    ) -> str:
        """决定 profile.default_model 应写入什么值.

        Args:
            model_preset_id: 目标主模型 preset id.
            context: `_load_context` 返回的上下文.
            existing_profile: 当前 profile 配置.

        Returns:
            profile.default_model 应写回的模型名.
        """

        preset_id = str(model_preset_id or "").strip()
        if preset_id:
            model_name = str(context["preset_model_names"].get(preset_id, "") or "").strip()
            if model_name:
                return model_name
        return str(existing_profile.get("default_model", "") or "")

    def _legacy_backend_admin_actor_ids(self) -> list[str]:
        """读取 legacy backend 区块里的管理员列表.

        Returns:
            `backend.admin_actor_ids` 里的 actor 列表; 不存在时返回空列表.
        """

        if self.config_control_plane is None:
            return []
        backend_conf = dict(self.config_control_plane.config.get("runtime", {}).get("backend", {}) or {})
        return _string_list(backend_conf.get("admin_actor_ids", []))

    def _clear_legacy_backend_admin_actor_ids(self) -> None:
        """清理 legacy backend 配置里的管理员列表.

        当 Bot 已经写入共享管理员列表后, 旧的 `backend.admin_actor_ids`
        只保留兼容读取意义, 不再继续作为写入真源.
        """

        if self.config_control_plane is None:
            return
        data = self.config_control_plane.config.to_dict()
        runtime_conf = dict(data.get("runtime", {}) or {})
        backend_conf = dict(runtime_conf.get("backend", {}) or {})
        if "admin_actor_ids" not in backend_conf:
            return
        backend_conf.pop("admin_actor_ids", None)
        runtime_conf["backend"] = backend_conf
        data["runtime"] = runtime_conf
        self.config_control_plane.config.replace(data)
        self.config_control_plane.config.save()

    async def _sync_agent_model_binding(
        self,
        *,
        agent_id: str,
        model_preset_id: str,
        context: dict[str, Any],
    ) -> None:
        """同步默认 Bot 主模型的 agent 绑定.

        Args:
            agent_id: 默认 Bot 的 agent id.
            model_preset_id: 目标主模型 preset id.
            context: `_load_context` 返回的上下文.
        """

        existing_binding = context["main_binding"]
        preset_id = str(model_preset_id or "").strip()
        if preset_id:
            binding_id = (
                existing_binding.binding_id
                if existing_binding is not None
                else self._bot_model_binding_id(agent_id)
            )
            await self.model_ops.upsert_model_binding(
                ModelBinding(
                    binding_id=binding_id,
                    target_type="agent",
                    target_id=agent_id,
                    preset_id=preset_id,
                )
            )
            return
        if existing_binding is not None:
            await self.model_ops.delete_model_binding(existing_binding.binding_id)

    async def _sync_summary_model_binding(
        self,
        *,
        summary_model_preset_id: str,
        context: dict[str, Any],
    ) -> None:
        """同步默认摘要模型绑定.

        Args:
            summary_model_preset_id: 目标摘要模型 preset id.
            context: `_load_context` 返回的上下文.
        """

        existing_binding = context["summary_binding"]
        preset_id = str(summary_model_preset_id or "").strip()
        if preset_id:
            binding_id = (
                existing_binding.binding_id
                if existing_binding is not None
                else "bot_summary_model"
            )
            await self.model_ops.upsert_model_binding(
                ModelBinding(
                    binding_id=binding_id,
                    target_type="system",
                    target_id="compactor_summary",
                    preset_ids=[preset_id],
                )
            )
            return
        if existing_binding is not None:
            await self.model_ops.delete_model_binding(existing_binding.binding_id)

    async def _save_default_input(self, *, default_input: dict[str, Any], context: dict[str, Any]) -> None:
        """保存默认输入处理区块.

        Args:
            default_input: 规范化后的默认输入处理区块.
            context: `_load_context` 返回的上下文.
        """

        if self.config_control_plane is None:
            raise RuntimeError("runtime config control plane unavailable")
        inbound_rule_ids = dict(context.get("default_input_inbound_ids", {}) or {})
        event_policy_ids = dict(context.get("default_input_policy_ids", {}) or {})
        for raw in list(default_input.get("rules", []) or []):
            rule = dict(raw or {})
            event_type = str(rule.get("event_type", "") or "").strip()
            if event_type not in UI_EVENT_TYPE_OPTIONS:
                continue
            inbound_rule_id = str(inbound_rule_ids.get(event_type, "") or "") or self._bot_inbound_rule_id(
                event_type
            )
            event_policy_id = str(event_policy_ids.get(event_type, "") or "") or self._bot_policy_id(event_type)
            enabled = bool(rule.get("enabled", True))
            run_mode = str(rule.get("run_mode", "respond") or "respond")
            await self.config_control_plane.upsert_inbound_rule(
                {
                    "rule_id": inbound_rule_id,
                    "run_mode": run_mode if enabled else "silent_drop",
                    "priority": 100,
                    "match": {"event_type": event_type},
                    "metadata": {
                        "managed_by": "webui_bot",
                        "webui_run_mode": run_mode if not enabled else "",
                    },
                }
            )
            memory_scopes = _string_list(rule.get("memory_scopes", []))
            await self.config_control_plane.upsert_event_policy(
                {
                    "policy_id": event_policy_id,
                    "priority": 100,
                    "match": {"event_type": event_type},
                    "persist_event": bool(rule.get("persist_event", True)),
                    "extract_to_memory": bool(memory_scopes),
                    "memory_scopes": memory_scopes,
                    "tags": _string_list(rule.get("tags", [])),
                    "metadata": {"managed_by": "webui_bot"},
                }
            )

    def _binding_first_preset_id(self, binding: ModelBinding | None) -> str:
        """读取一条绑定里的首个 preset id.

        Args:
            binding: 目标绑定对象.

        Returns:
            首个可用 preset id; 不存在时返回空字符串.
        """

        if binding is None:
            return ""
        if binding.preset_ids:
            return str(binding.preset_ids[0] or "")
        return str(binding.preset_id or "")

    def _bot_model_binding_id(self, agent_id: str) -> str:
        """为默认 Bot 生成稳定的模型绑定 id.

        Args:
            agent_id: 默认 Bot 的 agent id.

        Returns:
            稳定的模型绑定 id.
        """

        return f"bot_model_{self._slug(agent_id)}"

    def _bot_inbound_rule_id(self, event_type: str) -> str:
        """为默认 Bot 生成稳定的 inbound rule id.

        Args:
            event_type: 事件类型.

        Returns:
            稳定的 inbound rule id.
        """

        return f"bot_default_inbound_{self._slug(event_type)}"

    def _bot_policy_id(self, event_type: str) -> str:
        """为默认 Bot 生成稳定的 event policy id.

        Args:
            event_type: 事件类型.

        Returns:
            稳定的 event policy id.
        """

        return f"bot_default_policy_{self._slug(event_type)}"

    def _slug(self, value: str) -> str:
        """把任意字符串转换成稳定 slug.

        Args:
            value: 原始字符串.

        Returns:
            只包含小写字母、数字和下划线的 slug.
        """

        slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip()).strip("_").lower()
        return slug or "default"
