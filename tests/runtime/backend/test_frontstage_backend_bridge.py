"""前台到 backend bridge 的最小契约测试."""

from __future__ import annotations

from acabot.config import Config
from acabot.runtime import ToolBroker
from acabot.runtime.plugins.backend_bridge_tool import BackendBridgeToolPlugin
from acabot.runtime.plugin_protocol import RuntimePluginContext

from tests.runtime.test_model_agent_runtime import _context
from tests.runtime.test_outbox import FakeGateway


async def test_frontstage_backend_bridge_only_supports_query_and_change() -> None:
    """ask_backend 只允许前台发送 query/change 两类请求."""

    broker = ToolBroker()
    plugin = BackendBridgeToolPlugin()
    await plugin.setup(
        RuntimePluginContext(
            config=Config({}),
            gateway=FakeGateway(),
            tool_broker=broker,
        )
    )
    registration = plugin.runtime_tools()[0]
    ctx = _context()
    tool_ctx = broker._build_execution_context(ctx)

    bad_result = await registration.handler(
        {"request_kind": "admin_direct", "summary": "bad"},
        tool_ctx,
    )

    assert bad_result.metadata["error"] == "unsupported_request_kind"
