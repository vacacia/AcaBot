import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from acabot.config import Config
from acabot.runtime import ModelBinding, RouteDecision, build_runtime_components
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


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def request_json_with_status(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return int(exc.code), json.loads(body)


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


def test_runtime_http_api_server_default_static_dir_points_to_src_acabot_webui() -> None:
    config = Config(
        {
            "runtime": {
                "webui": {
                    "enabled": True,
                }
            }
        },
        path="/tmp/acabot-config.yaml",
    )
    server = RuntimeHttpApiServer(
        config=config,
        control_plane=build_runtime_components(
            config,
            gateway=FakeGateway(),
            agent=FakeAgent(FakeAgentResponse(text="ok")),
        ).control_plane,
    )

    assert server.static_dir == Path("src/acabot/webui").resolve()


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

        backend_status = await asyncio.to_thread(request_json, base_url, "/api/backend/status")
        assert backend_status["ok"] is True
        assert "configured" in backend_status["data"]
        assert backend_status["data"]["configured"] is False
        assert backend_status["data"]["session_path"].endswith(".acabot-runtime/backend/session.json")

        backend_path = await asyncio.to_thread(request_json, base_url, "/api/backend/session-path")
        assert backend_path["ok"] is True
        assert backend_path["data"]["path"].endswith(".acabot-runtime/backend/session.json")

        catalog = await asyncio.to_thread(request_json, base_url, "/api/ui/catalog")
        assert catalog["ok"] is True
        assert "agents" in catalog["data"]
        assert "tools" in catalog["data"]
        assert "options" in catalog["data"]
        assert "event_types" in catalog["data"]["options"]

        logs = await asyncio.to_thread(request_json, base_url, "/api/system/logs")
        assert logs["ok"] is True
        assert "items" in logs["data"]

        plugins_config = await asyncio.to_thread(request_json, base_url, "/api/system/plugins/config")
        assert plugins_config["ok"] is True
        assert "items" in plugins_config["data"]

        if plugins_config["data"]["items"]:
            first = plugins_config["data"]["items"][0]
            toggled = await asyncio.to_thread(
                request_json,
                base_url,
                "/api/system/plugins/config",
                method="PUT",
                payload={
                    "items": [
                        {
                            "path": first["path"],
                            "enabled": False,
                        }
                    ]
                },
            )
            assert toggled["ok"] is True
            assert any(item["path"] == first["path"] and item["enabled"] is False for item in toggled["data"]["items"])

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


async def test_runtime_http_api_server_serves_soul_and_sticky_notes_routes(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"

        soul_files = await asyncio.to_thread(request_json, base_url, "/api/soul/files")
        assert soul_files["ok"] is True
        names = [str(item["name"]) for item in soul_files["data"]["items"]]
        assert "identity.md" in names
        assert "soul.md" in names
        assert "state.yaml" in names
        assert "task.md" in names

        self_alias = await asyncio.to_thread(request_json, base_url, "/api/self/files")
        assert self_alias["ok"] is True
        assert [str(item["name"]) for item in self_alias["data"]["items"]] == names

        created = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/soul/files",
            method="POST",
            payload={"name": "persona.md", "content": "Aca 喜欢直接表达。"},
        )
        assert created["ok"] is True
        assert created["data"]["name"] == "persona.md"

        updated = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/soul/file",
            method="PUT",
            payload={"name": "task.md", "content": "- [ ] 重写 WebUI"},
        )
        assert updated["ok"] is True
        assert "重写 WebUI" in str(updated["data"]["content"])

        status, invalid_yaml = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/soul/file",
            method="PUT",
            payload={"name": "state.yaml", "content": "bad: [yaml"},
        )
        assert status == 400
        assert invalid_yaml["ok"] is False

        created_note = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/memory/sticky-notes/item",
            method="POST",
            payload={"scope": "channel", "scope_key": "qq:group:42", "key": "internship_rule"},
        )
        assert created_note["ok"] is True
        assert created_note["data"]["key"] == "internship_rule"

        put_readonly = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/memory/sticky-notes/readonly",
            method="PUT",
            payload={
                "scope": "channel",
                "scope_key": "qq:group:42",
                "key": "internship_rule",
                "content": "十个月只需要成果鉴定。",
            },
        )
        assert put_readonly["ok"] is True

        put_editable = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/memory/sticky-notes/item",
            method="PUT",
            payload={
                "scope": "channel",
                "scope_key": "qq:group:42",
                "key": "internship_rule",
                "content": "补充：不用额外证明。",
            },
        )
        assert put_editable["ok"] is True

        sticky_item = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/memory/sticky-notes/item?scope=channel&scope_key=qq:group:42&key=internship_rule",
        )
        assert sticky_item["ok"] is True
        assert sticky_item["data"]["readonly"]["content"] == "十个月只需要成果鉴定。"
        assert sticky_item["data"]["editable"]["content"] == "补充：不用额外证明。"

        scopes = await asyncio.to_thread(request_json, base_url, "/api/memory/sticky-notes/scopes")
        assert scopes["ok"] is True
        assert any(
            item["scope"] == "channel" and item["scope_key"] == "qq:group:42"
            for item in scopes["data"]["items"]
        )
    finally:
        await server.stop()


async def test_runtime_http_api_server_serves_product_shaped_sessions(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await components.control_plane.upsert_prompt(
        prompt_ref="prompt/session-qa",
        content="你负责招聘群的说明。",
    )
    await components.control_plane.upsert_profile(
        {
            "agent_id": "session_qq_group_42",
            "name": "招聘会话",
            "prompt_ref": "prompt/session-qa",
            "default_model": "session-model",
            "summary_model_preset_id": "summary-preset",
            "enabled_tools": ["read", "write"],
            "skill_assignments": [
                {
                    "skill_name": "sample_configured_skill",
                    "delegation_mode": "prefer_delegate",
                    "delegate_agent_id": "aca",
                }
            ],
            "metadata": {
                "managed_by": "webui_session",
                "session_key": "qq:group:42",
            },
        }
    )
    await components.control_plane.upsert_model_binding(
        ModelBinding(
            binding_id="session-binding-model",
            target_type="agent",
            target_id="session_qq_group_42",
            preset_id="gpt-4.1",
        )
    )
    await components.control_plane.upsert_binding_rule(
        {
            "rule_id": "session-binding",
            "agent_id": "session_qq_group_42",
            "priority": 100,
            "match": {"channel_scope": "qq:group:42"},
            "metadata": {
                "display_name": "招聘群",
                "managed_by": "webui_session",
                "session_key": "qq:group:42",
                "tags": ["campus", "internship"],
            },
        }
    )
    await components.control_plane.upsert_inbound_rule(
        {
            "rule_id": "session-inbound-message",
            "run_mode": "respond",
            "priority": 100,
            "match": {
                "channel_scope": "qq:group:42",
                "event_type": "message",
            },
            "metadata": {"display_name": "招聘群"},
        }
    )
    await components.control_plane.upsert_event_policy(
        {
            "policy_id": "session-policy-message",
            "priority": 100,
            "match": {
                "channel_scope": "qq:group:42",
                "event_type": "message",
            },
            "persist_event": True,
            "extract_to_memory": True,
            "memory_scopes": ["user", "channel"],
            "tags": ["internship"],
            "metadata": {"display_name": "招聘群"},
        }
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"

        listed = await asyncio.to_thread(request_json, base_url, "/api/sessions")
        assert listed["ok"] is True
        session_item = next(
            item for item in listed["data"]["items"] if item["channel_scope"] == "qq:group:42"
        )
        assert session_item["display_name"] == "招聘群"
        assert session_item["ai"]["prompt_ref"] == "prompt/session-qa"
        assert session_item["ai"]["summary_model_preset_id"] == "summary-preset"
        assert session_item["ai"]["enabled_tools"] == ["read", "write"]
        assert session_item["ai"]["skills"] == ["sample_configured_skill"]
        assert session_item["other"]["tags"] == ["campus", "internship"]

        message_rule = next(
            item for item in session_item["message_response"]["rules"] if item["event_type"] == "message"
        )
        assert message_rule["enabled"] is True
        assert message_rule["run_mode"] == "respond"
        assert message_rule["persist_event"] is True
        assert message_rule["memory_scopes"] == ["user", "channel"]
        assert message_rule["tags"] == ["internship"]
        assert "binding_rule_id" not in session_item
        assert "inbound_rule_id" not in message_rule
        assert "event_policy_id" not in message_rule

        saved = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/sessions/qq%3Agroup%3A42",
            method="PUT",
            payload={
                "display_name": "招聘群 2026",
                "channel_scope": "qq:group:42",
                "ai": {
                    "prompt_ref": "prompt/session-qa",
                    "model_preset_id": "gpt-4.1",
                    "summary_model_preset_id": "summary-preset",
                    "enabled_tools": ["read"],
                    "skills": ["sample_configured_skill"],
                },
                "message_response": {
                    "rules": [
                        {
                            "event_type": "message",
                            "enabled": True,
                            "run_mode": "record_only",
                            "persist_event": False,
                            "memory_scopes": ["channel"],
                            "tags": ["intake"],
                        }
                    ]
                },
                "other": {"tags": ["campus", "2026"]},
            },
        )
        assert saved["ok"] is True
        assert saved["data"]["display_name"] == "招聘群 2026"
        assert saved["data"]["ai"]["enabled_tools"] == ["read"]
        saved_rule = next(
            item for item in saved["data"]["message_response"]["rules"] if item["event_type"] == "message"
        )
        assert saved_rule["run_mode"] == "record_only"
        assert saved_rule["persist_event"] is False
        assert saved_rule["memory_scopes"] == ["channel"]
        assert saved["data"]["other"]["tags"] == ["campus", "2026"]

        inbound_rules = await asyncio.to_thread(request_json, base_url, "/api/rules/inbound")
        message_inbound = next(
            item
            for item in inbound_rules["data"]
            if item["match"].get("channel_scope") == "qq:group:42"
            and item["match"].get("event_type") == "message"
        )
        assert message_inbound["run_mode"] == "record_only"

        event_policies = await asyncio.to_thread(request_json, base_url, "/api/rules/event-policies")
        message_policy = next(
            item
            for item in event_policies["data"]
            if item["match"].get("channel_scope") == "qq:group:42"
            and item["match"].get("event_type") == "message"
        )
        assert message_policy["persist_event"] is False
        assert message_policy["memory_scopes"] == ["channel"]
        assert message_policy["tags"] == ["intake"]
    finally:
        await server.stop()


def test_webui_shell_is_vite_bundle_entry() -> None:
    html = Path("src/acabot/webui/index.html").read_text(encoding="utf-8")

    assert "<div id=\"app\"></div>" in html
    assert "data-view=\"sessions\"" not in html
    assert "<script type=\"module\"" in html
