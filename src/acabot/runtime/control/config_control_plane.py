"""runtime.config_control_plane 提供 WebUI 需要的配置真源读写与热刷新.

当前这个控制面只保留运行时真正还在使用的配置能力:

- profiles
- prompts
- gateway
- runtime plugins
- session-config 驱动的 reload
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from acabot.config import Config

from ..computer import ComputerPolicy, parse_computer_policy
from ..contracts import AgentProfile
from ..model.model_registry import FileSystemModelRegistryManager
from ..model.model_targets import build_agent_model_targets
from ..plugin_manager import RuntimePluginManager, RuntimePluginSpec, load_runtime_plugin
from ..router import RuntimeRouter
from ..skills import SkillCatalog
from ..subagents import SubagentExecutorRegistry
from .profile_loader import (
    AgentProfileRegistry,
    ChainedPromptLoader,
    FileSystemProfileLoader,
    FileSystemPromptLoader,
    PromptLoader,
    ReloadablePromptLoader,
    StaticPromptLoader,
    normalize_enabled_tools,
    normalize_profile_config,
    resolve_profile_skills,
)
from .session_loader import ConfigBackedSessionConfigLoader, SessionConfigLoader
from .session_runtime import SessionRuntime


def _resolve_filesystem_path(
    config: Config,
    fs_conf: dict[str, object],
    *,
    key: str,
    default: str,
) -> Path:
    """把 filesystem 相对路径解析到配置基目录.

    Args:
        config: 当前 runtime 配置.
        fs_conf: `runtime.filesystem` 配置块.
        key: 目标字段名.
        default: 缺省路径.

    Returns:
        Path: 解析后的绝对路径.
    """

    base_dir = Path(str(fs_conf.get("base_dir", ".") or "."))
    if not base_dir.is_absolute():
        base_dir = config.resolve_path(base_dir)
    raw_value = Path(str(fs_conf.get(key, default) or default))
    if raw_value.is_absolute():
        return raw_value
    return (base_dir / raw_value).resolve()


def _build_session_runtime(config: Config) -> SessionRuntime:
    """按当前配置构造 session runtime.

    Args:
        config: 当前 runtime 配置.

    Returns:
        SessionRuntime: 当前有效的 session-config 决策运行时.
    """

    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if "sessions_dir" in fs_conf:
        sessions_dir = _resolve_filesystem_path(
            config,
            fs_conf,
            key="sessions_dir",
            default="sessions",
        )
        return SessionRuntime(SessionConfigLoader(config_root=sessions_dir))
    return SessionRuntime(ConfigBackedSessionConfigLoader(config))


def _default_computer_policy(config: Config) -> ComputerPolicy:
    """读取 profile 默认 computer policy.

    Args:
        config: 当前 runtime 配置.

    Returns:
        ComputerPolicy: 默认 computer policy.
    """

    runtime_conf = config.get("runtime", {})
    computer_conf = dict(runtime_conf.get("computer", {}))
    defaults = ComputerPolicy(
        backend=str(computer_conf.get("backend", "host") or "host"),
        allow_exec=bool(computer_conf.get("allow_exec", True)),
        allow_sessions=bool(computer_conf.get("allow_sessions", True)),
        auto_stage_attachments=bool(computer_conf.get("auto_stage_attachments", True)),
        network_mode=str(computer_conf.get("network_mode", "enabled") or "enabled"),
    )
    return parse_computer_policy(computer_conf, defaults=defaults)


def _build_profiles(config: Config) -> dict[str, AgentProfile]:
    """从运行配置构造 inline profiles.

    Args:
        config: 当前 runtime 配置.

    Returns:
        dict[str, AgentProfile]: 解析后的 profile 映射.
    """

    runtime_conf = dict(config.get("runtime", {}) or {})
    agent_conf = dict(config.get("agent", {}) or {})
    profiles_conf = runtime_conf.get("profiles", {})
    default_policy = _default_computer_policy(config)
    if profiles_conf:
        profiles: dict[str, AgentProfile] = {}
        for agent_id, profile_conf in dict(profiles_conf).items():
            profile_map = normalize_profile_config(dict(profile_conf or {}))
            profiles[agent_id] = AgentProfile(
                agent_id=agent_id,
                name=str(profile_map.get("name", agent_id) or agent_id),
                prompt_ref=str(profile_map.get("prompt_ref", f"prompt/{agent_id}") or f"prompt/{agent_id}"),
                enabled_tools=[str(item) for item in list(profile_map.get("enabled_tools", []) or [])],
                skills=resolve_profile_skills(profile_map),
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
            enabled_tools=normalize_enabled_tools(runtime_conf.get("enabled_tools", [])),
            skills=resolve_profile_skills(dict(runtime_conf)),
            computer_policy=default_policy,
            config=dict(agent_conf),
        )
    }


def _build_filesystem_profiles(config: Config) -> dict[str, AgentProfile]:
    """从文件系统加载 profiles.

    Args:
        config: 当前 runtime 配置.

    Returns:
        dict[str, AgentProfile]: 文件系统 profile 映射.
    """

    runtime_conf = dict(config.get("runtime", {}) or {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    if not bool(fs_conf.get("enabled", False)):
        return {}
    profiles_dir = _resolve_filesystem_path(config, fs_conf, key="profiles_dir", default="profiles")
    loader = FileSystemProfileLoader(
        profiles_dir,
        default_computer_policy=_default_computer_policy(config),
    )
    return loader.load_all()


def _build_prompt_map(config: Config, profiles: dict[str, AgentProfile]) -> dict[str, str]:
    """构造 inline prompt 映射.

    Args:
        config: 当前 runtime 配置.
        profiles: 当前 profile 映射.

    Returns:
        dict[str, str]: `prompt_ref -> text` 映射.
    """

    runtime_conf = dict(config.get("runtime", {}) or {})
    agent_conf = dict(config.get("agent", {}) or {})
    prompts = dict(runtime_conf.get("prompts", {}) or {})
    default_prompt_text = str(agent_conf.get("system_prompt", "") or "")
    for profile in profiles.values():
        prompts.setdefault(profile.prompt_ref, default_prompt_text)
    return prompts


def _build_prompt_loader(config: Config, profiles: dict[str, AgentProfile]) -> PromptLoader:
    """构造 prompt loader.

    Args:
        config: 当前 runtime 配置.
        profiles: 当前 profile 映射.

    Returns:
        PromptLoader: 当前有效 prompt loader.
    """

    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    static_loader = StaticPromptLoader(_build_prompt_map(config, profiles))
    if not bool(fs_conf.get("enabled", False)):
        return static_loader
    prompts_dir = _resolve_filesystem_path(config, fs_conf, key="prompts_dir", default="prompts")
    return ChainedPromptLoader([
        FileSystemPromptLoader(prompts_dir),
        static_loader,
    ])


def _profile_to_config(profile: AgentProfile) -> dict[str, Any]:
    """把 profile 对象转成可写回/可展示配置.

    Args:
        profile: 当前 profile.

    Returns:
        dict[str, Any]: 适合控制面展示的 profile 配置.
    """

    data = dict(profile.config)
    data.pop("skill_assignments", None)
    data["agent_id"] = profile.agent_id
    data["name"] = profile.name
    data["prompt_ref"] = profile.prompt_ref
    data["enabled_tools"] = list(profile.enabled_tools)
    data["skills"] = list(profile.skills)
    if profile.computer_policy is not None:
        data["computer"] = {
            "backend": profile.computer_policy.backend,
            "allow_exec": profile.computer_policy.allow_exec,
            "allow_sessions": profile.computer_policy.allow_sessions,
            "auto_stage_attachments": profile.computer_policy.auto_stage_attachments,
            "network_mode": profile.computer_policy.network_mode,
        }
    return data


class RuntimeConfigControlPlane:
    """面向 WebUI 的 runtime 配置读写与热刷新服务."""

    def __init__(
        self,
        *,
        config: Config,
        router: RuntimeRouter,
        profile_registry: AgentProfileRegistry,
        prompt_loader: ReloadablePromptLoader,
        model_registry_manager: FileSystemModelRegistryManager | None = None,
        skill_catalog: SkillCatalog | None = None,
        plugin_manager: RuntimePluginManager | None = None,
        subagent_executor_registry: SubagentExecutorRegistry | None = None,
        tool_broker=None,
        subagent_delegator=None,
        local_subagent_executor: Callable[[Any], Awaitable[Any]] | None = None,
        builtin_plugin_factory: Callable[[dict[str, AgentProfile]], list[Any]] | None = None,
    ) -> None:
        """初始化 RuntimeConfigControlPlane.

        Args:
            config: 当前 runtime 配置.
            router: 当前 runtime router.
            profile_registry: profile registry.
            prompt_loader: 可热刷新的 prompt loader.
            skill_catalog: 可选 skill catalog.
            plugin_manager: 可选 runtime plugin manager.
            subagent_executor_registry: 可选 subagent executor 注册表.
            tool_broker: 可选 tool broker.
            subagent_delegator: 可选 subagent delegator.
            local_subagent_executor: 本地 subagent 执行入口.
            builtin_plugin_factory: builtin plugin 工厂.
        """

        self.config = config
        self.router = router
        self.profile_registry = profile_registry
        self.prompt_loader = prompt_loader
        self.model_registry_manager = model_registry_manager
        self.skill_catalog = skill_catalog
        self.plugin_manager = plugin_manager
        self.subagent_executor_registry = subagent_executor_registry
        self.tool_broker = tool_broker
        self.subagent_delegator = subagent_delegator
        self.local_subagent_executor = local_subagent_executor
        self.builtin_plugin_factory = builtin_plugin_factory

    def storage_mode(self) -> str:
        """返回当前配置存储模式.

        Returns:
            str: `filesystem` 或 `inline`.
        """

        runtime_conf = self.config.get("runtime", {})
        fs_conf = dict(runtime_conf.get("filesystem", {}))
        return "filesystem" if bool(fs_conf.get("enabled", False)) else "inline"

    async def reload_runtime_configuration(self) -> dict[str, Any]:
        """重新加载 runtime 配置并热更新相关组件.

        Returns:
            dict[str, Any]: 这次热刷新后的摘要.
        """

        self.config.reload_from_file()
        runtime_conf = dict(self.config.get("runtime", {}) or {})
        profiles = _build_profiles(self.config)
        profiles.update(_build_filesystem_profiles(self.config))
        if not profiles:
            raise ValueError("runtime configuration must contain at least one profile")
        default_agent_id = str(runtime_conf.get("default_agent_id", next(iter(profiles))) or next(iter(profiles)))

        if self.model_registry_manager is not None:
            previous_agent_targets = [
                target
                for target in self.model_registry_manager.target_catalog.list_targets()
                if target.source_kind == "agent"
            ]
            self.model_registry_manager.target_catalog.replace_agent_targets(
                build_agent_model_targets(profiles.values())
            )
            reload_snapshot = await self.model_registry_manager.reload()
            if not reload_snapshot.ok:
                self.model_registry_manager.target_catalog.replace_agent_targets(previous_agent_targets)
                rollback_snapshot = await self.model_registry_manager.reload()
                if not rollback_snapshot.ok:
                    raise ValueError(rollback_snapshot.error or reload_snapshot.error or "model registry reload failed")
                raise ValueError(reload_snapshot.error or "model registry reload failed")
        self.profile_registry.reload(
            profiles=profiles,
            default_agent_id=default_agent_id,
        )
        self.prompt_loader.replace_loader(_build_prompt_loader(self.config, profiles))
        self.router.default_agent_id = default_agent_id
        self.router.session_runtime = _build_session_runtime(self.config)

        if self.tool_broker is not None:
            self.tool_broker.default_agent_id = default_agent_id
        if self.subagent_delegator is not None:
            self.subagent_delegator.default_agent_id = default_agent_id
        if self.skill_catalog is not None:
            self.skill_catalog.reload()
        if self.subagent_executor_registry is not None:
            self.subagent_executor_registry.unregister_source("runtime:local_profile")
            if self.local_subagent_executor is not None:
                for profile in profiles.values():
                    metadata = dict(profile.config.get("metadata", {}) or {})
                    managed_by = str(metadata.get("managed_by", "") or "").strip()
                    if managed_by in {"webui_session", "webui_v2_session"} or str(metadata.get("session_key", "") or "").strip():
                        continue
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
            await self.plugin_manager.reload_from_config()
        return {
            "default_agent_id": default_agent_id,
            "profile_count": len(profiles),
            "storage_mode": self.storage_mode(),
        }

    def list_profiles(self) -> list[dict[str, Any]]:
        """列出全部 profiles.

        Returns:
            list[dict[str, Any]]: 当前全部 profile 配置.
        """

        return [_profile_to_config(item) for item in self.profile_registry.list_profiles()]

    def get_gateway_config(self) -> dict[str, Any]:
        """读取 gateway 配置视图.

        Returns:
            dict[str, Any]: 当前 gateway 配置.
        """

        gateway_conf = dict(self.config.get("gateway", {}) or {})
        return {
            "host": str(gateway_conf.get("host", "0.0.0.0") or "0.0.0.0"),
            "port": int(gateway_conf.get("port", 8080) or 8080),
            "timeout": float(gateway_conf.get("timeout", 10.0) or 10.0),
            "token": str(gateway_conf.get("token", "") or ""),
        }

    async def upsert_gateway_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        """写回 gateway 配置.

        Args:
            payload: 新的 gateway 配置片段.

        Returns:
            dict[str, Any]: 写回后的 gateway 配置.
        """

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

    def get_long_term_memory_config(self) -> dict[str, Any]:
        """读取长期记忆配置视图.

        Returns:
            dict[str, Any]: 当前长期记忆配置和模型绑定状态.
        """

        runtime_conf = dict(self.config.get("runtime", {}) or {})
        current_conf = dict(runtime_conf.get("long_term_memory", {}) or {})
        normalized = {
            "enabled": bool(current_conf.get("enabled", False)),
            "storage_dir": str(current_conf.get("storage_dir", "long-term-memory/lancedb") or "long-term-memory/lancedb"),
            "window_size": max(1, int(current_conf.get("window_size", 50) or 50)),
            "overlap_size": max(0, int(current_conf.get("overlap_size", 10) or 10)),
            "max_entries": max(1, int(current_conf.get("max_entries", 8) or 8)),
            "extractor_version": str(current_conf.get("extractor_version", "ltm-extractor-v1") or "ltm-extractor-v1"),
        }
        if normalized["overlap_size"] >= normalized["window_size"]:
            normalized["overlap_size"] = max(0, normalized["window_size"] - 1)

        required_target_ids = [
            "system:ltm_extract",
            "system:ltm_query_plan",
            "system:ltm_embed",
        ]
        missing_target_ids: list[str] = []
        if self.model_registry_manager is not None:
            missing_target_ids = [
                target_id
                for target_id in required_target_ids
                if self.model_registry_manager.resolve_target_request(target_id) is None
            ]
        return {
            **normalized,
            "required_target_ids": required_target_ids,
            "missing_target_ids": missing_target_ids,
            "restart_required": True,
        }

    async def upsert_long_term_memory_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        """写回长期记忆配置.

        Args:
            payload: 前端提交的长期记忆配置片段.

        Returns:
            dict[str, Any]: 写回后的长期记忆配置视图.
        """

        current = self.get_long_term_memory_config()
        next_conf = {
            "enabled": bool(payload.get("enabled", current["enabled"])),
            "storage_dir": str(payload.get("storage_dir", current["storage_dir"]) or current["storage_dir"]),
            "window_size": max(1, int(payload.get("window_size", current["window_size"]) or current["window_size"])),
            "overlap_size": max(0, int(payload.get("overlap_size", current["overlap_size"]) or current["overlap_size"])),
            "max_entries": max(1, int(payload.get("max_entries", current["max_entries"]) or current["max_entries"])),
            "extractor_version": str(
                payload.get("extractor_version", current["extractor_version"]) or current["extractor_version"]
            ),
        }
        if next_conf["overlap_size"] >= next_conf["window_size"]:
            next_conf["overlap_size"] = max(0, next_conf["window_size"] - 1)
        data = self.config.to_dict()
        runtime_conf = dict(data.get("runtime", {}) or {})
        runtime_conf["long_term_memory"] = next_conf
        data["runtime"] = runtime_conf
        self.config.replace(data)
        self.config.save()
        return self.get_long_term_memory_config()

    def get_profile(self, agent_id: str) -> dict[str, Any] | None:
        """读取单个 profile.

        Args:
            agent_id: 目标 agent_id.

        Returns:
            dict[str, Any] | None: 命中的 profile 配置.
        """

        profile = self.profile_registry.profiles.get(agent_id)
        if profile is None:
            return None
        return _profile_to_config(profile)

    async def upsert_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        """新增或更新一个 profile.

        Args:
            payload: profile 配置片段.

        Returns:
            dict[str, Any]: 写回后的 profile 配置.
        """

        agent_id = str(payload.get("agent_id", "") or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        normalized = normalize_profile_config(dict(payload))
        normalized["agent_id"] = agent_id
        normalized.setdefault("name", agent_id)
        normalized.setdefault("prompt_ref", f"prompt/{agent_id}")
        normalized.setdefault("enabled_tools", [])
        normalized.setdefault("skills", [])
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
        """删除一个 profile.

        Args:
            agent_id: 目标 agent_id.

        Returns:
            bool: 是否真的删除了对象.
        """

        if self.model_registry_manager is not None:
            binding = self.model_registry_manager.active_registry.binding_for_target(f"agent:{agent_id}")
            if binding is not None:
                raise ValueError(f"profile still has model binding: agent:{agent_id}")

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
        """列出全部 prompts.

        Returns:
            list[dict[str, Any]]: 当前全部 prompt 配置.
        """

        prompts: list[dict[str, Any]] = []
        seen: set[str] = set()
        runtime_conf = self.config.get("runtime", {})
        if self.storage_mode() == "filesystem":
            prompts_dir = self._prompts_dir()
            if prompts_dir.exists():
                for path in sorted(prompts_dir.rglob("*")):
                    if not path.is_file() or path.suffix not in {".md", ".txt", ".prompt"}:
                        continue
                    prompt_ref = self._prompt_ref_from_path(path)
                    prompts.append({
                        "prompt_ref": prompt_ref,
                        "content": path.read_text(encoding="utf-8"),
                        "source": "filesystem",
                    })
                    seen.add(prompt_ref)
        for prompt_ref, content in sorted(dict(runtime_conf.get("prompts", {}) or {}).items()):
            prompt_ref = str(prompt_ref)
            if prompt_ref in seen:
                continue
            prompts.append({
                "prompt_ref": prompt_ref,
                "content": str(content or ""),
                "source": "inline",
            })
            seen.add(prompt_ref)
        return prompts

    def get_prompt(self, prompt_ref: str) -> dict[str, Any] | None:
        """读取单个 prompt.

        Args:
            prompt_ref: 目标 prompt_ref.

        Returns:
            dict[str, Any] | None: 命中的 prompt 配置.
        """

        prompt_ref = str(prompt_ref or "").strip()
        if not prompt_ref:
            return None
        if self.storage_mode() == "filesystem":
            path = self._resolve_prompt_path(prompt_ref)
            if path is not None and path.exists():
                return {
                    "prompt_ref": prompt_ref,
                    "content": path.read_text(encoding="utf-8"),
                    "source": "filesystem",
                }
        runtime_conf = self.config.get("runtime", {})
        prompts_conf = dict(runtime_conf.get("prompts", {}) or {})
        if prompt_ref not in prompts_conf:
            return None
        return {
            "prompt_ref": prompt_ref,
            "content": str(prompts_conf[prompt_ref] or ""),
            "source": "inline",
        }

    async def upsert_prompt(self, prompt_ref: str, content: str) -> dict[str, Any]:
        """新增或更新一个 prompt.

        Args:
            prompt_ref: 目标 prompt_ref.
            content: 新文本.

        Returns:
            dict[str, Any]: 写回后的 prompt 配置.
        """

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
        """删除一个 prompt.

        Args:
            prompt_ref: 目标 prompt_ref.

        Returns:
            bool: 是否真的删除了对象.
        """

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
        """返回 runtime.plugins 的配置视图.

        Returns:
            list[dict[str, Any]]: 当前插件配置列表.
        """

        runtime_conf = dict(self.config.get("runtime", {}) or {})
        raw_plugins = list(runtime_conf.get("plugins", []) or [])
        items: list[dict[str, Any]] = []
        for raw in raw_plugins:
            if isinstance(raw, str):
                import_path = raw
                enabled = True
            elif isinstance(raw, dict):
                import_path = str(raw.get("path", "") or raw.get("import_path", "") or "")
                enabled = bool(raw.get("enabled", True))
                if not import_path:
                    continue
            else:
                continue

            load_error = self._probe_plugin_import_error(import_path) if enabled else ""
            items.append({
                "path": import_path,
                "enabled": enabled,
                "name": self._plugin_name_from_path(import_path),
                "display_name": self._plugin_display_name_from_path(import_path),
                "loadable": load_error == "",
                "load_error": load_error,
            })
        return items

    async def replace_plugin_configs(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """整批替换 runtime.plugins 配置并热刷新.

        Args:
            items: 新的插件配置列表.

        Returns:
            list[dict[str, Any]]: 热刷新后的插件配置视图.
        """

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
    def _probe_plugin_import_error(import_path: str) -> str:
        """检查一条 plugin import path 当前是否能成功加载.

        Args:
            import_path: 目标插件导入路径.

        Returns:
            str: 成功时返回空字符串, 失败时返回简短错误文本.
        """

        try:
            load_runtime_plugin(RuntimePluginSpec(import_path=import_path))
        except Exception as exc:
            return str(exc)
        return ""

    @staticmethod
    def _plugin_name_from_path(import_path: str) -> str:
        """从导入路径提取插件名.

        Args:
            import_path: 插件导入路径.

        Returns:
            str: 插件名.
        """

        module_path, _, symbol_name = str(import_path).partition(":")
        if symbol_name:
            return symbol_name
        return module_path.rsplit(".", 1)[-1]

    @classmethod
    def _plugin_display_name_from_path(cls, import_path: str) -> str:
        """把插件导入路径整理成更适合人看的名字.

        Args:
            import_path: 插件导入路径.

        Returns:
            str: 适合展示的插件名字.
        """

        raw_name = cls._plugin_name_from_path(import_path)
        normalized = re.sub(r"Plugin$", "", raw_name)
        words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", normalized).strip()
        if words:
            return words
        return raw_name

    def _filesystem_conf(self) -> dict[str, object]:
        """读取 `runtime.filesystem` 配置块.

        Returns:
            dict[str, object]: filesystem 配置.
        """

        runtime_conf = self.config.get("runtime", {})
        return dict(runtime_conf.get("filesystem", {}) or {})

    def _profiles_dir(self) -> Path:
        """返回 filesystem profiles 目录.

        Returns:
            Path: profiles 目录.
        """

        return _resolve_filesystem_path(self.config, self._filesystem_conf(), key="profiles_dir", default="profiles")

    def _prompts_dir(self) -> Path:
        """返回 filesystem prompts 目录.

        Returns:
            Path: prompts 目录.
        """

        return _resolve_filesystem_path(self.config, self._filesystem_conf(), key="prompts_dir", default="prompts")

    def _path_for_prompt_ref(self, prompt_ref: str) -> Path:
        """把 prompt_ref 转成目标文件路径.

        Args:
            prompt_ref: 目标 prompt_ref.

        Returns:
            Path: 目标文件路径.
        """

        relative = prompt_ref.removeprefix("prompt/")
        raw_path = Path(relative)
        if raw_path.suffix:
            return self._prompts_dir() / raw_path
        return self._prompts_dir() / raw_path.with_suffix(".md")

    def _resolve_prompt_path(self, prompt_ref: str) -> Path | None:
        """按 prompt_ref 解析已有 prompt 文件路径.

        Args:
            prompt_ref: 目标 prompt_ref.

        Returns:
            Path | None: 命中的文件路径.
        """

        loader = FileSystemPromptLoader(self._prompts_dir())
        return loader._resolve_prompt_path(prompt_ref)

    def _prompt_ref_from_path(self, path: Path) -> str:
        """把 prompt 文件路径映射回 prompt_ref.

        Args:
            path: prompt 文件路径.

        Returns:
            str: 归一化后的 prompt_ref.
        """

        relative = path.relative_to(self._prompts_dir())
        if relative.name.startswith("index."):
            normalized = relative.parent
        else:
            normalized = relative.with_suffix("")
        return f"prompt/{normalized.as_posix()}".rstrip("/")

    @staticmethod
    def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
        """安全写入 YAML 文件.

        Args:
            path: 目标文件路径.
            payload: 要写入的 YAML 对象.
        """

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
