import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from acabot.config import Config
from acabot.runtime import RouteDecision, build_runtime_components
from acabot.runtime.control.http_api import RuntimeHttpApiServer

from .test_outbox import FakeGateway


@dataclass
class FakeAgentResponse:
    text: str = ""
    attachments: list[Any] = field(default_factory=list)
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls_made: list[Any] = field(default_factory=list)
    model_used: str = ""
    raw: Any = None


class FakeAgent:
    def __init__(self, response: FakeAgentResponse) -> None:
        self.response = response

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
    ) -> FakeAgentResponse:
        _ = (
            system_prompt,
            messages,
            model,
            request_options,
            max_tool_rounds,
            tools,
            tool_executor,
        )
        return self.response


def _write_config(path: Path, *, webui_enabled: bool = False, port: int = 0) -> None:
    path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080

agent:
  default_model: "test-model"

runtime:
  default_agent_id: "aca"
  profiles:
    aca:
      name: "Aca"
      prompt_ref: "prompt/default"
      default_model: "test-model"
  prompts:
    prompt/default: "hello"
  binding_rules:
    - rule_id: "private-default"
      priority: 10
      match:
        channel_scope: "qq:user:10001"
      agent_id: "aca"
  webui:
    enabled: {str(webui_enabled).lower()}
    host: "127.0.0.1"
    port: {port}
""".strip(),
        encoding="utf-8",
    )


async def test_runtime_config_control_plane_upserts_profile_prompt_and_rule(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    profile = await components.control_plane.upsert_profile(
        {
            "agent_id": "worker",
            "name": "Worker",
            "prompt_ref": "prompt/worker",
            "default_model": "worker-model",
            "enabled_tools": ["read"],
            "skill_assignments": [
                {
                    "skill_name": "sample_configured_skill",
                    "delegation_mode": "prefer_delegate",
                    "delegate_agent_id": "aca",
                }
            ],
        }
    )
    assert profile["agent_id"] == "worker"
    loaded = components.profile_loader.load(
        RouteDecision(
            thread_id="thread:1",
            actor_id="actor:1",
            agent_id="worker",
            channel_scope="qq:user:10001",
        )
    )
    assert loaded.agent_id == "worker"
    assert components.subagent_executor_registry.get("worker") is not None

    prompt = await components.control_plane.upsert_prompt(
        prompt_ref="prompt/worker",
        content="you are worker",
    )
    assert prompt["prompt_ref"] == "prompt/worker"
    assert components.prompt_loader.load("prompt/worker") == "you are worker"

    rule = await components.control_plane.upsert_binding_rule(
        {
            "rule_id": "worker-channel",
            "agent_id": "worker",
            "priority": 20,
            "match": {"channel_scope": "qq:group:42"},
        }
    )
    assert rule["rule_id"] == "worker-channel"
    assert components.profile_loader.get_rule("worker-channel") is not None
    assert "worker" in config_path.read_text(encoding="utf-8")


async def test_runtime_http_api_server_serves_status_and_profile_crud(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    def request_json(base_url: str, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{base_url}{path}", data=data, headers=headers, method=method)
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"

        meta = await asyncio.to_thread(request_json, base_url, "/api/meta")
        assert meta["ok"] is True
        assert meta["data"]["storage_mode"] == "inline"

        status = await asyncio.to_thread(request_json, base_url, "/api/status")
        assert status["ok"] is True
        assert "loaded_plugins" in status["data"]

        catalog = await asyncio.to_thread(request_json, base_url, "/api/ui/catalog")
        assert catalog["ok"] is True
        assert "agents" in catalog["data"]
        assert "tools" in catalog["data"]
        assert "options" in catalog["data"]
        assert "event_types" in catalog["data"]["options"]

        put_result = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/profiles/worker",
            method="PUT",
            payload={
                "name": "Worker",
                "prompt_ref": "prompt/worker",
                "default_model": "worker-model",
                "enabled_tools": ["read"],
                "skill_assignments": [],
            },
        )
        assert put_result["ok"] is True
        get_result = await asyncio.to_thread(request_json, base_url, "/api/profiles/worker")
        assert get_result["data"]["agent_id"] == "worker"

        workspaces_result = await asyncio.to_thread(request_json, base_url, "/api/workspaces")
        assert workspaces_result["ok"] is True

        references_result = await asyncio.to_thread(request_json, base_url, "/api/references/spaces")
        assert references_result["ok"] is True
    finally:
        await server.stop()
