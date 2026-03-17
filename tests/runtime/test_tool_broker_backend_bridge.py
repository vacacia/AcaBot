"""ToolBroker 暴露前台 backend bridge tool 的测试."""

from __future__ import annotations

from acabot.config import Config
from acabot.runtime import AgentProfile, BackendBridge, BackendSessionService, ToolBroker, build_runtime_components
from acabot.runtime.backend.contracts import BackendRequest

from tests.runtime.test_bootstrap import FakeAgent, FakeAgentResponse
from tests.runtime.test_outbox import FakeGateway


class FakeBackendSessionService(BackendSessionService):
    """记录前台 backend bridge 调用的最小 fake session service."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str]] = []

    def is_configured(self) -> bool:
        return True

    async def send_change(self, summary: str) -> object:
        self.calls.append(("change", summary))
        return {"kind": "change", "summary": summary}

    async def fork_query_from_stable_checkpoint(self, summary: str) -> object:
        self.calls.append(("query", summary))
        return {"kind": "query", "summary": summary}


def _profile(agent_id: str) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id,
        name=agent_id,
        prompt_ref="prompt/default",
        default_model="test-model",
        enabled_tools=[],
    )


async def test_tool_broker_exposes_backend_bridge_tool_only_to_default_agent() -> None:
    broker = ToolBroker(
        default_agent_id="aca",
        backend_bridge=BackendBridge(session=FakeBackendSessionService()),
    )
    from acabot.runtime.plugins.backend_bridge_tool import BackendBridgeToolPlugin
    from acabot.runtime.plugin_manager import RuntimePluginContext
    from acabot.config import Config
    from tests.runtime.test_outbox import FakeGateway

    plugin = BackendBridgeToolPlugin()
    await plugin.setup(
        RuntimePluginContext(
            config=Config({}),
            gateway=FakeGateway(),
            tool_broker=broker,
        )
    )
    for registration in plugin.runtime_tools():
        broker.register_tool(
            registration.spec,
            registration.handler,
            source="plugin:backend_bridge_tool",
            metadata={
                "plugin_name": plugin.name,
                "visible_to_default_agent_only": registration.visible_to_default_agent_only,
            },
        )

    default_visible = broker.visible_tools(_profile("aca"))
    worker_visible = broker.visible_tools(_profile("worker"))

    assert [tool.name for tool in default_visible] == ["ask_backend"]
    assert worker_visible == []


async def test_backend_bridge_tool_executes_via_broker_real_path() -> None:
    session = FakeBackendSessionService()
    broker = ToolBroker(
        default_agent_id="aca",
        backend_bridge=BackendBridge(session=session),
    )
    from acabot.runtime.plugins.backend_bridge_tool import BackendBridgeToolPlugin
    from acabot.runtime.plugin_manager import RuntimePluginContext
    from acabot.config import Config
    from tests.runtime.test_outbox import FakeGateway
    from tests.runtime.test_model_agent_runtime import _context

    plugin = BackendBridgeToolPlugin()
    await plugin.setup(
        RuntimePluginContext(
            config=Config({}),
            gateway=FakeGateway(),
            tool_broker=broker,
        )
    )
    registration = plugin.runtime_tools()[0]
    broker.register_tool(
        registration.spec,
        registration.handler,
        source="plugin:backend_bridge_tool",
        metadata={
            "plugin_name": plugin.name,
            "visible_to_default_agent_only": registration.visible_to_default_agent_only,
        },
    )
    ctx = _context()
    result = await broker.execute(
        tool_name="ask_backend",
        arguments={"request_kind": "query", "summary": "查询当前配置"},
        ctx=broker._build_execution_context(ctx),
    )

    assert session.calls == [("query", "查询当前配置")]
    assert result.metadata["backend_request_kind"] == "query"
    assert result.metadata["backend_source_kind"] == "frontstage_internal"
    assert result.raw["result"] == {"kind": "query", "summary": "查询当前配置"}


async def test_backend_bridge_tool_builds_frontstage_request_from_tool_context() -> None:
    session = FakeBackendSessionService()
    broker = ToolBroker(
        default_agent_id="aca",
        backend_bridge=BackendBridge(session=session),
    )
    from acabot.runtime.plugins.backend_bridge_tool import BackendBridgeToolPlugin
    from acabot.runtime.plugin_manager import RuntimePluginContext
    from acabot.config import Config
    from tests.runtime.test_outbox import FakeGateway
    from tests.runtime.test_model_agent_runtime import _context

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

    result = await registration.handler(
        {"request_kind": "query", "summary": "查询当前配置"},
        tool_ctx,
    )

    assert session.calls == [("query", "查询当前配置")]
    assert result.metadata["backend_request_kind"] == "query"
    assert result.metadata["backend_source_kind"] == "frontstage_internal"
    assert result.raw["result"] == {"kind": "query", "summary": "查询当前配置"}


async def test_build_runtime_components_enabled_backend_exposes_ask_backend(
    tmp_path,
) -> None:
    config = Config(
        {
            "agent": {
                "default_model": "fallback-model",
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "runtime_root": str(tmp_path / ".acabot-runtime"),
                "backend": {
                    "enabled": True,
                    "session_binding_path": "backend/session.json",
                    "pi_command": ["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await components.plugin_manager.ensure_started()

    visible = components.tool_broker.visible_tools(_profile("aca"))

    assert [tool.name for tool in visible] == ["ask_backend"]

    await components.backend_bridge.session.adapter.dispose()


async def test_enabled_runtime_ask_backend_executes_against_real_pi(tmp_path) -> None:
    config = Config(
        {
            "agent": {
                "default_model": "fallback-model",
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "runtime_root": str(tmp_path / ".acabot-runtime"),
                "backend": {
                    "enabled": True,
                    "session_binding_path": "backend/session.json",
                    "pi_command": ["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await components.plugin_manager.ensure_started()

    from tests.runtime.test_model_agent_runtime import _context

    ctx = _context()
    result = await components.tool_broker.execute(
        tool_name="ask_backend",
        arguments={
            "request_kind": "change",
            "summary": "Reply with exactly: ENABLED_RUNTIME_TOOL_OK",
        },
        ctx=components.tool_broker._build_execution_context(ctx),
    )

    assert result.metadata["backend_request_kind"] == "change"
    assert "ENABLED_RUNTIME_TOOL_OK" in str(result.raw["result"]["text"])

    await components.backend_bridge.session.adapter.dispose()
