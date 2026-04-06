"""builtin refresh tool surface."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from acabot.agent import ToolSpec

from ..control.extension_refresh import ExtensionRefreshService
from ..tool_broker import ToolBroker, ToolExecutionContext, ToolResult

BUILTIN_EXTENSIONS_TOOL_SOURCE = "builtin:extensions"


class BuiltinExtensionsToolSurface:
    """向模型暴露受限的扩展刷新入口。"""

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
            self._tool_spec(),
            self._handle_refresh,
            source=BUILTIN_EXTENSIONS_TOOL_SOURCE,
        )
        return ["refresh_extensions"]

    @staticmethod
    def _tool_spec() -> ToolSpec:
        return ToolSpec(
            name="refresh_extensions",
            description=(
                "Refresh runtime extension discovery for later runs. "
                "Currently only supports kind=skills. "
                "Use this after host-side skill maintenance so later runs can see updated skills."
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

    async def _handle_refresh(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        kind = str(arguments.get("kind", "") or "").strip()
        if kind != "skills":
            raise ValueError(f"unsupported extension refresh kind: {kind!r}")

        session_id = str(ctx.metadata.get("channel_scope", "") or "").strip()
        if not session_id:
            raise PermissionError("refresh_extensions requires a session-bound frontstage run")
        expected_agent_id = f"session:{session_id}:frontstage"
        if str(ctx.agent_id or "") != expected_agent_id:
            raise PermissionError("refresh_extensions requires the session-owned frontstage agent")

        backend_kind = str(ctx.metadata.get("backend_kind", "") or "").strip()
        if backend_kind != "host":
            raise PermissionError("refresh_extensions requires host backend")

        admin_actor_ids = set(self._admin_actor_ids_getter() or set()) if self._admin_actor_ids_getter is not None else set()
        if not self._is_bot_admin_actor(str(ctx.actor_id or ""), admin_actor_ids):
            raise PermissionError("refresh_extensions requires bot admin")

        service = self._refresh_service_getter() if self._refresh_service_getter is not None else None
        if service is None:
            raise RuntimeError("extension refresh service unavailable")
        result = await service.refresh_skills(session_id=session_id)
        return ToolResult(
            llm_content=json.dumps(result, ensure_ascii=False),
            raw=result,
        )

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
