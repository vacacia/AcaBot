"""ToolBroker 暴露前台 backend bridge tool 的测试."""

from __future__ import annotations

import shutil

import pytest

from acabot.config import Config
from acabot.runtime import ResolvedAgent, BackendBridge, BackendSessionService, ToolBroker, build_runtime_components

from tests.runtime._agent_fakes import FakeAgent, FakeAgentResponse
from tests.runtime.test_outbox import FakeGateway


_has_pi = shutil.which("pi") is not None


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


def _profile(agent_id: str, *, enabled_tools: list[str] | None = None) -> ResolvedAgent:
    return ResolvedAgent(
        agent_id=agent_id,
        name=agent_id,
        prompt_ref="prompt/default",
        enabled_tools=enabled_tools or [],
    )


async def test_tool_broker_exposes_backend_bridge_tool_to_all_agents() -> None:
    broker = ToolBroker(
        backend_bridge=BackendBridge(session=FakeBackendSessionService()),
    )
    from acabot.runtime.plugins.backend_bridge_tool import BackendBridgeToolPlugin
    from acabot.runtime.plugin_protocol import RuntimePluginContext
    from pathlib import Path as _Path
    from tests.runtime.test_outbox import FakeGateway

    plugin = BackendBridgeToolPlugin()
    await plugin.setup(
        RuntimePluginContext(
            plugin_id="backend_bridge_tool",
            plugin_config={},
            data_dir=_Path("/tmp/acabot-test-plugin-data"),
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
            },
        )

    # ask_backend 只对 enabled_tools 包含它的 agent 可见
    visible_with = broker.visible_tools(_profile("aca", enabled_tools=["ask_backend"]))
    visible_without = broker.visible_tools(_profile("worker"))

    assert [tool.name for tool in visible_with] == ["ask_backend"]
    assert [tool.name for tool in visible_without] == []


async def test_backend_bridge_tool_executes_via_broker_real_path() -> None:
    session = FakeBackendSessionService()
    broker = ToolBroker(
        backend_bridge=BackendBridge(session=session),
    )
    from acabot.runtime.plugins.backend_bridge_tool import BackendBridgeToolPlugin
    from acabot.runtime.plugin_protocol import RuntimePluginContext
    from pathlib import Path as _Path
    from tests.runtime.test_outbox import FakeGateway
    from tests.runtime.test_model_agent_runtime import _context

    plugin = BackendBridgeToolPlugin()
    await plugin.setup(
        RuntimePluginContext(
            plugin_id="backend_bridge_tool",
            plugin_config={},
            data_dir=_Path("/tmp/acabot-test-plugin-data"),
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
        },
    )
    ctx = _context()
    # ask_backend 需要在 agent.enabled_tools 中才可执行
    from dataclasses import replace as _replace
    ctx = _replace(ctx, agent=_profile("aca", enabled_tools=["ask_backend"]))
    result = await broker.execute(
        tool_name="ask_backend",
        arguments={"request_kind": "query", "summary": "查询当前配置"},
        ctx=broker._build_execution_context(ctx),
    )

    assert session.calls == [("query", "查询当前配置")]
    assert result.raw["result"] == {"kind": "query", "summary": "查询当前配置"}


async def test_backend_bridge_tool_builds_frontstage_request_from_tool_context() -> None:
    session = FakeBackendSessionService()
    broker = ToolBroker(
        backend_bridge=BackendBridge(session=session),
    )
    from acabot.runtime.plugins.backend_bridge_tool import BackendBridgeToolPlugin
    from acabot.runtime.plugin_protocol import RuntimePluginContext
    from pathlib import Path as _Path
    from tests.runtime.test_outbox import FakeGateway
    from tests.runtime.test_model_agent_runtime import _context

    plugin = BackendBridgeToolPlugin()
    await plugin.setup(
        RuntimePluginContext(
            plugin_id="backend_bridge_tool",
            plugin_config={},
            data_dir=_Path("/tmp/acabot-test-plugin-data"),
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
    assert result.raw["result"] == {"kind": "query", "summary": "查询当前配置"}


@pytest.mark.skipif(not _has_pi, reason="pi binary not available")
async def test_build_runtime_components_enabled_backend_exposes_ask_backend(
    tmp_path,
) -> None:
    config = Config(
        {
            "agent": {
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "runtime_root": str(tmp_path / "runtime_data"),
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
    # 新插件体系不需要 ensure_started

    visible = components.tool_broker.visible_tools(_profile("aca"))

    assert [tool.name for tool in visible] == ["ask_backend"]

    await components.backend_bridge.session.adapter.dispose()


@pytest.mark.skipif(not _has_pi, reason="pi binary not available")
async def test_enabled_runtime_ask_backend_executes_against_real_pi(tmp_path) -> None:
    config = Config(
        {
            "agent": {
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "runtime_root": str(tmp_path / "runtime_data"),
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
    # 新插件体系不需要 ensure_started

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

    assert result.raw["ok"] is True
    assert isinstance(result.raw["result"], dict)
    assert "text" in result.raw["result"]

    await components.backend_bridge.session.adapter.dispose()
