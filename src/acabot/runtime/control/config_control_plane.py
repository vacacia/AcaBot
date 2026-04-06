"""runtime.config_control_plane 提供 WebUI 需要的配置真源读写与热刷新.

当前这个控制面只保留运行时真正还在使用的配置能力:

- session bundles
- prompts
- gateway
- runtime plugins
- session-config 驱动的 reload
"""

from __future__ import annotations

from collections.abc import Callable
import logging
import math
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from acabot.config import Config

from ..bootstrap.config import resolve_runtime_path as _resolve_runtime_path
from ..bootstrap.loaders import (
    BootstrapDefaults,
    build_bootstrap_defaults as _build_bootstrap_defaults,
    build_prompt_loader as _build_runtime_prompt_loader,
    build_prompt_refs as _build_runtime_prompt_refs,
    build_session_bundle_loader as _build_runtime_session_bundle_loader,
)
from ..computer import ComputerPolicy, parse_computer_policy
from ..contracts import ResolvedAgent, SessionBundle
from ..model.model_registry import FileSystemModelRegistryManager
from ..model.model_targets import build_agent_model_targets
from ..plugin_reconciler import PluginReconciler
from ..render import RenderService
from ..render.playwright_backend import (
    DEFAULT_RENDER_DEVICE_SCALE_FACTOR,
    DEFAULT_RENDER_VIEWPORT_WIDTH,
)
from ..router import RuntimeRouter
from ..skills import FileSystemSkillPackageLoader, SkillCatalog
from ..skills.loader import SkillDiscoveryRoot
from ..subagents import FileSystemSubagentPackageLoader, SubagentCatalog
from ..subagents.loader import SubagentDiscoveryRoot
from .prompt_loader import (
    FileSystemPromptLoader,
    ReloadablePromptLoader,
)
from .session_bundle_loader import SessionBundleLoader
from .session_loader import SessionConfigLoader
from .session_runtime import SessionRuntime

DEFAULT_SKILL_CATALOG_DIRS = ["./extensions/skills"]
DEFAULT_SUBAGENT_CATALOG_DIRS = ["./extensions/subagents"]

logger = logging.getLogger("acabot.runtime.control.config_control_plane")

_SESSION_SURFACE_STORAGE_ALIASES: dict[str, dict[str, str]] = {
    "qq_group": {
        "message": "message.plain",
        "message_mention": "message.mention",
        "message_reply": "message.reply_to_bot",
        "poke": "notice.notify",
        "recall": "notice.group_recall",
        "member_join": "notice.group_increase",
        "member_leave": "notice.group_decrease",
        "admin_change": "notice.group_admin",
        "file_upload": "notice.group_upload",
        "mute_change": "notice.group_ban",
        "honor_change": "notice.notify",
        "title_change": "notice.notify",
        "lucky_king": "notice.notify",
    },
    "qq_private": {
        "message": "message.private",
        "poke": "notice.notify",
        "recall": "notice.friend_recall",
    },
}


def _normalize_session_surfaces_for_storage(
    *,
    surfaces: dict[str, Any],
    template_id: str,
) -> dict[str, Any]:
    """把 WebUI / API 传来的公共事件名归一化成 runtime 使用的 surface 键.

    这里承担 session 配置控制面的边界职责：
    - WebUI 仍可继续使用 `message_mention` 这类公共事件名
    - 真正落盘到 `session.yaml` 时统一写成 runtime 能命中的 canonical surface id
    - 如果 payload 同时带了 alias 和 canonical，优先保留 canonical
    """

    alias_map = _SESSION_SURFACE_STORAGE_ALIASES.get(template_id, {})
    normalized: dict[str, Any] = {}
    source_rank: dict[str, int] = {}
    for surface_id, surface_conf in surfaces.items():
        raw_surface_id = str(surface_id or "").strip()
        if not raw_surface_id:
            continue
        canonical_surface_id = alias_map.get(raw_surface_id, raw_surface_id)
        rank = 1 if canonical_surface_id == raw_surface_id else 0
        previous_rank = source_rank.get(canonical_surface_id, -1)
        if previous_rank > rank:
            continue
        normalized[canonical_surface_id] = dict(surface_conf or {})
        source_rank[canonical_surface_id] = rank
    return normalized


def _resolve_render_int(*, key: str, value: object, default: int) -> int:
    """安全解析 int 型 render 配置值, 无效时回退到 default."""

    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        logger.warning(
            "Invalid runtime.render.%s=%r, fallback to default %r",
            key,
            value,
            default,
        )
        return default


def _resolve_render_float(*, key: str, value: object, default: float) -> float:
    """安全解析 float 型 render 配置值, 无效时回退到 default."""

    if value in (None, ""):
        return default
    try:
        resolved = float(value)
    except (TypeError, ValueError, OverflowError):
        logger.warning(
            "Invalid runtime.render.%s=%r, fallback to default %r",
            key,
            value,
            default,
        )
        return default
    if not math.isfinite(resolved):
        logger.warning(
            "Invalid runtime.render.%s=%r, fallback to default %r",
            key,
            value,
            default,
        )
        return default
    return resolved


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


def _normalize_catalog_dir_values(raw_values: object, *, defaults: list[str]) -> list[str]:
    """把配置里的 catalog 根目录收成字符串列表."""

    if raw_values in (None, ""):
        values = list(defaults)
    elif isinstance(raw_values, str):
        values = [raw_values]
    else:
        values = [str(item) for item in list(raw_values or [])]

    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        normalized.append(text)
    return normalized


def _scope_for_catalog_dir(raw_value: str) -> str:
    """按配置写法推断 catalog 根目录 scope."""

    if raw_value.startswith("~"):
        return "user"
    if Path(raw_value).is_absolute():
        return "user"
    return "project"


def _resolve_catalog_dir_path(*, raw: str, base_dir: Path) -> Path:
    """把 catalog 扫描目录解析成宿主机绝对路径."""

    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def _build_session_runtime(config: Config) -> SessionRuntime:
    """按当前配置构造 session runtime.

    Args:
        config: 当前 runtime 配置.

    Returns:
        SessionRuntime: 当前有效的 session-config 决策运行时.
    """

    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    sessions_dir = _resolve_filesystem_path(config, fs_conf, key="sessions_dir", default="sessions")
    return SessionRuntime(SessionConfigLoader(config_root=sessions_dir))


def _default_computer_policy(config: Config) -> ComputerPolicy:
    """读取默认前台 agent 的 computer policy.

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


def _surfaces_to_view(session: Any) -> dict[str, Any]:
    """把 SessionConfig.surfaces 序列化成 WebUI 可消费的字典."""

    result: dict[str, Any] = {}
    for surface_id, surface in (session.surfaces or {}).items():
        entry: dict[str, Any] = {}
        for domain_name in ("routing", "admission", "context", "persistence", "extraction", "computer"):
            domain = getattr(surface, domain_name, None)
            if domain is None:
                continue
            domain_dict: dict[str, Any] = {"default": dict(domain.default)}
            if domain.cases:
                domain_dict["cases"] = [
                    {
                        "case_id": c.case_id,
                        "when": c.when.to_dict() if hasattr(c.when, "to_dict") and c.when else None,
                        "when_ref": c.when_ref,
                        "use": dict(c.use),
                        "priority": c.priority,
                    }
                    for c in domain.cases
                ]
            entry[domain_name] = domain_dict
        result[surface_id] = entry
    return result


class RuntimeConfigControlPlane:
    """面向 WebUI 的 runtime 配置读写与热刷新服务."""

    def __init__(
        self,
        *,
        config: Config,
        router: RuntimeRouter,
        bootstrap_defaults: BootstrapDefaults,
        session_bundle_loader: SessionBundleLoader | None,
        prompt_loader: ReloadablePromptLoader,
        model_registry_manager: FileSystemModelRegistryManager | None = None,
        skill_catalog: SkillCatalog | None = None,
        subagent_catalog: SubagentCatalog | None = None,
        plugin_reconciler: PluginReconciler | None = None,
        render_service: RenderService | None = None,
        tool_broker=None,
        subagent_delegator=None,
        rebind_agent_loader: Callable[[SessionBundleLoader | None], None] | None = None,
    ) -> None:
        """初始化 RuntimeConfigControlPlane.

        Args:
            config: 当前 runtime 配置.
            router: 当前 runtime router.
            bootstrap_defaults: bootstrap 种子默认值.
            session_bundle_loader: session bundle 真源 loader.
            prompt_loader: 可热刷新的 prompt loader.
            skill_catalog: 可选 skill catalog.
            subagent_catalog: 可选 subagent catalog.
            plugin_reconciler: 可选 plugin reconciler.
            render_service: 可选 render service，用于热应用 render 默认值.
            tool_broker: 可选 tool broker.
            subagent_delegator: 可选 subagent delegator.
        """

        self.config = config
        self.router = router
        self.bootstrap_defaults = bootstrap_defaults
        self.session_bundle_loader = session_bundle_loader
        self.prompt_loader = prompt_loader
        self.model_registry_manager = model_registry_manager
        self.skill_catalog = skill_catalog
        self.subagent_catalog = subagent_catalog
        self.plugin_reconciler = plugin_reconciler
        self.render_service = render_service
        self.tool_broker = tool_broker
        self.subagent_delegator = subagent_delegator
        self.rebind_agent_loader = rebind_agent_loader

    async def reload_runtime_configuration(self) -> dict[str, Any]:
        """重新加载 runtime 配置并热更新相关组件.

        Returns:
            dict[str, Any]: 这次热刷新后的摘要.
        """

        self.config.reload_from_file()
        self.bootstrap_defaults = _build_bootstrap_defaults(
            self.config,
            default_computer_policy=_default_computer_policy(self.config),
        )
        if self.subagent_catalog is not None:
            self.subagent_catalog.replace_loader(self._subagent_catalog_loader())
            self.subagent_catalog.reload()
        if self.skill_catalog is not None:
            self.skill_catalog.replace_loader(self._skill_catalog_loader())
            self.skill_catalog.reload()
        self._refresh_session_bundle_loader()
        self.prompt_loader.replace_loader(
            _build_runtime_prompt_loader(
                self.config,
                prompt_refs={self.bootstrap_defaults.prompt_ref},
                subagent_catalog=self.subagent_catalog,
            )
        )
        self._rebind_agent_loader()
        self.router.session_runtime = _build_session_runtime(self.config)

        if self.plugin_reconciler is not None:
            await self.plugin_reconciler.reconcile_all()
        await self._refresh_session_agent_targets()
        return {
            "session_count": len(self.list_sessions()),
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        """列出全部 session 摘要."""

        if self.session_bundle_loader is None:
            return []
        return [self._session_summary_from_bundle(bundle) for bundle in self.session_bundle_loader.list_bundles()]

    def list_session_bundles(self) -> list[dict[str, Any]]:
        """列出全部完整 session bundle 视图."""

        if self.session_bundle_loader is None:
            return []
        return [self._bundle_to_view(bundle) for bundle in self.session_bundle_loader.list_bundles()]

    def get_session_bundle(self, session_id: str) -> dict[str, Any] | None:
        """读取单个 session bundle."""

        if self.session_bundle_loader is None:
            return None
        try:
            bundle = self.session_bundle_loader.load_by_session_id(session_id)
        except FileNotFoundError:
            return None
        return self._bundle_to_view(bundle)

    def find_session_agent(self, agent_id: str) -> ResolvedAgent | None:
        """按 agent_id 查找当前已配置的 session-owned agent."""

        normalized = str(agent_id or "").strip()
        if not normalized:
            return None
        if self.session_bundle_loader is not None:
            for bundle in self.session_bundle_loader.list_bundles():
                if bundle.frontstage_agent.agent_id == normalized:
                    return ResolvedAgent.from_session_agent(bundle.frontstage_agent)
        return None

    async def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        """创建一份新的 session bundle."""

        if self.session_bundle_loader is None:
            raise RuntimeError("session bundle storage is unavailable")
        session_id = str(payload.get("session_id", "") or "").strip()
        if not session_id:
            raise ValueError("session_id is required")
        if "frontstage_agent_id" in payload or "agent_id" in payload:
            raise ValueError("frontstage_agent_id and agent_id are internal readonly fields")
        session_dir = self.session_bundle_loader.session_dir_for_session_id(session_id)
        if session_dir.exists():
            raise ValueError(f"session already exists: {session_id}")
        agent_id = self._session_agent_id(session_id)
        session_payload = self._build_session_payload(
            session_id=session_id,
            frontstage_agent_id=agent_id,
            title=str(payload.get("title", "") or ""),
            template_id=str(payload.get("template_id", "") or ""),
            selectors=dict(payload.get("selectors", {}) or {}),
            surfaces=dict(payload.get("surfaces", {}) or {}),
        )
        agent_payload = {
            "agent_id": agent_id,
            "prompt_ref": self.bootstrap_defaults.prompt_ref,
            "visible_tools": [],
            "visible_skills": [],
            "visible_subagents": [],
        }
        # 如果 seed prompt 文件不存在，自动创建一份最小默认 prompt
        seed_prompt_ref = agent_payload["prompt_ref"]
        prompt_path = self._resolve_prompt_path(seed_prompt_ref)
        if prompt_path is None or not prompt_path.exists():
            target = self._path_for_prompt_ref(seed_prompt_ref)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("You are a helpful assistant.\n", encoding="utf-8")
        if self.bootstrap_defaults.computer_policy is not None:
            cp = self.bootstrap_defaults.computer_policy
            agent_payload["computer_policy"] = {
                "backend": cp.backend,
                "allow_exec": cp.allow_exec,
                "allow_sessions": cp.allow_sessions,
                "auto_stage_attachments": cp.auto_stage_attachments,
                "network_mode": cp.network_mode,
            }
        self._write_yaml(session_dir / "session.yaml", session_payload)
        self._write_yaml(session_dir / "agent.yaml", agent_payload)
        try:
            self._refresh_session_bundle_loader()
            bundle = self.session_bundle_loader.load_by_session_id(session_id)
            await self._refresh_session_agent_targets()
            return self._bundle_to_view(bundle)
        except Exception:
            for path in (session_dir / "session.yaml", session_dir / "agent.yaml"):
                if path.exists():
                    path.unlink()
            if session_dir.exists() and not any(session_dir.iterdir()):
                session_dir.rmdir()
            raise

    async def update_session(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """更新 `session.yaml`."""

        if self.session_bundle_loader is None:
            raise RuntimeError("session bundle storage is unavailable")
        if "frontstage_agent_id" in payload or "agent_id" in payload:
            raise ValueError("frontstage_agent_id and agent_id are internal readonly fields")
        bundle = self.session_bundle_loader.load_by_session_id(session_id)
        raw = yaml.safe_load(bundle.paths.session_config_path.read_text(encoding="utf-8")) or {}
        previous = dict(raw)
        session_block = dict(raw.get("session", {}) or {})
        if "title" in payload:
            session_block["title"] = str(payload.get("title", "") or "")
        if "template_id" in payload:
            session_block["template"] = str(payload.get("template_id", "") or "")
        if "selectors" in payload:
            raw["selectors"] = dict(payload.get("selectors", {}) or {})
        if "surfaces" in payload:
            raw["surfaces"] = _normalize_session_surfaces_for_storage(
                surfaces=dict(payload.get("surfaces", {}) or {}),
                template_id=str(session_block.get("template", "") or ""),
            )
        if "context" in payload:
            context_payload = dict(payload.get("context", {}) or {})
            context_block = dict(raw.get("context", {}) or {})
            if "strategy" in context_payload:
                strategy = str(context_payload["strategy"] or "truncate")
                context_block["strategy"] = strategy if strategy in ("truncate", "summarize") else "truncate"
            if "preserve_recent" in context_payload:
                context_block["preserve_recent"] = max(1, int(context_payload["preserve_recent"] or 12))
            raw["context"] = context_block
        raw["session"] = session_block
        self._write_yaml(bundle.paths.session_config_path, raw)
        try:
            self._refresh_session_bundle_loader()
            refreshed = self.session_bundle_loader.load_by_session_id(session_id)
            return self._bundle_to_view(refreshed)
        except Exception:
            self._write_yaml(bundle.paths.session_config_path, previous)
            raise

    async def update_session_agent(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """更新 `agent.yaml`."""

        if self.session_bundle_loader is None:
            raise RuntimeError("session bundle storage is unavailable")
        if "frontstage_agent_id" in payload or "agent_id" in payload:
            raise ValueError("frontstage_agent_id and agent_id are internal readonly fields")
        bundle = self.session_bundle_loader.load_by_session_id(session_id)
        raw = yaml.safe_load(bundle.paths.agent_config_path.read_text(encoding="utf-8")) or {}
        previous = dict(raw)
        for key in ("prompt_ref", "visible_tools", "visible_skills", "visible_subagents"):
            if key in payload:
                raw[key] = payload[key]
        if "model_target" in payload:
            model_target = str(payload.get("model_target", "") or "").strip()
            if model_target:
                raw["model_target"] = model_target
            else:
                raw.pop("model_target", None)
        if "computer_policy" in payload:
            raw["computer_policy"] = dict(payload.get("computer_policy", {}) or {})
        self._write_yaml(bundle.paths.agent_config_path, raw)
        try:
            self._refresh_session_bundle_loader()
            refreshed = self.session_bundle_loader.load_by_session_id(session_id)
            return dict(self._bundle_to_view(refreshed)["agent"])
        except Exception:
            self._write_yaml(bundle.paths.agent_config_path, previous)
            raise

    def _refresh_session_bundle_loader(self) -> None:
        """同步 session bundle loader 的根目录和 catalog 快照."""

        tool_names = set()
        if self.tool_broker is not None:
            tool_names = {
                str(item.get("name", "") or "")
                for item in self.tool_broker.list_registered_tools()
                if str(item.get("name", "") or "")
            }
        skill_names = {item.skill_name for item in self.skill_catalog.list_all()} if self.skill_catalog is not None else set()
        subagent_names = (
            {item.subagent_name for item in self.subagent_catalog.list_all()}
            if self.subagent_catalog is not None
            else set()
        )
        model_target_ids = (
            {item.target_id for item in self.model_registry_manager.target_catalog.list_targets()}
            if self.model_registry_manager is not None
            else None
        )
        self.session_bundle_loader = _build_runtime_session_bundle_loader(
            self.config,
            prompt_refs=_build_runtime_prompt_refs(
                self.config,
                prompt_refs={self.bootstrap_defaults.prompt_ref},
                subagent_catalog=self.subagent_catalog,
            ),
            tool_names=tool_names,
            skill_names=skill_names,
            subagent_names=subagent_names,
            model_target_ids=model_target_ids,
        )
        self._rebind_agent_loader()

    async def _refresh_session_agent_targets(self) -> None:
        """按当前 session bundle 刷新 agent model targets."""

        if self.model_registry_manager is None:
            return
        agents: list[ResolvedAgent] = []
        if self.session_bundle_loader is not None:
            seen_agent_ids: set[str] = set()
            for bundle in self.session_bundle_loader.list_bundles():
                resolved = ResolvedAgent.from_session_agent(bundle.frontstage_agent)
                if resolved.agent_id in seen_agent_ids:
                    continue
                agents.append(resolved)
                seen_agent_ids.add(resolved.agent_id)
        self.model_registry_manager.target_catalog.replace_agent_targets(
            build_agent_model_targets(agents)
        )
        reload_snapshot = await self.model_registry_manager.reload()
        if not reload_snapshot.ok:
            raise ValueError(reload_snapshot.error or "model registry reload failed")

    def get_render_config(self) -> dict[str, Any]:
        """读取 render 默认配置视图."""

        runtime_conf = dict(self.config.get("runtime", {}) or {})
        render_conf = dict(runtime_conf.get("render", {}) or {})
        width_value = (
            render_conf["width"]
            if "width" in render_conf
            else DEFAULT_RENDER_VIEWPORT_WIDTH
        )
        device_scale_factor_value = (
            render_conf["device_scale_factor"]
            if "device_scale_factor" in render_conf
            else DEFAULT_RENDER_DEVICE_SCALE_FACTOR
        )
        return {
            "width": max(
                320,
                _resolve_render_int(
                    key="width",
                    value=width_value,
                    default=DEFAULT_RENDER_VIEWPORT_WIDTH,
                ),
            ),
            "device_scale_factor": max(
                1.0,
                _resolve_render_float(
                    key="device_scale_factor",
                    value=device_scale_factor_value,
                    default=DEFAULT_RENDER_DEVICE_SCALE_FACTOR,
                ),
            ),
        }

    async def upsert_render_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        """写回 render 默认配置并尝试热应用到现有 backend."""

        current = self.get_render_config()
        width_value = payload["width"] if "width" in payload else current["width"]
        device_scale_factor_value = (
            payload["device_scale_factor"]
            if "device_scale_factor" in payload
            else current["device_scale_factor"]
        )
        next_conf = {
            "width": max(
                320,
                _resolve_render_int(
                    key="width",
                    value=width_value,
                    default=current["width"],
                ),
            ),
            "device_scale_factor": max(
                1.0,
                _resolve_render_float(
                    key="device_scale_factor",
                    value=device_scale_factor_value,
                    default=current["device_scale_factor"],
                ),
            ),
        }
        data = self.config.to_dict()
        runtime_conf = dict(data.get("runtime", {}) or {})
        runtime_conf["render"] = dict(next_conf)
        data["runtime"] = runtime_conf
        self.config.replace(data)
        self.config.save()

        backend = self.render_service.get_backend("playwright") if self.render_service is not None else None
        update_render_defaults = getattr(backend, "update_render_defaults", None)
        if not callable(update_render_defaults):
            return self.with_apply_result(
                self.get_render_config(),
                apply_status="apply_failed",
                restart_required=True,
                message="已保存，但热应用失败，需要重启",
                technical_detail="playwright render backend does not support hot apply",
            )
        try:
            update_render_defaults(
                viewport_width=next_conf["width"],
                device_scale_factor=next_conf["device_scale_factor"],
            )
        except Exception as exc:
            return self.with_apply_result(
                self.get_render_config(),
                apply_status="apply_failed",
                restart_required=True,
                message="已保存，但热应用失败，需要重启",
                technical_detail=str(exc),
            )
        return self.with_apply_result(
            self.get_render_config(),
            apply_status="applied",
            restart_required=False,
            message="已保存并已生效",
        )

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
        return self.with_apply_result(
            self.get_gateway_config(),
            apply_status="restart_required",
            restart_required=True,
            message="已保存，需要重启后生效",
        )

    def get_long_term_memory_config(self) -> dict[str, Any]:
        """读取长期记忆配置视图.

        Returns:
            dict[str, Any]: 当前长期记忆配置和模型绑定状态.
        """

        runtime_conf = dict(self.config.get("runtime", {}) or {})
        current_conf = dict(runtime_conf.get("long_term_memory", {}) or {})
        normalized = {
            "enabled": bool(current_conf.get("enabled", False)),
            "storage_dir": str(current_conf.get("storage_dir", "long_term_memory/lancedb") or "long_term_memory/lancedb"),
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

    def get_filesystem_scan_config(self) -> dict[str, Any]:
        """读取 filesystem catalog 扫描配置视图."""

        fs_conf = self._filesystem_conf()
        base_dir = Path(str(fs_conf.get("base_dir", ".") or "."))
        if not base_dir.is_absolute():
            base_dir = self.config.resolve_path(base_dir)
        configured_skill_catalog_dirs = self._configured_catalog_dir_values("skill_catalog_dirs")
        configured_subagent_catalog_dirs = self._configured_catalog_dir_values("subagent_catalog_dirs")
        return {
            "base_dir": str(base_dir.resolve()),
            "skill_catalog_dirs": _normalize_catalog_dir_values(
                fs_conf.get("skill_catalog_dirs"),
                defaults=DEFAULT_SKILL_CATALOG_DIRS,
            ),
            "subagent_catalog_dirs": _normalize_catalog_dir_values(
                fs_conf.get("subagent_catalog_dirs"),
                defaults=DEFAULT_SUBAGENT_CATALOG_DIRS,
            ),
            "configured_skill_catalog_dirs": configured_skill_catalog_dirs,
            "configured_subagent_catalog_dirs": configured_subagent_catalog_dirs,
            "default_skill_catalog_dirs": list(DEFAULT_SKILL_CATALOG_DIRS),
            "default_subagent_catalog_dirs": list(DEFAULT_SUBAGENT_CATALOG_DIRS),
            "resolved_skill_catalog_dirs": self._resolved_catalog_dir_views(
                key="skill_catalog_dirs",
                defaults=DEFAULT_SKILL_CATALOG_DIRS,
            ),
            "resolved_subagent_catalog_dirs": self._resolved_catalog_dir_views(
                key="subagent_catalog_dirs",
                defaults=DEFAULT_SUBAGENT_CATALOG_DIRS,
            ),
        }

    async def upsert_filesystem_scan_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        """写回 filesystem catalog 扫描配置并热刷新."""

        data = self.config.to_dict()
        runtime_conf = dict(data.get("runtime", {}) or {})
        fs_conf = dict(runtime_conf.get("filesystem", {}) or {})
        changed = False
        for key in ("skill_catalog_dirs", "subagent_catalog_dirs"):
            if key not in payload:
                continue
            changed = True
            normalized = self._normalize_catalog_dir_update_value(payload.get(key))
            if normalized is None:
                fs_conf.pop(key, None)
            else:
                fs_conf[key] = normalized
        if not changed:
            return self.with_apply_result(
                self.get_filesystem_scan_config(),
                apply_status="applied",
                restart_required=False,
                message="没有检测到配置变更，当前配置已生效",
            )
        runtime_conf["filesystem"] = fs_conf
        data["runtime"] = runtime_conf
        self.config.replace(data)
        self.config.save()
        try:
            await self.reload_runtime_configuration()
        except Exception as exc:
            return self.with_apply_result(
                self.get_filesystem_scan_config(),
                apply_status="apply_failed",
                restart_required=False,
                message="已写入，但应用失败",
                technical_detail=str(exc),
            )
        return self.with_apply_result(
            self.get_filesystem_scan_config(),
            apply_status="applied",
            restart_required=False,
            message="已保存并已生效",
        )

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

    def list_prompts(self) -> list[dict[str, Any]]:
        """列出全部 prompts.

        Returns:
            list[dict[str, Any]]: 当前全部 prompt 配置.
        """

        prompts: list[dict[str, Any]] = []
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
        path = self._resolve_prompt_path(prompt_ref)
        if path is not None and path.exists():
            return {
                "prompt_ref": prompt_ref,
                "content": path.read_text(encoding="utf-8"),
                "source": "filesystem",
            }
        return None

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
        path = self._path_for_prompt_ref(prompt_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
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
        path = self._resolve_prompt_path(prompt_ref)
        if path is None:
            path = self._path_for_prompt_ref(prompt_ref)
        if path.exists():
            path.unlink()
            existed = True
        if existed:
            await self.reload_runtime_configuration()
        return existed

    @staticmethod
    def _session_agent_id(session_id: str) -> str:
        """为一个 session 派生稳定的内部 frontstage agent_id."""

        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("session_id is required")
        SessionConfigLoader._split_session_id(normalized)
        return f"session:{normalized}:frontstage"

    @staticmethod
    def _build_session_payload(
        *,
        session_id: str,
        frontstage_agent_id: str,
        title: str,
        template_id: str,
        selectors: dict[str, Any],
        surfaces: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session": {
                "id": session_id,
            },
            "frontstage": {
                "agent_id": frontstage_agent_id,
            },
        }
        if title:
            payload["session"]["title"] = title
        if template_id:
            payload["session"]["template"] = template_id
        if selectors:
            payload["selectors"] = selectors
        if surfaces:
            payload["surfaces"] = _normalize_session_surfaces_for_storage(
                surfaces=surfaces,
                template_id=template_id,
            )
        return payload

    @staticmethod
    def _build_agent_payload_from_agent(
        *,
        agent_id: str,
        agent: ResolvedAgent,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "agent_id": agent_id,
            "prompt_ref": agent.prompt_ref,
            "visible_tools": list(agent.enabled_tools),
            "visible_skills": list(agent.skills),
            "visible_subagents": list(agent.visible_subagents),
        }
        model_target = str(agent.config.get("model_target", "") or "").strip()
        if model_target:
            payload["model_target"] = model_target
        if agent.computer_policy is not None:
            payload["computer_policy"] = {
                "backend": agent.computer_policy.backend,
                "allow_exec": agent.computer_policy.allow_exec,
                "allow_sessions": agent.computer_policy.allow_sessions,
                "auto_stage_attachments": agent.computer_policy.auto_stage_attachments,
                "network_mode": agent.computer_policy.network_mode,
            }
        return payload

    @staticmethod
    def _session_summary_from_bundle(bundle: SessionBundle) -> dict[str, Any]:
        return {
            "session_id": bundle.session_config.session_id,
            "title": bundle.session_config.title,
            "template_id": bundle.session_config.template_id,
            "frontstage_agent_id": bundle.session_config.frontstage_agent_id,
        }

    @staticmethod
    def _bundle_to_view(bundle: SessionBundle) -> dict[str, Any]:
        agent = bundle.frontstage_agent
        session = bundle.session_config
        payload: dict[str, Any] = {
            "session": {
                "session_id": session.session_id,
                "title": session.title,
                "template_id": session.template_id,
                "frontstage_agent_id": session.frontstage_agent_id,
            },
            "surfaces": _surfaces_to_view(session),
            "context": {
                "strategy": session.context_strategy,
                "preserve_recent": session.context_preserve_recent,
            },
            "agent": {
                "agent_id": agent.agent_id,
                "prompt_ref": agent.prompt_ref,
                "model_target": str(agent.config.get("model_target", "") or ""),
                "visible_tools": list(agent.visible_tools),
                "visible_skills": list(agent.visible_skills),
                "visible_subagents": list(agent.visible_subagents),
            },
            "paths": {
                "session_dir": str(bundle.paths.session_dir),
                "session_config_path": str(bundle.paths.session_config_path),
                "agent_config_path": str(bundle.paths.agent_config_path),
            },
        }
        if agent.computer_policy is not None:
            payload["agent"]["computer_policy"] = {
                "backend": agent.computer_policy.backend,
                "allow_exec": agent.computer_policy.allow_exec,
                "allow_sessions": agent.computer_policy.allow_sessions,
                "auto_stage_attachments": agent.computer_policy.auto_stage_attachments,
                "network_mode": agent.computer_policy.network_mode,
            }
        return payload

    def _rebind_agent_loader(self) -> None:
        """把当前 frontstage agent 真源同步给运行时 loader 闭包."""

        if self.rebind_agent_loader is None:
            return
        self.rebind_agent_loader(self.session_bundle_loader)

    def _filesystem_conf(self) -> dict[str, object]:
        """读取 `runtime.filesystem` 配置块.

        Returns:
            dict[str, object]: filesystem 配置.
        """

        runtime_conf = self.config.get("runtime", {})
        return dict(runtime_conf.get("filesystem", {}) or {})

    def _configured_catalog_dir_values(self, key: str) -> list[str] | None:
        """返回某个 catalog 根目录字段的显式配置值."""

        fs_conf = self._filesystem_conf()
        if key not in fs_conf:
            return None
        raw_values = fs_conf.get(key)
        if raw_values in (None, ""):
            return None
        return _normalize_catalog_dir_values(raw_values, defaults=[])

    def _resolved_catalog_dir_views(
        self,
        *,
        key: str,
        defaults: list[str],
    ) -> list[dict[str, str]]:
        """返回某组 catalog 根目录的解析后视图."""

        fs_conf = self._filesystem_conf()
        base_dir = Path(str(fs_conf.get("base_dir", ".") or "."))
        if not base_dir.is_absolute():
            base_dir = self.config.resolve_path(base_dir)
        resolved: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for raw in _normalize_catalog_dir_values(fs_conf.get(key), defaults=defaults):
            scope = _scope_for_catalog_dir(raw)
            path = _resolve_catalog_dir_path(raw=raw, base_dir=base_dir)
            item = {
                "host_root_path": str(path),
                "scope": scope,
            }
            dedupe_key = (item["host_root_path"], item["scope"])
            if dedupe_key in seen:
                continue
            resolved.append(item)
            seen.add(dedupe_key)
        return resolved

    def _skill_catalog_loader(self) -> FileSystemSkillPackageLoader:
        """按当前配置构造 skill catalog loader."""

        return FileSystemSkillPackageLoader(
            [
                SkillDiscoveryRoot(
                    host_root_path=item["host_root_path"],
                    scope=item["scope"],
                )
                for item in self._resolved_catalog_dir_views(
                    key="skill_catalog_dirs",
                    defaults=DEFAULT_SKILL_CATALOG_DIRS,
                )
            ]
        )

    def _subagent_catalog_loader(self) -> FileSystemSubagentPackageLoader:
        """按当前配置构造 subagent catalog loader."""

        return FileSystemSubagentPackageLoader(
            [
                SubagentDiscoveryRoot(
                    host_root_path=item["host_root_path"],
                    scope=item["scope"],
                )
                for item in self._resolved_catalog_dir_views(
                    key="subagent_catalog_dirs",
                    defaults=DEFAULT_SUBAGENT_CATALOG_DIRS,
                )
            ]
        )

    @staticmethod
    def _normalize_catalog_dir_update_value(raw_value: object) -> list[str] | None:
        """把 PUT 提交的 catalog 根目录值归一化.

        `None` 表示移除字段, 回退到默认目录; 空列表表示显式禁用该扫描源。
        """

        if raw_value is None:
            return None
        return _normalize_catalog_dir_values(raw_value, defaults=[])

    def _prompts_dir(self) -> Path:
        """返回 filesystem prompts 目录.

        Returns:
            Path: prompts 目录.
        """

        return _resolve_filesystem_path(self.config, self._filesystem_conf(), key="prompts_dir", default="prompts")

    def _sessions_dir(self) -> Path:
        """返回 filesystem sessions 目录."""

        return _resolve_filesystem_path(self.config, self._filesystem_conf(), key="sessions_dir", default="sessions")

    def _computer_root_dir(self) -> Path:
        """返回 computer runtime 根目录."""

        runtime_conf = dict(self.config.get("runtime", {}) or {})
        computer_conf = dict(runtime_conf.get("computer", {}) or {})
        return _resolve_runtime_path(
            self.config,
            computer_conf.get("root_dir", "workspaces"),
        )

    def _sticky_notes_dir(self) -> Path:
        """返回 sticky notes 根目录."""

        runtime_conf = dict(self.config.get("runtime", {}) or {})
        return _resolve_runtime_path(
            self.config,
            runtime_conf.get("sticky_notes_dir", "sticky_notes"),
        )

    def _long_term_memory_storage_dir(self) -> Path:
        """返回长期记忆存储目录."""

        runtime_conf = dict(self.config.get("runtime", {}) or {})
        long_term_memory_conf = dict(runtime_conf.get("long_term_memory", {}) or {})
        return _resolve_runtime_path(
            self.config,
            long_term_memory_conf.get("storage_dir", "long_term_memory/lancedb"),
        )

    def _backend_session_path(self) -> Path:
        """返回 backend session binding 文件路径."""

        runtime_conf = dict(self.config.get("runtime", {}) or {})
        backend_conf = dict(runtime_conf.get("backend", {}) or {})
        return _resolve_runtime_path(
            self.config,
            backend_conf.get("session_binding_path", "backend/session.json"),
        )

    def get_runtime_path_overview(self) -> dict[str, Any]:
        """返回系统页需要的运行时路径总览."""

        fs_conf = self._filesystem_conf()
        base_dir = Path(str(fs_conf.get("base_dir", ".") or "."))
        if not base_dir.is_absolute():
            base_dir = self.config.resolve_path(base_dir)
        config_path = Path(str(self.config.path or "config.yaml")).resolve()
        return {
            "config_path": str(config_path),
            "filesystem_base_dir": str(base_dir.resolve()),
            "prompts_dir": str(self._prompts_dir().resolve()),
            "sessions_dir": str(self._sessions_dir().resolve()),
            "computer_root_dir": str(self._computer_root_dir().resolve()),
            "sticky_notes_dir": str(self._sticky_notes_dir().resolve()),
            "long_term_memory_storage_dir": str(self._long_term_memory_storage_dir().resolve()),
            "resolved_skill_catalog_dirs": [
                str(Path(item["host_root_path"]).resolve())
                for item in self._resolved_catalog_dir_views(
                    key="skill_catalog_dirs",
                    defaults=DEFAULT_SKILL_CATALOG_DIRS,
                )
            ],
            "resolved_subagent_catalog_dirs": [
                str(Path(item["host_root_path"]).resolve())
                for item in self._resolved_catalog_dir_views(
                    key="subagent_catalog_dirs",
                    defaults=DEFAULT_SUBAGENT_CATALOG_DIRS,
                )
            ],
            "backend_session_path": str(self._backend_session_path().resolve()),
        }

    @staticmethod
    def with_apply_result(
        data: dict[str, Any],
        *,
        apply_status: str,
        restart_required: bool,
        message: str,
        technical_detail: str | None = None,
    ) -> dict[str, Any]:
        """把配置写入结果整形成统一的 apply-result payload."""

        result = {
            **dict(data),
            "apply_status": apply_status,
            "restart_required": restart_required,
            "message": message,
        }
        if technical_detail:
            result["technical_detail"] = technical_detail
        return result

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
