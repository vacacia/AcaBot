from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from acabot.agent import AgentResponse, ToolCallRecord
from acabot.gateway.napcat import NapCatGateway
from acabot.runtime import (
    ComputerRuntime,
    ComputerRuntimeConfig,
    ModelAgentRuntime,
    Outbox,
    StaticPromptLoader,
    ToolBroker,
)
from acabot.runtime.builtin_tools.message import BuiltinMessageToolSurface

from .e2e_onebot_probe import OneBotProbe
from .test_model_agent_runtime import _context
from .test_outbox import FakeMessageStore, FakeRenderService
from acabot.runtime.render.protocol import RenderResult


@dataclass
class MessageCallingAgent:
    arguments: dict[str, Any]
    response_text: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        request_options=None,
        max_tool_rounds=None,
        tools=None,
        tool_executor=None,
    ) -> AgentResponse:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "model": model,
                "tools": list(tools or []),
                "tool_executor": tool_executor,
            }
        )
        assert tool_executor is not None
        await tool_executor("message", self.arguments)
        return AgentResponse(
            text=self.response_text,
            model_used=model or "",
            tool_calls_made=[
                ToolCallRecord(
                    name="message",
                    arguments=dict(self.arguments),
                    result={"status": "ok"},
                )
            ],
        )


async def _gateway_and_probe():
    gateway = NapCatGateway(host="127.0.0.1", port=0, timeout=1.0)
    await gateway.start()
    port = gateway._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    probe = OneBotProbe(url=f"ws://127.0.0.1:{port}")
    await probe.connect()
    return gateway, probe


async def _run_message_send(
    tmp_path: Path,
    *,
    tool_arguments: dict[str, Any],
    prepare_workspace: callable | None = None,
    render_service: FakeRenderService | None = None,
):
    gateway, probe = await _gateway_and_probe()
    try:
        broker = ToolBroker()
        BuiltinMessageToolSurface().register(broker)
        agent = MessageCallingAgent(arguments=tool_arguments)
        runtime = ModelAgentRuntime(
            agent=agent,
            prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
            tool_runtime_resolver=broker.build_tool_runtime,
        )
        computer_runtime = ComputerRuntime(
            config=ComputerRuntimeConfig(
                root_dir=str(tmp_path / "runtime_data" / "workspaces"),
                host_skills_catalog_root_path=str(tmp_path / "runtime_data" / "skills-catalog"),
            ),
        )
        ctx = _context()
        ctx.agent.enabled_tools = ["message"]
        await computer_runtime.prepare_run_context(ctx)
        if prepare_workspace is not None:
            prepare_workspace(Path(ctx.world_view.workspace_root_host_path))
        result = await runtime.execute(ctx)
        ctx.actions = list(result.actions)
        outbox = Outbox(
            gateway=gateway,
            store=FakeMessageStore(),
            render_service=render_service,
            runtime_root=tmp_path / "runtime_data",
        )
        report = await outbox.dispatch(ctx)
        probe_result = await probe.next_result()
        return report, probe_result
    finally:
        await probe.close()
        await gateway.stop()


@pytest.mark.asyncio
async def test_message_send_local_workspace_image_reaches_onebot_probe(tmp_path: Path) -> None:
    report, probe_result = await _run_message_send(
        tmp_path,
        tool_arguments={"action": "send", "images": ["x_screenshot.png"]},
        prepare_workspace=lambda root: (root / "x_screenshot.png").write_bytes(b"png-bytes"),
    )

    assert report.has_failures is False
    assert probe_result.payload["params"]["message"][0]["type"] == "image"
    assert probe_result.local_file_read_ok is True
    assert probe_result.validation_error == ""
    assert probe_result.captured_file_refs[0] != "/workspace/x_screenshot.png"
    assert "file://" in probe_result.captured_file_refs[0]


@pytest.mark.asyncio
async def test_message_send_remote_image_passthrough_reaches_probe(tmp_path: Path) -> None:
    report, probe_result = await _run_message_send(
        tmp_path,
        tool_arguments={"action": "send", "images": ["https://example.com/cat.png"]},
    )

    assert report.has_failures is False
    assert probe_result.local_file_read_ok is True
    assert probe_result.captured_file_refs == ["https://example.com/cat.png"]
    assert probe_result.payload["params"]["message"][0]["data"]["file"] == "https://example.com/cat.png"


@pytest.mark.asyncio
async def test_message_send_data_url_passthrough_reaches_probe(tmp_path: Path) -> None:
    report, probe_result = await _run_message_send(
        tmp_path,
        tool_arguments={"action": "send", "images": ["data:image/png;base64,abc"]},
    )

    assert report.has_failures is False
    assert probe_result.local_file_read_ok is True
    assert probe_result.captured_file_refs == ["data:image/png;base64,abc"]
    assert probe_result.payload["params"]["message"][0]["data"]["file"] == "data:image/png;base64,abc"


@pytest.mark.asyncio
async def test_message_send_base64_url_passthrough_reaches_probe(tmp_path: Path) -> None:
    report, probe_result = await _run_message_send(
        tmp_path,
        tool_arguments={"action": "send", "images": ["base64://abc123"]},
    )

    assert report.has_failures is False
    assert probe_result.local_file_read_ok is True
    assert probe_result.captured_file_refs == ["base64://abc123"]
    assert probe_result.payload["params"]["message"][0]["data"]["file"] == "base64://abc123"


@pytest.mark.asyncio
async def test_message_send_render_still_reaches_probe(tmp_path: Path) -> None:
    artifact_path = tmp_path / "runtime_data" / "rendered.png"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(b"png")
    render_service = FakeRenderService(
        RenderResult.ok(
            backend_name="playwright",
            artifact_path=artifact_path,
            html="<p>rendered</p>",
        )
    )
    report, probe_result = await _run_message_send(
        tmp_path,
        tool_arguments={"action": "send", "render": "# Title"},
        render_service=render_service,
    )

    assert report.has_failures is False
    assert probe_result.local_file_read_ok is True
    assert probe_result.captured_file_refs
    assert probe_result.payload["params"]["message"][0]["type"] == "image"


@pytest.mark.asyncio
async def test_message_send_invalid_local_path_fails_before_gateway(tmp_path: Path) -> None:
    gateway, probe = await _gateway_and_probe()
    try:
        broker = ToolBroker()
        BuiltinMessageToolSurface().register(broker)
        agent = MessageCallingAgent(arguments={"action": "send", "images": ["/tmp/out.png"]})
        runtime = ModelAgentRuntime(
            agent=agent,
            prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
            tool_runtime_resolver=broker.build_tool_runtime,
        )
        ctx = _context()
        ctx.agent.enabled_tools = ["message"]

        result = await runtime.execute(ctx)

        assert result.actions == []
        assert any(item.get("status") == "failed" for item in result.tool_calls)
        assert gateway._ws is not None
        assert probe.results.empty()
    finally:
        await probe.close()
        await gateway.stop()
