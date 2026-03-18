import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
import shutil
import subprocess
import textwrap
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from acabot.config import Config
from acabot.runtime import (
    ModelBinding,
    ModelPreset,
    ModelProvider,
    OpenAICompatibleProviderConfig,
    RouteDecision,
    build_runtime_components,
)
from acabot.runtime.control.http_api import RuntimeHttpApiServer
from acabot.runtime.control.log_buffer import InMemoryLogBuffer, LogEntry
from acabot.types import EventSource, MsgSegment, StandardEvent

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


def measure_page_layout(
    *,
    url: str,
    width: int,
    height: int,
    wait_ms: int = 1500,
) -> dict[str, Any]:
    """用 headless Chromium + CDP 读取页面布局指标.

    Args:
        url: 要测量的页面地址.
        width: 浏览器窗口宽度.
        height: 浏览器窗口高度.
        wait_ms: 导航后等待页面稳定的毫秒数.

    Returns:
        一组页面布局指标.
    """

    node_path = shutil.which("node")
    chrome_path = next(
        (
            candidate
            for candidate in (
                "/snap/bin/chromium",
                shutil.which("chromium"),
                shutil.which("chromium-browser"),
                shutil.which("google-chrome"),
            )
            if candidate
        ),
        "",
    )
    if not node_path or not chrome_path:
        pytest.skip("node 或 chromium 不可用，跳过页面布局测量")

    script = textwrap.dedent(
        f"""
        const {{spawn}} = require('node:child_process');
        const fs = require('node:fs');
        const os = require('node:os');
        const path = require('node:path');

        async function wait(ms) {{
          return new Promise((resolve) => setTimeout(resolve, ms));
        }}

        async function main() {{
          const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'acabot-chrome-'));
          const chrome = spawn({json.dumps(chrome_path)}, [
            '--headless',
            '--disable-gpu',
            '--no-sandbox',
            '--window-size={width},{height}',
            '--remote-debugging-port=9230',
            `--user-data-dir=${{userDataDir}}`,
            'about:blank',
          ], {{ stdio: ['ignore', 'pipe', 'pipe'] }});

          try {{
            let version = null;
            for (let index = 0; index < 40; index += 1) {{
              try {{
                const response = await fetch('http://127.0.0.1:9230/json/version');
                if (response.ok) {{
                  version = await response.json();
                  break;
                }}
              }} catch (error) {{
                void error;
              }}
              await wait(200);
            }}
            if (!version) {{
              throw new Error('CDP not ready');
            }}

            const targets = await (await fetch('http://127.0.0.1:9230/json/list')).json();
            const page = targets.find((target) => target.type === 'page');
            if (!page) {{
              throw new Error('No page target');
            }}

            const ws = new WebSocket(version.webSocketDebuggerUrl);
            await new Promise((resolve, reject) => {{
              ws.addEventListener('open', resolve, {{ once: true }});
              ws.addEventListener('error', reject, {{ once: true }});
            }});

            let id = 0;
            function send(method, params = {{}}, sessionId) {{
              const messageId = ++id;
              const payload = sessionId
                ? {{ id: messageId, sessionId, method, params }}
                : {{ id: messageId, method, params }};
              ws.send(JSON.stringify(payload));
              return new Promise((resolve, reject) => {{
                function onMessage(event) {{
                  const data = JSON.parse(event.data);
                  if (data.id !== messageId) {{
                    return;
                  }}
                  ws.removeEventListener('message', onMessage);
                  if (data.error) {{
                    reject(new Error(JSON.stringify(data.error)));
                    return;
                  }}
                  resolve(data.result);
                }}
                ws.addEventListener('message', onMessage);
              }});
            }}

            const attachResult = await send('Target.attachToTarget', {{ targetId: page.id, flatten: true }});
            const sessionId = attachResult.sessionId;

            await send('Page.enable', {{}}, sessionId);
            await send('Runtime.enable', {{}}, sessionId);
            await send('Page.navigate', {{ url: {json.dumps(url)} }}, sessionId);
            await wait({wait_ms});

            const metrics = await send('Runtime.evaluate', {{
              expression: `JSON.stringify({{
                innerWidth: window.innerWidth,
                clientWidth: document.documentElement.clientWidth,
                scrollWidth: document.scrollingElement.scrollWidth,
                bodyMinWidth: getComputedStyle(document.body).minWidth,
                contentGrid: document.querySelector('.content')
                  ? getComputedStyle(document.querySelector('.content')).gridTemplateColumns
                  : '',
                stickyLayout: document.querySelector('.layout')
                  ? getComputedStyle(document.querySelector('.layout')).gridTemplateColumns
                  : ''
              }})`,
              returnByValue: true,
            }}, sessionId);

            console.log(metrics.result.value);
            ws.close();
          }} finally {{
            chrome.kill('SIGKILL');
          }}
        }}

        main().catch((error) => {{
          console.error(error);
          process.exit(1);
        }});
        """
    )
    result = subprocess.run(
        [node_path, "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    output = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not output:
        raise AssertionError("页面布局测量没有返回结果")
    return json.loads(output[-1])


def run_page_script(
    *,
    url: str,
    width: int,
    height: int,
    script: str,
    wait_ms: int = 1500,
) -> dict[str, Any]:
    """在真实页面里执行一段脚本, 并返回 JSON 结果.

    Args:
        url: 要打开的页面地址.
        width: 浏览器窗口宽度.
        height: 浏览器窗口高度.
        script: 在页面里执行的 JS 表达式, 需要返回一个对象.
        wait_ms: 导航后等待页面稳定的毫秒数.

    Returns:
        页面脚本返回的 JSON 对象.
    """

    node_path = shutil.which("node")
    chrome_path = next(
        (
            candidate
            for candidate in (
                "/snap/bin/chromium",
                shutil.which("chromium"),
                shutil.which("chromium-browser"),
                shutil.which("google-chrome"),
            )
            if candidate
        ),
        "",
    )
    if not node_path or not chrome_path:
        pytest.skip("node 或 chromium 不可用，跳过页面交互测试")

    node_script = textwrap.dedent(
        f"""
        const {{spawn}} = require('node:child_process');
        const fs = require('node:fs');
        const os = require('node:os');
        const path = require('node:path');

        async function wait(ms) {{
          return new Promise((resolve) => setTimeout(resolve, ms));
        }}

        async function main() {{
          const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'acabot-chrome-'));
          const chrome = spawn({json.dumps(chrome_path)}, [
            '--headless',
            '--disable-gpu',
            '--no-sandbox',
            '--window-size={width},{height}',
            '--remote-debugging-port=9231',
            `--user-data-dir=${{userDataDir}}`,
            'about:blank',
          ], {{ stdio: ['ignore', 'pipe', 'pipe'] }});

          try {{
            let version = null;
            for (let index = 0; index < 40; index += 1) {{
              try {{
                const response = await fetch('http://127.0.0.1:9231/json/version');
                if (response.ok) {{
                  version = await response.json();
                  break;
                }}
              }} catch (error) {{
                void error;
              }}
              await wait(200);
            }}
            if (!version) {{
              throw new Error('CDP not ready');
            }}

            const targets = await (await fetch('http://127.0.0.1:9231/json/list')).json();
            const page = targets.find((target) => target.type === 'page');
            if (!page) {{
              throw new Error('No page target');
            }}

            const ws = new WebSocket(version.webSocketDebuggerUrl);
            await new Promise((resolve, reject) => {{
              ws.addEventListener('open', resolve, {{ once: true }});
              ws.addEventListener('error', reject, {{ once: true }});
            }});

            let id = 0;
            function send(method, params = {{}}, sessionId) {{
              const messageId = ++id;
              const payload = sessionId
                ? {{ id: messageId, sessionId, method, params }}
                : {{ id: messageId, method, params }};
              ws.send(JSON.stringify(payload));
              return new Promise((resolve, reject) => {{
                function onMessage(event) {{
                  const data = JSON.parse(event.data);
                  if (data.id !== messageId) {{
                    return;
                  }}
                  ws.removeEventListener('message', onMessage);
                  if (data.error) {{
                    reject(new Error(JSON.stringify(data.error)));
                    return;
                  }}
                  resolve(data.result);
                }}
                ws.addEventListener('message', onMessage);
              }});
            }}

            const attachResult = await send('Target.attachToTarget', {{ targetId: page.id, flatten: true }});
            const sessionId = attachResult.sessionId;

            await send('Page.enable', {{}}, sessionId);
            await send('Runtime.enable', {{}}, sessionId);
            await send('Page.navigate', {{ url: {json.dumps(url)} }}, sessionId);
            await wait({wait_ms});

            const result = await send('Runtime.evaluate', {{
              expression: `(async () => {{
                const value = (() => {{ {script} }})();
                return JSON.stringify(await value);
              }})()`,
              returnByValue: true,
              awaitPromise: true,
            }}, sessionId);

            console.log(result.result.value);
            ws.close();
          }} finally {{
            chrome.kill('SIGKILL');
          }}
        }}

        main().catch((error) => {{
          console.error(error);
          process.exit(1);
        }});
        """
    )
    result = subprocess.run(
        [node_path, "-e", node_script],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    output = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not output:
        raise AssertionError("页面交互测试没有返回结果")
    return json.loads(output[-1])


def _session_event(
    *,
    message_type: str,
    user_id: str,
    group_id: str | None = None,
    targets_self: bool = False,
    mentions_self: bool = False,
    reply_targets_self: bool = False,
) -> StandardEvent:
    return StandardEvent(
        event_id="evt-session-1",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type=message_type,
            user_id=user_id,
            group_id=group_id,
        ),
        segments=[MsgSegment(type="text", data={"text": "hello"})],
        raw_message_id="msg-session-1",
        sender_nickname="acacia",
        sender_role="member",
        targets_self=targets_self,
        mentions_self=mentions_self,
        reply_targets_self=reply_targets_self,
    )


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
        log_buffer=InMemoryLogBuffer(),
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
        log_buffer=InMemoryLogBuffer(),
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
        assert any(item["prompt_name"] == "default" for item in catalog["data"]["prompts"])

        logs = await asyncio.to_thread(request_json, base_url, "/api/system/logs")
        assert logs["ok"] is True
        assert "items" in logs["data"]
        assert "next_seq" in logs["data"]
        assert "reset_required" in logs["data"]

        plugins_config = await asyncio.to_thread(request_json, base_url, "/api/system/plugins/config")
        assert plugins_config["ok"] is True
        assert "items" in plugins_config["data"]

        if plugins_config["data"]["items"]:
            first = plugins_config["data"]["items"][0]
            assert str(first.get("name", "")).strip() != ""
            assert str(first.get("display_name", "")).strip() != ""
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


async def test_runtime_http_api_server_serves_incremental_logs(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    assert components.control_plane.log_buffer is not None
    components.control_plane.log_buffer.append(
        LogEntry(timestamp=1.0, level="INFO", logger="acabot.test", message="first")
    )
    components.control_plane.log_buffer.append(
        LogEntry(timestamp=2.0, level="INFO", logger="acabot.test", message="second")
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"

        snapshot = await asyncio.to_thread(request_json, base_url, "/api/system/logs?limit=10")
        assert snapshot["ok"] is True
        assert snapshot["data"]["reset_required"] is False
        assert snapshot["data"]["next_seq"] == 2
        assert [item["message"] for item in snapshot["data"]["items"]] == ["first", "second"]

        components.control_plane.log_buffer.append(
            LogEntry(timestamp=3.0, level="ERROR", logger="acabot.test", message="third")
        )
        delta = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/system/logs?after_seq=2&limit=10",
        )
        assert delta["ok"] is True
        assert delta["data"]["reset_required"] is False
        assert delta["data"]["next_seq"] == 3
        assert [item["message"] for item in delta["data"]["items"]] == ["third"]
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

        identity_file = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/soul/file?name=identity.md",
        )
        assert identity_file["ok"] is True
        assert "我是谁" in str(identity_file["data"]["content"])

        task_file = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/soul/file?name=task.md",
        )
        assert task_file["ok"] is True
        assert "正在做" in str(task_file["data"]["content"])

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


async def test_runtime_http_api_server_plugin_configs_include_display_names(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
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
  plugins:
    - path: "acabot.runtime.plugins.ops_control:OpsControlPlugin"
      enabled: true
  webui:
    enabled: true
    host: "127.0.0.1"
    port: 0
""".strip(),
        encoding="utf-8",
    )
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

        plugins_config = await asyncio.to_thread(request_json, base_url, "/api/system/plugins/config")
        assert plugins_config["ok"] is True
        first = plugins_config["data"]["items"][0]
        assert first["name"] == "OpsControlPlugin"
        assert first["display_name"] == "Ops Control"
    finally:
        await server.stop()


async def test_runtime_http_api_server_persists_model_provider_name(tmp_path: Path) -> None:
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

        saved = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/models/providers/openai-main",
            method="PUT",
            payload={
                "name": "OpenAI 主线路",
                "kind": "openai_compatible",
                "base_url": "https://llm.example.com/v1",
                "api_key_env": "OPENAI_API_KEY",
            },
        )
        assert saved["ok"] is True
        assert saved["data"]["entity_id"] == "openai-main"

        providers = await asyncio.to_thread(request_json, base_url, "/api/models/providers")
        assert providers["ok"] is True
        provider = next(item for item in providers["data"] if item["provider_id"] == "openai-main")
        assert provider["name"] == "OpenAI 主线路"

        provider_detail = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/models/providers/openai-main",
        )
        assert provider_detail["ok"] is True
        assert provider_detail["data"]["name"] == "OpenAI 主线路"

        catalog = await asyncio.to_thread(request_json, base_url, "/api/ui/catalog")
        assert catalog["ok"] is True
        catalog_provider = next(
            item for item in catalog["data"]["model_providers"] if item["provider_id"] == "openai-main"
        )
        assert catalog_provider["name"] == "OpenAI 主线路"
    finally:
        await server.stop()


async def test_runtime_http_api_server_serves_product_shaped_bot_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await components.control_plane.upsert_profile(
        {
            "agent_id": "aca",
            "name": "Aca",
            "prompt_ref": "prompt/default",
            "default_model": "legacy-model",
            "admin_actor_ids": ["qq:private:123456"],
            "enabled_tools": ["read"],
            "skill_assignments": [{"skill_name": "sample_configured_skill"}],
        }
    )
    await components.control_plane.upsert_prompt(
        prompt_ref="prompt/friendlier",
        content="你是更亲切的 Aca。",
    )
    await components.control_plane.upsert_model_provider(
        ModelProvider(
            provider_id="openai-main",
            kind="openai_compatible",
            config=OpenAICompatibleProviderConfig(
                base_url="https://llm.example.com/v1",
                api_key_env="OPENAI_API_KEY",
            ),
        )
    )
    await components.control_plane.upsert_model_preset(
        ModelPreset(
            preset_id="main-a",
            provider_id="openai-main",
            model="gpt-main-a",
            context_window=128000,
            supports_tools=True,
        )
    )
    await components.control_plane.upsert_model_preset(
        ModelPreset(
            preset_id="main-b",
            provider_id="openai-main",
            model="gpt-main-b",
            context_window=256000,
            supports_tools=True,
        )
    )
    await components.control_plane.upsert_model_preset(
        ModelPreset(
            preset_id="summary-a",
            provider_id="openai-main",
            model="gpt-summary-a",
            context_window=64000,
            supports_tools=False,
        )
    )
    await components.control_plane.upsert_model_preset(
        ModelPreset(
            preset_id="summary-b",
            provider_id="openai-main",
            model="gpt-summary-b",
            context_window=64000,
            supports_tools=False,
        )
    )
    await components.control_plane.upsert_model_binding(
        ModelBinding(
            binding_id="binding:aca",
            target_type="agent",
            target_id="aca",
            preset_id="main-a",
        )
    )
    await components.control_plane.upsert_model_binding(
        ModelBinding(
            binding_id="binding:summary",
            target_type="system",
            target_id="compactor_summary",
            preset_ids=["summary-a"],
        )
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        inbound_before = await asyncio.to_thread(request_json, base_url, "/api/rules/inbound")
        assert inbound_before["ok"] is True
        assert inbound_before["data"] == []

        bot = await asyncio.to_thread(request_json, base_url, "/api/bot")
        assert bot["ok"] is True
        default_input_event_types = {
            item["event_type"]
            for item in bot["data"]["default_input"]["rules"]
        }
        assert "message_mention" not in default_input_event_types
        assert "message_reply" not in default_input_event_types

        admins = await asyncio.to_thread(request_json, base_url, "/api/admins")
        assert admins["ok"] is True
        assert admins["data"] == {
            "admin_actor_ids": ["qq:private:123456"],
        }

        saved = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/admins",
            method="PUT",
            payload={
                "admin_actor_ids": ["qq:private:123456", "napcat:private:42"],
            },
        )
        assert saved["ok"] is True
        assert saved["data"] == {
            "admin_actor_ids": ["qq:private:123456", "napcat:private:42"],
        }

        profile = await components.control_plane.get_profile("aca")
        assert profile is not None
        assert profile["admin_actor_ids"] == ["qq:private:123456", "napcat:private:42"]
        assert profile["name"] == "Aca"
        assert profile["prompt_ref"] == "prompt/default"
        assert profile["default_model"] == "legacy-model"
        assert "summary_model_preset_id" not in profile
        assert profile["enabled_tools"] == ["read"]
        assert profile["skill_assignments"] == [{"skill_name": "sample_configured_skill"}]

        backend_status = await asyncio.to_thread(request_json, base_url, "/api/backend/status")
        assert backend_status["ok"] is True
        assert backend_status["data"]["admin_actor_ids"] == ["napcat:private:42", "qq:private:123456"]

        inbound_after = await asyncio.to_thread(request_json, base_url, "/api/rules/inbound")
        assert inbound_after["ok"] is True
        assert inbound_after["data"] == []

        bindings = await components.control_plane.list_model_bindings()
        main_binding = next(item for item in bindings if item.target_type == "agent" and item.target_id == "aca")
        summary_binding = next(
            item
            for item in bindings
            if item.target_type == "system" and item.target_id == "compactor_summary"
        )
        assert main_binding.preset_id == "main-a"
        assert summary_binding.preset_ids == ["summary-a"]
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
            "computer": {
                "backend": "host",
                "read_only": True,
                "allow_write": False,
                "allow_exec": False,
                "allow_sessions": False,
                "auto_stage_attachments": False,
                "network_mode": "disabled",
            },
            "context_management": {"strategy": "summarize"},
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
        assert session_item["channel_template_id"] == "qq_group"
        assert session_item["ai"]["prompt_ref"] == "prompt/session-qa"
        assert session_item["ai"]["summary_model_preset_id"] == "summary-preset"
        assert session_item["ai"]["context_management"]["strategy"] == "summarize"
        assert session_item["ai"]["enabled_tools"] == ["read", "write"]
        assert session_item["ai"]["skills"] == ["sample_configured_skill"]
        message_rules = {
            item["event_type"]: item
            for item in session_item["message_response"]["rules"]
        }
        assert {"message", "message_mention", "message_reply"} <= set(message_rules)
        message_rule = message_rules["message"]
        mention_rule = message_rules["message_mention"]
        reply_rule = message_rules["message_reply"]
        assert message_rule["enabled"] is True
        assert message_rule["run_mode"] == "respond"
        assert message_rule["persist_event"] is True
        assert message_rule["memory_scopes"] == ["user", "channel"]
        assert mention_rule["run_mode"] == "respond"
        assert reply_rule["run_mode"] == "respond"
        assert "tags" not in message_rule
        assert session_item["other"] == {}
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
                "channel_template_id": "qq_group",
                "ai": {
                    "prompt_ref": "prompt/session-qa",
                    "model_preset_id": "gpt-4.1",
                    "summary_model_preset_id": "summary-preset",
                    "context_management": {"strategy": "truncate"},
                    "enabled_tools": ["read"],
                    "skills": ["sample_configured_skill"],
                },
                "message_response": {
                    "rules": [
                        {
                            "event_type": "message",
                            "enabled": False,
                            "run_mode": "respond",
                            "persist_event": False,
                            "memory_scopes": [],
                        },
                        {
                            "event_type": "message_mention",
                            "enabled": True,
                            "run_mode": "record_only",
                            "persist_event": False,
                            "memory_scopes": ["channel"],
                        },
                        {
                            "event_type": "message_reply",
                            "enabled": True,
                            "run_mode": "respond",
                            "persist_event": True,
                            "memory_scopes": ["user"],
                        }
                    ]
                },
                "other": {},
            },
        )
        assert saved["ok"] is True
        assert saved["data"]["display_name"] == "招聘群 2026"
        assert saved["data"]["channel_template_id"] == "qq_group"
        assert saved["data"]["ai"]["context_management"]["strategy"] == "truncate"
        assert saved["data"]["ai"]["enabled_tools"] == ["read"]
        saved_rules = {
            item["event_type"]: item
            for item in saved["data"]["message_response"]["rules"]
        }
        assert saved_rules["message"]["enabled"] is False
        assert saved_rules["message"]["run_mode"] == "respond"
        assert saved_rules["message_mention"]["run_mode"] == "record_only"
        assert saved_rules["message_mention"]["persist_event"] is False
        assert saved_rules["message_mention"]["memory_scopes"] == ["channel"]
        assert saved_rules["message_reply"]["run_mode"] == "respond"
        assert saved_rules["message_reply"]["persist_event"] is True
        assert saved_rules["message_reply"]["memory_scopes"] == ["user"]
        assert "tags" not in saved_rules["message_mention"]
        assert saved["data"]["other"] == {}

        profile_after_save = await components.control_plane.get_profile("session_qq_group_42")
        assert profile_after_save is not None
        assert profile_after_save["computer"] == {
            "backend": "host",
            "read_only": True,
            "allow_write": False,
            "allow_exec": False,
            "allow_sessions": False,
            "auto_stage_attachments": False,
            "network_mode": "disabled",
        }

        inbound_rules = await asyncio.to_thread(request_json, base_url, "/api/rules/inbound")
        message_inbound_rules = [
            item
            for item in inbound_rules["data"]
            if item["match"].get("channel_scope") == "qq:group:42"
            and item["match"].get("event_type") == "message"
        ]
        assert len(message_inbound_rules) == 3
        assert any(
            item["run_mode"] == "silent_drop"
            and item["match"].get("mentions_self") is None
            and item["match"].get("reply_targets_self") is None
            for item in message_inbound_rules
        )
        assert any(
            item["run_mode"] == "record_only"
            and item["match"].get("mentions_self") is True
            for item in message_inbound_rules
        )
        assert any(
            item["run_mode"] == "respond"
            and item["match"].get("reply_targets_self") is True
            for item in message_inbound_rules
        )

        event_policies = await asyncio.to_thread(request_json, base_url, "/api/rules/event-policies")
        message_policies = [
            item
            for item in event_policies["data"]
            if item["match"].get("channel_scope") == "qq:group:42"
            and item["match"].get("event_type") == "message"
        ]
        assert len(message_policies) == 3
        assert any(
            item["persist_event"] is False
            and item["memory_scopes"] == ["channel"]
            and item["match"].get("mentions_self") is True
            for item in message_policies
        )
        assert any(
            item["persist_event"] is True
            and item["memory_scopes"] == ["user"]
            and item["match"].get("reply_targets_self") is True
            for item in message_policies
        )

        ambient_group = await components.router.route(
            _session_event(message_type="group", user_id="10001", group_id="42")
        )
        assert ambient_group.run_mode == "silent_drop"

        mentioned_group = await components.router.route(
            _session_event(
                message_type="group",
                user_id="10001",
                group_id="42",
                targets_self=True,
                mentions_self=True,
            )
        )
        assert mentioned_group.run_mode == "record_only"
        assert mentioned_group.metadata["event_memory_scopes"] == ["channel"]

        replied_group = await components.router.route(
            _session_event(
                message_type="group",
                user_id="10001",
                group_id="42",
                targets_self=True,
                reply_targets_self=True,
            )
        )
        assert replied_group.run_mode == "respond"
        assert replied_group.metadata["event_memory_scopes"] == ["user"]

        private_saved = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/sessions/qq%3Auser%3A10001",
            method="PUT",
            payload={
                "display_name": "管理员私聊",
                "channel_scope": "qq:user:10001",
                "channel_template_id": "qq_private",
                "ai": {
                    "prompt_ref": "",
                    "model_preset_id": "",
                    "summary_model_preset_id": "",
                    "context_management": {"strategy": ""},
                    "enabled_tools": [],
                    "skills": [],
                },
                "message_response": {
                    "rules": [
                        {
                            "event_type": "message",
                            "enabled": True,
                            "run_mode": "respond",
                            "persist_event": True,
                            "memory_scopes": [],
                        }
                    ]
                },
                "other": {},
            },
        )
        assert private_saved["ok"] is True
        assert private_saved["data"]["channel_template_id"] == "qq_private"
        assert private_saved["data"]["ai"]["context_management"]["strategy"] == ""
        private_event_types = {
            item["event_type"]
            for item in private_saved["data"]["message_response"]["rules"]
        }
        assert "member_join" not in private_event_types
        assert "member_leave" not in private_event_types
        private_message_rule = next(
            item
            for item in private_saved["data"]["message_response"]["rules"]
            if item["event_type"] == "message"
        )
        assert "message_mention" not in private_event_types
        assert "message_reply" not in private_event_types
    finally:
        await server.stop()


async def test_runtime_http_api_server_blocks_deleting_prompt_that_is_still_referenced(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await components.control_plane.upsert_prompt(
        prompt_ref="prompt/in-use",
        content="still referenced",
    )
    await components.control_plane.upsert_profile(
        {
            "agent_id": "worker",
            "name": "Worker",
            "prompt_ref": "prompt/in-use",
            "default_model": "worker-model",
        }
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        status, payload = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/prompt?prompt_ref=prompt%2Fin-use",
            method="DELETE",
        )

        assert status == 400
        assert payload["ok"] is False
        assert "worker" in payload["error"]

        prompt = await components.control_plane.get_prompt("prompt/in-use")
        assert prompt is not None
        assert prompt["prompt_ref"] == "prompt/in-use"
    finally:
        await server.stop()


def test_webui_shell_is_vite_bundle_entry() -> None:
    html = Path("src/acabot/webui/index.html").read_text(encoding="utf-8")

    assert "<div id=\"app\"></div>" in html
    assert "data-view=\"sessions\"" not in html
    assert "<script type=\"module\"" in html


async def test_memory_page_does_not_overflow_on_narrow_width(tmp_path: Path) -> None:
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
        await asyncio.to_thread(
            request_json,
            base_url,
            "/api/memory/sticky-notes/item",
            method="POST",
            payload={
                "scope": "channel",
                "scope_key": "qq:group:42",
                "key": "test-note",
            },
        )

        metrics = await asyncio.to_thread(
            measure_page_layout,
            url=f"{base_url}/config/memory",
            width=390,
            height=844,
        )

        assert metrics["bodyMinWidth"] != "1200px"
        assert metrics["scrollWidth"] <= metrics["clientWidth"] + 1
    finally:
        await server.stop()


async def test_memory_page_shows_validation_when_creating_note_without_scope_key(tmp_path: Path) -> None:
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
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/config/memory",
            width=1440,
            height=1000,
            script="""
              const noteInput = document.querySelector('.new-note input');
              const createButton = document.querySelector('.new-note button');
              noteInput.value = 'qq:user:1733064202';
              noteInput.dispatchEvent(new Event('input', { bubbles: true }));
              createButton.click();
              return new Promise((resolve) => {
                setTimeout(() => {
                  resolve({
                    errorText: document.querySelector('.error')?.textContent?.trim() || '',
                    emptyText: document.querySelector('.empty')?.textContent?.trim() || '',
                  });
                }, 300);
              });
            """,
        )

        assert "scope key" in result["errorText"]
    finally:
        await server.stop()


async def test_logs_page_exists_and_exposes_mode_toggle(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    components.control_plane.log_buffer.append(
        LogEntry(timestamp=1.0, level="INFO", logger="acabot.test", message="hello logs")
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/logs",
            width=1440,
            height=1000,
            script="""
              return {
                title: document.querySelector('h1')?.textContent?.trim() || '',
                bodyText: document.body.textContent || '',
              };
            """,
        )

        assert "日志" in result["title"]
        assert "紧凑" in result["bodyText"]
    finally:
        await server.stop()
