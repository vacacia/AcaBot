"""runtime.plugins.backend_bridge_tool 暴露前台到后台的单一 bridge tool."""

from __future__ import annotations

from typing import Any

from acabot.agent import ToolSpec

from ..backend.bridge import BackendBridge
from ..backend.contracts import BackendRequest, BackendSourceRef
from ..plugin_manager import RuntimePlugin, RuntimePluginContext, RuntimeToolRegistration
from ..tool_broker import ToolExecutionContext, ToolResult


class BackendBridgeToolPlugin(RuntimePlugin):
    """给前台 Aca 暴露 ask_backend 工具的最小插件."""

    name = "backend_bridge_tool"

    def __init__(self) -> None:
        """初始化空的 backend bridge tool 插件状态."""

        self._backend_bridge: BackendBridge | None = None

    async def setup(self, runtime: RuntimePluginContext) -> None:
        """从 tool broker 读取共享的 backend bridge 引用."""

        self._backend_bridge = runtime.tool_broker.backend_bridge

    def runtime_tools(self) -> list[RuntimeToolRegistration]:
        """返回前台 ask_backend 工具定义."""

        return [
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="ask_backend",
                    description=(
                        "Ask the backend maintainer for a query or a small change. "
                        "Only request_kind=query|change is allowed."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "request_kind": {
                                "type": "string",
                                "enum": ["query", "change"],
                                "description": "Backend request kind. Only query or change is allowed.",
                            },
                            "summary": {
                                "type": "string",
                                "description": "A concise summary for the backend maintainer.",
                            },
                        },
                        "required": ["request_kind", "summary"],
                    },
                ),
                handler=self._ask_backend,
                visible_to_default_agent_only=True,
            )
        ]

    async def _ask_backend(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """把前台 ask_backend 工具调用转成一条 BackendRequest."""

        bridge = self._backend_bridge

        request_kind = str(arguments.get("request_kind", "") or "").strip()
        summary = str(arguments.get("summary", "") or "").strip()
        if request_kind not in {"query", "change"}:
            return ToolResult(
                llm_content=(
                    '{"error": "Unsupported backend request_kind: '
                    f'{request_kind or "-"}"' + "}"
                ),
                raw={
                    "ok": False,
                    "reason": "unsupported_request_kind",
                    "request_kind": request_kind,
                },
                metadata={"error": "unsupported_request_kind"},
            )

        if bridge is None:
            return ToolResult(
                llm_content='{"error": "backend bridge unavailable"}',
                raw={"ok": False, "reason": "backend_bridge_unavailable"},
                metadata={"error": "backend bridge unavailable"},
            )

        request = BackendRequest(
            request_id=f"backend:{ctx.metadata.get('event_id', '') or ctx.run_id}",
            source_kind="frontstage_internal",
            request_kind=request_kind,
            source_ref=BackendSourceRef(
                thread_id=ctx.thread_id,
                channel_scope=str(ctx.metadata.get("channel_scope", "") or ""),
                event_id=str(ctx.metadata.get("event_id", "") or ""),
            ),
            summary=summary,
            created_at=int(ctx.metadata.get("event_timestamp", 0) or 0),
        )
        result = await bridge.handle_frontstage_request(request)
        return ToolResult(
            llm_content=str(result),
            raw={
                "ok": True,
                "request_kind": request_kind,
                "summary": summary,
                "result": result,
            },
            metadata={
                "backend_request_kind": request_kind,
                "backend_source_kind": "frontstage_internal",
            },
        )
