"""builtin refresh/install tool surface."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from acabot.agent import ToolSpec

from ..control.extension_refresh import ExtensionRefreshService
from ..tool_broker import ToolBroker, ToolExecutionContext, ToolResult

BUILTIN_EXTENSIONS_TOOL_SOURCE = "builtin:extensions"


class BuiltinExtensionsToolSurface:
    """向模型暴露受限的扩展维护入口。"""

    def __init__(
        self,
        *,
        refresh_service_getter: Callable[[], ExtensionRefreshService | None] | None,
        admin_actor_ids_getter: Callable[[], set[str]] | None,
    ) -> None:
        self._refresh_service_getter = refresh_service_getter
        self._admin_actor_ids_getter = admin_actor_ids_getter

    def register(self, tool_broker: ToolBroker) -> list[str]:
        tool_broker.unregister_source(BUILTIN_EXTENSIONS_TOOL_SOURCE)
        tool_broker.register_tool(
            self._refresh_tool_spec(),
            self._handle_refresh,
            source=BUILTIN_EXTENSIONS_TOOL_SOURCE,
        )
        tool_broker.register_tool(
            self._install_tool_spec(),
            self._handle_install_skill,
            source=BUILTIN_EXTENSIONS_TOOL_SOURCE,
        )
        return ["refresh_extensions", "install_skill"]

    @staticmethod
    def _refresh_tool_spec() -> ToolSpec:
        return ToolSpec(
            name="refresh_extensions",
            description=(
                "Refresh runtime extension discovery for later runs. "
                "Currently only supports kind=skills. "
                "Use this after host-side manual skill maintenance so later runs can see updated skills."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["skills"],
                        "description": "The extension family to refresh. Only skills is supported.",
                    }
                },
                "required": ["kind"],
            },
        )

    @staticmethod
    def _install_tool_spec() -> ToolSpec:
        return ToolSpec(
            name="install_skill",
            description=(
                "Install a skill directory from /workspace into the real project skill catalog for later runs. "
                "Use this after downloading or generating a skill under /workspace/skills/<name>. "
                "This tool refreshes runtime skill discovery automatically."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source_path": {
                        "type": "string",
                        "description": "Absolute world path to the skill directory, usually /workspace/skills/<name>.",
                    },
                    "target_name": {
                        "type": "string",
                        "description": "Optional final installed skill name. Defaults to the source folder or SKILL frontmatter name.",
                    },
                },
                "required": ["source_path"],
            },
        )

    async def _handle_refresh(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        kind = str(arguments.get("kind", "") or "").strip()
        if kind != "skills":
            raise ValueError(f"unsupported extension refresh kind: {kind!r}")

        session_id = self._require_admin_host_frontstage(ctx)
        service = self._require_service()
        result = await service.refresh_skills(session_id=session_id)
        return ToolResult(
            llm_content=json.dumps(result, ensure_ascii=False),
            raw=result,
        )

    async def _handle_install_skill(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        session_id = self._require_admin_host_frontstage(ctx)
        source_path = str(arguments.get("source_path", "") or "").strip()
        if not source_path:
            raise ValueError("install_skill requires source_path")
        if not source_path.startswith("/workspace/"):
            raise ValueError("install_skill only accepts source_path under /workspace")
        if ctx.world_view is None:
            raise PermissionError("install_skill requires a visible work world")
        resolved = ctx.world_view.resolve(source_path)
        source_dir = Path(resolved.host_path)
        if not source_dir.exists() or not source_dir.is_dir():
            raise FileNotFoundError(f"skill source directory not found: {source_path}")

        service = self._require_service()
        result = await service.install_skill_directory(
            source_dir_path=str(source_dir),
            target_name=str(arguments.get("target_name", "") or "").strip() or None,
            installed_via="builtin-install-skill",
            origin_label=source_path,
        )
        result["session_id"] = session_id
        result["source_path"] = source_path
        return ToolResult(
            llm_content=json.dumps(result, ensure_ascii=False),
            raw=result,
        )

    def _require_admin_host_frontstage(self, ctx: ToolExecutionContext) -> str:
        """统一校验 admin + host + session-owned frontstage 约束。"""

        session_id = str(ctx.metadata.get("channel_scope", "") or "").strip()
        if not session_id:
            raise PermissionError("extension maintenance requires a session-bound frontstage run")
        expected_agent_id = f"session:{session_id}:frontstage"
        if str(ctx.agent_id or "") != expected_agent_id:
            raise PermissionError("extension maintenance requires the session-owned frontstage agent")

        backend_kind = str(ctx.metadata.get("backend_kind", "") or "").strip()
        if backend_kind != "host":
            raise PermissionError("extension maintenance requires host backend")

        admin_actor_ids = set(self._admin_actor_ids_getter() or set()) if self._admin_actor_ids_getter is not None else set()
        if not self._is_bot_admin_actor(str(ctx.actor_id or ""), admin_actor_ids):
            raise PermissionError("extension maintenance requires bot admin")
        return session_id

    def _require_service(self) -> ExtensionRefreshService:
        service = self._refresh_service_getter() if self._refresh_service_getter is not None else None
        if service is None:
            raise RuntimeError("extension refresh service unavailable")
        return service

    @staticmethod
    def _is_bot_admin_actor(actor_id: str, admin_actor_ids: set[str]) -> bool:
        """兼容 `platform:user:id` 与历史 `platform:private:id` 管理员写法。"""

        normalized = str(actor_id or "").strip()
        if not normalized:
            return False
        if normalized in admin_actor_ids:
            return True
        parts = normalized.split(":", 2)
        if len(parts) == 3 and parts[1] == "user":
            return f"{parts[0]}:private:{parts[2]}" in admin_actor_ids
        return False


__all__ = ["BUILTIN_EXTENSIONS_TOOL_SOURCE", "BuiltinExtensionsToolSurface"]
