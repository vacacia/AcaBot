import asyncio
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
import shutil
import socket
import subprocess
import textwrap
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest
import yaml

from acabot.config import Config
from acabot.runtime import (
    AnthropicProviderConfig,
    ModelBinding,
    ModelPreset,
    ModelProvider,
    OneShotSchedule,
    OpenAICompatibleProviderConfig,
    RouteDecision,
    RunStep,
    RuntimeModelRequest,
    build_runtime_components,
)
from acabot.runtime.bootstrap import (
    DEFAULT_RENDER_DEVICE_SCALE_FACTOR,
    DEFAULT_RENDER_VIEWPORT_WIDTH,
)
from acabot.runtime.control.http_api import RuntimeHttpApiServer
from acabot.runtime.control.log_buffer import InMemoryLogBuffer, LogEntry
from acabot.types import ActionType, EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway, NegativeAckGateway


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


async def _seed_model_registry(control_plane: Any) -> None:
    await control_plane.upsert_model_provider(
        ModelProvider(
            provider_id="openai-main",
            name="OpenAI Main",
            kind="openai_compatible",
            config=OpenAICompatibleProviderConfig(
                base_url="https://llm.example.com/v1",
                api_key_env="OPENAI_API_KEY",
            ),
        )
    )
    await control_plane.upsert_model_provider(
        ModelProvider(
            provider_id="anthropic-main",
            name="Anthropic Main",
            kind="anthropic",
            config=AnthropicProviderConfig(
                api_key_env="ANTHROPIC_API_KEY",
                anthropic_version="2023-06-01",
            ),
        )
    )
    for preset in (
        ModelPreset(
            preset_id="aca-main",
            provider_id="openai-main",
            model="gpt-4.1",
            task_kind="chat",
            capabilities=["tool_calling", "reasoning"],
            context_window=128000,
            max_output_tokens=8192,
        ),
        ModelPreset(
            preset_id="aca-fallback",
            provider_id="anthropic-main",
            model="claude-sonnet-4-5",
            task_kind="chat",
            capabilities=["tool_calling", "structured_output"],
            context_window=200000,
            max_output_tokens=8192,
        ),
        ModelPreset(
            preset_id="summary-fast",
            provider_id="openai-main",
            model="gpt-4.1-mini",
            task_kind="chat",
            capabilities=["structured_output"],
            context_window=128000,
            max_output_tokens=4096,
        ),
        ModelPreset(
            preset_id="vision-main",
            provider_id="openai-main",
            model="gpt-4.1",
            task_kind="chat",
            capabilities=["image_input", "tool_calling"],
            context_window=128000,
            max_output_tokens=4096,
        ),
        ModelPreset(
            preset_id="ltm-chat",
            provider_id="anthropic-main",
            model="claude-sonnet-4-5",
            task_kind="chat",
            capabilities=["structured_output"],
            context_window=200000,
            max_output_tokens=4096,
        ),
        ModelPreset(
            preset_id="ltm-embed",
            provider_id="openai-main",
            model="text-embedding-3-large",
            task_kind="embedding",
            context_window=32000,
        ),
    ):
        await control_plane.upsert_model_preset(preset)

    for binding in (
        ModelBinding(
            binding_id="binding:agent:aca",
            target_id="agent:aca",
            preset_ids=["aca-main", "aca-fallback"],
        ),
        ModelBinding(
            binding_id="binding:system:compactor_summary",
            target_id="system:compactor_summary",
            preset_ids=["summary-fast"],
        ),
        ModelBinding(
            binding_id="binding:system:image_caption",
            target_id="system:image_caption",
            preset_ids=["vision-main"],
        ),
        ModelBinding(
            binding_id="binding:system:ltm_extract",
            target_id="system:ltm_extract",
            preset_ids=["ltm-chat", "aca-fallback"],
        ),
        ModelBinding(
            binding_id="binding:system:ltm_query_plan",
            target_id="system:ltm_query_plan",
            preset_ids=["ltm-chat"],
        ),
        ModelBinding(
            binding_id="binding:system:ltm_embed",
            target_id="system:ltm_embed",
            preset_ids=["ltm-embed"],
        ),
    ):
        await control_plane.upsert_model_binding(binding)


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


def request_multipart(
    base_url: str,
    path: str,
    *,
    fields: dict[str, str] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
) -> dict[str, Any]:
    """发送一条 multipart/form-data 请求, 供上传接口测试使用。"""

    boundary = "----AcaBotTestBoundary20260406"
    body = io.BytesIO()
    for key, value in (fields or {}).items():
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body.write(str(value).encode("utf-8"))
        body.write(b"\r\n")
    for key, (filename, content, content_type) in (files or {}).items():
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(
            (
                f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        body.write(content)
        body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode("utf-8"))

    request = Request(
        f"{base_url}{path}",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


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
                "/snap/bin/chromium" if Path("/snap/bin/chromium").exists() else None,
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

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        debug_port = sock.getsockname()[1]

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
            '--remote-debugging-port={debug_port}',
            `--user-data-dir=${{userDataDir}}`,
            'about:blank',
          ], {{ stdio: ['ignore', 'pipe', 'pipe'] }});

          try {{
            let version = null;
            for (let index = 0; index < 40; index += 1) {{
              try {{
                const response = await fetch('http://127.0.0.1:{debug_port}/json/version');
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

            const targets = await (await fetch('http://127.0.0.1:{debug_port}/json/list')).json();
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
    init_script: str = "",
) -> dict[str, Any]:
    """在真实页面里执行一段脚本, 并返回 JSON 结果.

    Args:
        url: 要打开的页面地址.
        width: 浏览器窗口宽度.
        height: 浏览器窗口高度.
        script: 在页面里执行的 JS 表达式, 需要返回一个对象.
        wait_ms: 导航后等待页面稳定的毫秒数.
        init_script: 在页面脚本执行前注入的 JS, 适合预置 localStorage 或 fetch hook.

    Returns:
        页面脚本返回的 JSON 对象.
    """

    node_path = shutil.which("node")
    chrome_path = next(
        (
            candidate
            for candidate in (
                "/snap/bin/chromium" if Path("/snap/bin/chromium").exists() else None,
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

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        debug_port = sock.getsockname()[1]

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
            '--remote-debugging-port={debug_port}',
            `--user-data-dir=${{userDataDir}}`,
            'about:blank',
          ], {{ stdio: ['ignore', 'pipe', 'pipe'] }});

          try {{
            let version = null;
            for (let index = 0; index < 40; index += 1) {{
              try {{
                const response = await fetch('http://127.0.0.1:{debug_port}/json/version');
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

            const targets = await (await fetch('http://127.0.0.1:{debug_port}/json/list')).json();
            const page = targets.find((target) => target.type === 'page');
            if (!page) {{
              throw new Error('No page target');
            }}

            const ws = new WebSocket(page.webSocketDebuggerUrl);
            await new Promise((resolve, reject) => {{
              ws.addEventListener('open', resolve, {{ once: true }});
              ws.addEventListener('error', reject, {{ once: true }});
            }});

            let id = 0;
            function send(method, params = {{}}) {{
              const messageId = ++id;
              ws.send(JSON.stringify({{ id: messageId, method, params }}));
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

            await send('Page.enable', {{}});
            await send('Runtime.enable', {{}});
            if ({json.dumps(bool(init_script))}) {{
              await send('Page.addScriptToEvaluateOnNewDocument', {{
                source: {json.dumps(init_script)},
              }});
            }}
            await send('Page.navigate', {{ url: {json.dumps(url)} }});
            await wait({wait_ms});

            const result = await send('Runtime.evaluate', {{
              expression: `(async () => {{
                const value = (() => {{ {script} }})();
                return JSON.stringify(await value);
              }})()`,
              returnByValue: true,
              awaitPromise: true,
            }});

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


_webui_assets_built = False


def ensure_webui_assets_built() -> None:
    global _webui_assets_built
    if _webui_assets_built:
        return
    if not shutil.which("npm"):
        pytest.skip("npm 不可用，跳过 WebUI 页面 smoke test")
    webui_dir = Path("webui")
    if not (webui_dir / "node_modules").exists():
        subprocess.run(
            ["bash", "-lc", "npm ci"],
            cwd=webui_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=240,
        )
    subprocess.run(
        ["bash", "-lc", "npm run build"],
        cwd=webui_dir,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    _webui_assets_built = True


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


async def _open_test_run(components: Any) -> str:
    run = await components.run_manager.open(
        event=_session_event(message_type="private", user_id="10001"),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="session:qq:user:10001:frontstage",
            channel_scope="qq:user:10001",
        ),
    )
    return run.run_id


def _write_minimal_fs_session(
    base_dir: Path,
    *,
    session_id: str = "qq:user:10001",
    agent_id: str = "aca",
    prompt_ref: str = "prompt/default",
    prompt_text: str = "hello",
) -> None:
    """在 base_dir 下写入最小 session+agent+prompt 文件供 build_runtime_components 使用."""
    parts = session_id.split(":", 2)
    session_dir = base_dir / "sessions" / parts[0] / parts[1] / parts[2]
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.yaml").write_text(
        f"session:\n  id: {session_id}\n  template: qq_user\nfrontstage:\n  agent_id: {agent_id}\nsurfaces:\n  message.private:\n    admission:\n      default:\n        mode: respond\n",
        encoding="utf-8",
    )
    agent_data = {
        "agent_id": agent_id,
        "prompt_ref": prompt_ref,
        "visible_tools": [],
        "visible_skills": [],
        "visible_subagents": [],
    }
    (session_dir / "agent.yaml").write_text(
        yaml.dump(agent_data, default_flow_style=False),
        encoding="utf-8",
    )
    parts = prompt_ref.replace("prompt/", "", 1).split("/")
    prompts_dir = base_dir / "prompts"
    for p in parts[:-1]:
        prompts_dir = prompts_dir / p
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / f"{parts[-1]}.md").write_text(prompt_text, encoding="utf-8")


def _write_config(
    path: Path,
    *,
    webui_enabled: bool = False,
    port: int = 0,
    filesystem_enabled: bool = False,
    base_dir: Path | None = None,
    backend_admin_actor_ids: list[str] | None = None,
    allow_synthetic_events: bool = False,
    write_session: bool = True,
) -> None:
    resolved_base_dir = base_dir or path.parent
    runtime: dict[str, Any] = {
        "filesystem": {
            "base_dir": str(resolved_base_dir),
            "sessions_dir": "sessions",
        },
        "webui": {
            "enabled": bool(webui_enabled),
            "host": "127.0.0.1",
            "port": port,
            "allow_synthetic_events": bool(allow_synthetic_events),
        },
    }
    if backend_admin_actor_ids:
        runtime["backend"] = {
            "admin_actor_ids": list(backend_admin_actor_ids),
        }
    path.write_text(
        yaml.safe_dump(
            {
                "gateway": {
                    "host": "127.0.0.1",
                    "port": 8080,
                },
                "agent": {},
                "runtime": runtime,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    if write_session:
        _write_minimal_fs_session(resolved_base_dir, session_id="qq:user:99999")


def _write_skill_package(root_dir: Path, relative_dir: str, *, name: str, description: str) -> None:
    """写入一份最小可发现的 skill package。"""

    skill_dir = root_dir / relative_dir
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                f"# {name}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_session_bundle(
    root: Path,
    *,
    session_id: str,
    prompt_ref: str = "prompt/default",
    visible_tools: list[str] | None = None,
    visible_skills: list[str] | None = None,
    visible_subagents: list[str] | None = None,
) -> str:
    platform, scope, identifier = session_id.split(":", 2)
    session_dir = root / "sessions" / platform / scope / identifier
    session_dir.mkdir(parents=True, exist_ok=True)
    agent_id = f"session:{session_id}:frontstage"
    (session_dir / "session.yaml").write_text(
        f"""
session:
  id: {session_id}
frontstage:
  agent_id: {agent_id}
""".strip(),
        encoding="utf-8",
    )
    lines = [
        f"agent_id: {agent_id}",
        f"prompt_ref: {prompt_ref}",
    ]
    for key, values in (
        ("visible_tools", visible_tools or []),
        ("visible_skills", visible_skills or []),
        ("visible_subagents", visible_subagents or []),
    ):
        if not values:
            continue
        lines.append(f"{key}:")
        lines.extend(f"  - {value}" for value in values)
    (session_dir / "agent.yaml").write_text("\n".join(lines), encoding="utf-8")
    return agent_id


def _write_subagent(
    tmp_path: Path,
    *,
    name: str,
    description: str,
    root_dir: Path | None = None,
) -> None:
    subagent_root = root_dir or (tmp_path / ".agents" / "subagents")
    subagent_dir = subagent_root / name
    subagent_dir.mkdir(parents=True, exist_ok=True)
    (subagent_dir / "SUBAGENT.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "tools:",
                "  - read",
                "---",
                f"You are {name}.",
                "",
            ]
        ),
        encoding="utf-8",
    )


async def test_runtime_reload_updates_default_agent_dependent_state(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_minimal_fs_session(tmp_path, prompt_ref="prompt/aca", prompt_text="hello aca")
    (tmp_path / "prompts" / "worker.md").write_text("hello worker", encoding="utf-8")
    config_path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  filesystem:
    base_dir: "{tmp_path}"
  backend:
    admin_actor_ids:
      - "qq:private:1"
""".strip(),
        encoding="utf-8",
    )
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    assert components.app.backend_admin_actor_ids == {"qq:private:1"}
    assert components.app.router.session_runtime.build_facts(
        _session_event(message_type="private", user_id="1")
    ).is_bot_admin is True

    config_path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  filesystem:
    base_dir: "{tmp_path}"
  backend:
    admin_actor_ids:
      - "qq:private:2"
""".strip(),
        encoding="utf-8",
    )

    result = await components.control_plane.reload_runtime_configuration()

    assert "session_count" in result
    assert components.app.backend_admin_actor_ids == {"qq:private:2"}
    assert components.app.router.session_runtime.build_facts(
        _session_event(message_type="private", user_id="1")
    ).is_bot_admin is False
    assert components.app.router.session_runtime.build_facts(
        _session_event(message_type="private", user_id="2")
    ).is_bot_admin is True


async def test_runtime_reload_rebinds_agent_loader_from_filesystem(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, base_dir=tmp_path)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    _write_session_bundle(tmp_path, session_id="qq:user:10001")

    fs_agent = components.agent_loader(
        RouteDecision(
            thread_id="thread:1",
            actor_id="actor:1",
            agent_id="ignored",
            channel_scope="qq:user:10001",
        )
    )
    assert fs_agent.agent_id == "session:qq:user:10001:frontstage"

    await components.control_plane.reload_runtime_configuration()
    fs_agent_after = components.agent_loader(
        RouteDecision(
            thread_id="thread:1",
            actor_id="actor:1",
            agent_id="ignored",
            channel_scope="qq:user:10001",
        )
    )
    assert fs_agent_after.agent_id == "session:qq:user:10001:frontstage"


async def test_runtime_config_control_plane_creates_session_and_updates_agent_prompt(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, base_dir=tmp_path)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    await _seed_model_registry(components.control_plane)
    await components.control_plane.upsert_prompt(
        prompt_ref="prompt/worker",
        content="you are worker",
    )

    created = await components.control_plane.create_session(
        {"session_id": "qq:user:20001", "title": "Worker Session"}
    )
    agent = await components.control_plane.update_session_agent(
        "qq:user:20001",
        {
            "prompt_ref": "prompt/worker",
            "visible_tools": ["read"],
        },
    )
    assert created["session"]["session_id"] == "qq:user:20001"
    assert agent["prompt_ref"] == "prompt/worker"
    loaded = components.agent_loader(
        RouteDecision(
            thread_id="thread:1",
            actor_id="actor:1",
            agent_id=created["session"]["frontstage_agent_id"],
            channel_scope="qq:user:20001",
        )
    )
    assert loaded.agent_id == created["agent"]["agent_id"]
    assert components.subagent_catalog.get("worker") is None

    prompt = await components.control_plane.get_prompt("prompt/worker")
    assert prompt is not None
    assert prompt["prompt_ref"] == "prompt/worker"
    assert components.prompt_loader.load("prompt/worker") == "you are worker"
    assert (tmp_path / "prompts" / "worker.md").exists()


async def test_runtime_config_control_plane_create_session_seeds_qq_group_bot_admin_surfaces(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, base_dir=tmp_path)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    await _seed_model_registry(components.control_plane)

    created = await components.control_plane.create_session(
        {
            "session_id": "qq:group:20001",
            "title": "Group Session",
            "template_id": "qq_group",
        }
    )

    surfaces = created["surfaces"]
    for surface_id, expected_mode in {
        "message.mention": "respond",
        "message.reply_to_bot": "respond",
        "message.plain": "record_only",
    }.items():
        computer = surfaces[surface_id]["computer"]
        assert surfaces[surface_id]["admission"]["default"]["mode"] == expected_mode
        assert computer["default"]["backend"] == "docker"
        assert computer["cases"][0]["when"] == {"is_bot_admin": True}
        assert computer["cases"][0]["use"]["backend"] == "host"
    assert created["agent"]["visible_tools"] == [
        "Skill",
        "ask_backend",
        "bash",
        "delegate_subagent",
        "edit",
        "message",
        "read",
        "sticky_note_append",
        "sticky_note_read",
        "write",
        "refresh_extensions",
    ]
    assert "computer_policy" not in created["agent"]


async def test_runtime_config_control_plane_create_session_keeps_default_agent_model_target_binding(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, base_dir=tmp_path)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    await _seed_model_registry(components.control_plane)

    created = await components.control_plane.create_session(
        {
            "session_id": "qq:user:20001",
            "title": "Worker Session",
            "template_id": "qq_private",
        }
    )

    assert created["session"]["session_id"] == "qq:user:20001"
    preview = await components.control_plane.preview_effective_target_model("agent:aca")
    assert preview.target_id == "agent:aca"
    assert preview.request.preset_id == "aca-main"


async def test_webui_subagents_endpoint_returns_catalog_items(tmp_path: Path) -> None:
    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="负责整理 Excel 子任务",
    )
    _write_minimal_fs_session(tmp_path, session_id="qq:user:99999")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  filesystem:
    base_dir: "{tmp_path}"
    subagent_catalog_dirs:
      - ".agents/subagents"
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
        log_buffer=InMemoryLogBuffer(),
    )
    await _seed_model_registry(components.control_plane)
    await components.control_plane.upsert_prompt(
        prompt_ref="prompt/worker",
        content="you are worker",
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        payload = await asyncio.to_thread(request_json, base_url, "/api/subagents")
    finally:
        await server.stop()

    assert payload["ok"] is True
    assert payload["data"] == [
        {
            "subagent_id": f"project:{str((tmp_path / '.agents' / 'subagents' / 'excel-worker' / 'SUBAGENT.md').resolve())}",
            "subagent_name": "excel-worker",
            "description": "负责整理 Excel 子任务",
            "source": "project",
            "host_subagent_file_path": str(
                (tmp_path / ".agents" / "subagents" / "excel-worker" / "SUBAGENT.md").resolve()
            ),
            "tools": ["read"],
            "model_target": "",
            "effective": True,
        }
    ]


async def test_webui_subagents_endpoint_preserves_duplicate_names_with_unique_ids(
    tmp_path: Path,
) -> None:
    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="项目作用域 Excel 子任务",
    )
    user_root = tmp_path / "user-subagents"
    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="用户作用域 Excel 子任务",
        root_dir=user_root,
    )
    config_path = tmp_path / "config.yaml"
    _write_minimal_fs_session(tmp_path, session_id="qq:user:99999")
    config_path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  filesystem:
    base_dir: "{tmp_path}"
    subagent_catalog_dirs:
      - ".agents/subagents"
      - "{user_root.resolve()}"
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
        log_buffer=InMemoryLogBuffer(),
    )
    await _seed_model_registry(components.control_plane)
    await components.control_plane.upsert_prompt(
        prompt_ref="prompt/worker",
        content="you are worker",
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        payload = await asyncio.to_thread(request_json, base_url, "/api/subagents")
    finally:
        await server.stop()

    assert payload["ok"] is True
    assert [item["subagent_name"] for item in payload["data"]] == ["excel-worker", "excel-worker"]
    assert len({item["subagent_id"] for item in payload["data"]}) == 2
    assert [item["effective"] for item in payload["data"]] == [True, False]


async def test_runtime_config_control_plane_normalizes_group_surface_aliases_for_runtime(
    tmp_path: Path,
) -> None:
    """群聊配置页使用公共事件名保存时，后端会转成 runtime 可识别的 surface 键。"""

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, base_dir=tmp_path)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    await components.control_plane.create_session(
        {
            "session_id": "qq:group:20001",
            "title": "Group Worker Session",
            "template_id": "qq_group",
        }
    )

    await components.control_plane.update_session(
        "qq:group:20001",
        {
            "surfaces": {
                "message": {"admission": {"default": {"mode": "record_only"}}},
                "message_mention": {"admission": {"default": {"mode": "respond"}}},
                "message_reply": {"admission": {"default": {"mode": "respond"}}},
            },
        },
    )

    bundle = components.config_control_plane.get_session_bundle("qq:group:20001")
    assert bundle is not None
    assert bundle["surfaces"]["message.mention"]["admission"]["default"]["mode"] == "respond"
    assert bundle["surfaces"]["message.reply_to_bot"]["admission"]["default"]["mode"] == "respond"

    session_text = (tmp_path / "sessions" / "qq" / "group" / "20001" / "session.yaml").read_text(encoding="utf-8")
    assert "message.mention:" in session_text
    assert "message.reply_to_bot:" in session_text
    assert "message_mention:" not in session_text
    assert "message_reply:" not in session_text

    decision = await components.router.route(
        StandardEvent(
            event_id="evt-mention",
            event_type="message",
            platform="qq",
            timestamp=123,
            source=EventSource(platform="qq", message_type="group", user_id="1733064202", group_id="20001"),
            segments=[MsgSegment(type="text", data={"text": "@bot 说句话"})],
            raw_message_id="msg-1",
            sender_nickname="tester",
            sender_role=None,
            mentions_self=True,
            targets_self=True,
        )
    )
    assert decision.run_mode == "respond"
    assert decision.metadata["surface_id"] == "message.mention"


async def test_runtime_config_control_plane_rejects_updating_internal_session_agent_ids(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, base_dir=tmp_path)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    await components.control_plane.create_session(
        {"session_id": "qq:user:20001", "title": "Worker Session"}
    )

    with pytest.raises(ValueError, match="internal readonly fields"):
        await components.control_plane.update_session(
            "qq:user:20001",
            {"frontstage_agent_id": "changed"},
        )


def test_runtime_components_always_use_filesystem_session_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, base_dir=tmp_path)
    config = Config.from_file(str(config_path))

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    # filesystem is always on — session_bundle_loader is always constructed
    assert components.config_control_plane.session_bundle_loader is not None
    bundles = components.config_control_plane.list_sessions()
    assert len(bundles) >= 1


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


async def test_runtime_http_api_server_serves_status_and_session_crud(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        filesystem_enabled=True,
        base_dir=tmp_path,
    )
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    await _seed_model_registry(components.control_plane)
    await components.control_plane.upsert_prompt(
        prompt_ref="prompt/worker",
        content="you are worker",
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"

        meta = await asyncio.to_thread(request_json, base_url, "/api/meta")
        assert meta["ok"] is True
        assert "config_path" in meta["data"]

        status = await asyncio.to_thread(request_json, base_url, "/api/status")
        assert status["ok"] is True
        assert "loaded_plugins" in status["data"]

        backend_status = await asyncio.to_thread(request_json, base_url, "/api/backend/status")
        assert backend_status["ok"] is True
        assert "configured" in backend_status["data"]
        assert backend_status["data"]["configured"] is False
        assert backend_status["data"]["session_path"].endswith("runtime_data/backend/session.json")

        backend_path = await asyncio.to_thread(request_json, base_url, "/api/backend/session-path")
        assert backend_path["ok"] is True
        assert backend_path["data"]["path"].endswith("runtime_data/backend/session.json")

        catalog = await asyncio.to_thread(request_json, base_url, "/api/ui/catalog")
        assert catalog["ok"] is True
        assert "agents" in catalog["data"]
        assert "tools" in catalog["data"]
        assert "options" in catalog["data"]
        assert "event_types" in catalog["data"]["options"]
        assert "binding_target_types" not in catalog["data"]["options"]
        assert catalog["data"]["options"]["model_target_source_kinds"] == ["agent", "system", "plugin"]
        assert any(item["prompt_name"] == "default" for item in catalog["data"]["prompts"])

        logs = await asyncio.to_thread(request_json, base_url, "/api/system/logs")
        assert logs["ok"] is True
        assert "items" in logs["data"]
        assert "next_seq" in logs["data"]
        assert "reset_required" in logs["data"]

        plugins_list = await asyncio.to_thread(request_json, base_url, "/api/system/plugins")
        assert plugins_list["ok"] is True
        assert "plugins" in plugins_list["data"]

        created = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/sessions",
            method="POST",
            payload={
                "session_id": "qq:user:20001",
                "title": "Worker Session",
            },
        )
        assert created["ok"] is True
        listed = await asyncio.to_thread(request_json, base_url, "/api/sessions")
        assert any(item["session_id"] == "qq:user:20001" for item in listed["data"])
        session_detail = await asyncio.to_thread(request_json, base_url, "/api/sessions/qq%3Auser%3A20001")
        assert session_detail["data"]["session"]["session_id"] == "qq:user:20001"
        agent_saved = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/sessions/qq%3Auser%3A20001/agent",
            method="PUT",
            payload={
                "prompt_ref": "prompt/worker",
                "visible_tools": ["read"],
            },
        )
        assert agent_saved["data"]["prompt_ref"] == "prompt/worker"
        agent_detail = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/sessions/qq%3Auser%3A20001/agent",
        )
        assert agent_detail["data"]["agent_id"] == "session:qq:user:20001:frontstage"

        workspaces_result = await asyncio.to_thread(request_json, base_url, "/api/workspaces")
        assert workspaces_result["ok"] is True
    finally:
        await server.stop()


async def test_runtime_http_api_server_supports_schedule_webui_crud(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        filesystem_enabled=True,
        base_dir=tmp_path,
    )
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

        created_status, created = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/schedules/conversation-wakeup",
            method="POST",
            payload={
                "conversation_id": "qq:user:20001",
                "schedule": {"kind": "interval", "spec": {"seconds": 60}},
                "note": "测试提醒",
            },
        )
        assert created_status == 201
        assert created["ok"] is True
        task_id = created["data"]["task_id"]
        assert created["data"]["conversation_id"] == "qq:user:20001"
        assert created["data"]["kind"] == "conversation_wakeup"
        assert created["data"]["enabled"] is True

        listed = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/schedules/conversation-wakeup?conversation_id=qq%3Auser%3A20001&enabled=true&limit=20",
        )
        assert listed["ok"] is True
        assert len(listed["data"]["items"]) == 1
        assert listed["data"]["items"][0]["task_id"] == task_id

        disabled = await asyncio.to_thread(
            request_json,
            base_url,
            f"/api/schedules/conversation-wakeup/{quote(task_id, safe='')}/disable",
            method="POST",
            payload={},
        )
        assert disabled["data"]["enabled"] is False
        assert disabled["data"]["next_fire_at"] is None

        enabled = await asyncio.to_thread(
            request_json,
            base_url,
            f"/api/schedules/conversation-wakeup/{quote(task_id, safe='')}/enable",
            method="POST",
            payload={},
        )
        assert enabled["data"]["enabled"] is True
        assert enabled["data"]["next_fire_at"] is not None

        deleted = await asyncio.to_thread(
            request_json,
            base_url,
            f"/api/schedules/conversation-wakeup/{quote(task_id, safe='')}",
            method="DELETE",
        )
        assert deleted["data"]["deleted"] is True
        assert deleted["data"]["task_id"] == task_id

        missing_status, missing = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            f"/api/schedules/conversation-wakeup/{quote(task_id, safe='')}/enable",
            method="POST",
            payload={},
        )
        assert missing_status == 404
        assert missing["ok"] is False
    finally:
        await server.stop()


async def test_runtime_http_api_server_rejects_invalid_schedule_webui_payload(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        filesystem_enabled=True,
        base_dir=tmp_path,
    )
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

        status, payload = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/schedules/conversation-wakeup",
            method="POST",
            payload={
                "conversation_id": "qq:user:20001",
                "schedule": {"kind": "interval", "spec": {}},
                "note": "x" * 600,
            },
        )
        assert status == 400
        assert payload["ok"] is False

        past_status, past_payload = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/schedules/conversation-wakeup",
            method="POST",
            payload={
                "conversation_id": "qq:user:20001",
                "schedule": {"kind": "one_shot", "spec": {"fire_at": time.time() - 10}},
                "note": "过去时间",
            },
        )
        assert past_status == 400
        assert past_payload["ok"] is False
    finally:
        await server.stop()


async def test_runtime_http_api_server_returns_conflict_for_expired_one_shot_enable(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        filesystem_enabled=True,
        base_dir=tmp_path,
    )
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

        created = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/schedules/conversation-wakeup",
            method="POST",
            payload={
                "conversation_id": "qq:user:20001",
                "schedule": {"kind": "one_shot", "spec": {"fire_at": time.time() + 0.1}},
                "note": "测试 one-shot",
            },
        )
        task_id = created["data"]["task_id"]
        await asyncio.to_thread(
            request_json,
            base_url,
            f"/api/schedules/conversation-wakeup/{quote(task_id, safe='')}/disable",
            method="POST",
            payload={},
        )
        components.scheduler._tasks[task_id].schedule = OneShotSchedule(fire_at=time.time() - 10)

        status, payload = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            f"/api/schedules/conversation-wakeup/{quote(task_id, safe='')}/enable",
            method="POST",
            payload={},
        )
        assert status == 409
        assert payload["ok"] is False
    finally:
        await server.stop()


async def test_runtime_http_api_server_returns_service_unavailable_for_schedule_api_without_service(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        filesystem_enabled=True,
        base_dir=tmp_path,
    )
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    components.control_plane.scheduled_task_service = None
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"

        status, payload = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/schedules/conversation-wakeup",
        )
        assert status == 503
        assert payload["ok"] is False
    finally:
        await server.stop()


async def test_runtime_http_api_server_rejects_path_traversal_session_ids(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        base_dir=tmp_path,
    )
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

        status, created = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/sessions",
            method="POST",
            payload={"session_id": "qq:user:..\\evil"},
        )
        # path-traversal 校验拒绝含 \ 的 session_id
        assert status == 400

        encoded = quote("qq:user:..\\evil", safe=":")
        status, fetched = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            f"/api/sessions/{encoded}",
        )
        assert status in (400, 404)
    finally:
        await server.stop()


async def test_runtime_http_api_server_defaults_sessions_dir_when_filesystem_enabled(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_minimal_fs_session(tmp_path, session_id="qq:user:99999")
    config_path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  filesystem:
    base_dir: "{tmp_path}"
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
        log_buffer=InMemoryLogBuffer(),
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        meta = await asyncio.to_thread(request_json, base_url, "/api/meta")
        created = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/sessions",
            method="POST",
            payload={
                "session_id": "qq:user:10001",
                "title": "Worker Session",
                "template_id": "qq_private",
            },
        )
    finally:
        await server.stop()

    assert meta["ok"] is True
    assert created["data"]["session"]["session_id"] == "qq:user:10001"
    assert (tmp_path / "sessions" / "qq" / "user" / "10001" / "session.yaml").exists()
    assert (tmp_path / "sessions" / "qq" / "user" / "10001" / "agent.yaml").exists()


async def test_runtime_http_api_server_exposes_system_configuration_snapshot_and_gateway_restart_status(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_minimal_fs_session(tmp_path, session_id="qq:user:99999")
    config_path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080
  timeout: 10
  token: ""

agent:

runtime:
  filesystem:
    base_dir: "{tmp_path}"
    sessions_dir: "sessions"
  backend:
    admin_actor_ids:
      - "qq:private:123456"
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

        snapshot = await asyncio.to_thread(request_json, base_url, "/api/system/configuration")
        saved_gateway = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/gateway/config",
            method="PUT",
            payload={
                "host": "0.0.0.0",
                "port": 9001,
                "timeout": 30,
                "token": "updated-token",
            },
        )
    finally:
        await server.stop()

    assert snapshot["ok"] is True
    assert snapshot["data"]["meta"]["config_path"] == str(config_path.resolve())
    assert snapshot["data"]["admins"] == {
        "admin_actor_ids": ["qq:private:123456"],
    }
    assert snapshot["data"]["gateway"]["host"] == "127.0.0.1"
    assert snapshot["data"]["paths"]["config_path"] == str(config_path.resolve())
    assert snapshot["data"]["paths"]["filesystem_base_dir"] == str(tmp_path.resolve())
    assert snapshot["data"]["paths"]["prompts_dir"] == str((tmp_path / "prompts").resolve())
    assert snapshot["data"]["paths"]["sessions_dir"] == str((tmp_path / "sessions").resolve())
    assert snapshot["data"]["paths"]["computer_root_dir"] == str((tmp_path / "runtime_data" / "workspaces").resolve())
    assert snapshot["data"]["paths"]["sticky_notes_dir"] == str((tmp_path / "runtime_data" / "sticky_notes").resolve())
    assert snapshot["data"]["paths"]["long_term_memory_storage_dir"] == str(
        (tmp_path / "runtime_data" / "long_term_memory" / "lancedb").resolve()
    )
    assert snapshot["data"]["paths"]["backend_session_path"] == str(
        (tmp_path / "runtime_data" / "backend" / "session.json").resolve()
    )
    assert snapshot["data"]["paths"]["resolved_skill_catalog_dirs"] == [
        str((tmp_path / "extensions" / "skills").resolve()),
    ]
    assert snapshot["data"]["paths"]["resolved_subagent_catalog_dirs"] == [
        str((tmp_path / "extensions" / "subagents").resolve()),
    ]
    for key in (
        "config_path",
        "filesystem_base_dir",
        "prompts_dir",
        "sessions_dir",
        "computer_root_dir",
        "sticky_notes_dir",
        "long_term_memory_storage_dir",
        "backend_session_path",
    ):
        assert Path(snapshot["data"]["paths"][key]).is_absolute()

    assert saved_gateway["ok"] is True
    assert saved_gateway["data"]["host"] == "0.0.0.0"
    assert saved_gateway["data"]["port"] == 9001
    assert saved_gateway["data"]["timeout"] == 30.0
    assert saved_gateway["data"]["token"] == "updated-token"
    assert saved_gateway["data"]["apply_status"] == "restart_required"
    assert saved_gateway["data"]["restart_required"] is True
    assert saved_gateway["data"]["message"] == "已保存，需要重启后生效"


async def test_runtime_http_api_server_serves_and_updates_render_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0, base_dir=tmp_path)
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

        initial = await asyncio.to_thread(request_json, base_url, "/api/render/config")
        updated = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/render/config",
            method="PUT",
            payload={
                "width": 1280,
                "device_scale_factor": 2.5,
            },
        )
        system_snapshot = await asyncio.to_thread(request_json, base_url, "/api/system/configuration")
    finally:
        await server.stop()

    assert initial["ok"] is True
    assert initial["data"]["width"] == DEFAULT_RENDER_VIEWPORT_WIDTH
    assert initial["data"]["device_scale_factor"] == DEFAULT_RENDER_DEVICE_SCALE_FACTOR

    assert updated["ok"] is True
    assert updated["data"]["width"] == 1280
    assert updated["data"]["device_scale_factor"] == 2.5
    assert updated["data"]["apply_status"] == "applied"
    assert updated["data"]["restart_required"] is False

    assert system_snapshot["ok"] is True
    assert system_snapshot["data"]["render"]["width"] == 1280
    assert system_snapshot["data"]["render"]["device_scale_factor"] == 2.5
    persisted = Config.from_file(str(config_path))
    assert persisted.get("runtime", {}).get("render", {}) == {
        "width": 1280,
        "device_scale_factor": 2.5,
    }


async def test_runtime_http_api_server_render_config_falls_back_for_malformed_config_values(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_minimal_fs_session(tmp_path, session_id="qq:user:99999")
    config_path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  filesystem:
    base_dir: "{tmp_path}"
  render:
    width: "not-a-number"
    device_scale_factor: "still-not-a-number"
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

        render_status, render_config = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/render/config",
        )
        system_status, system_snapshot = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/system/configuration",
        )
    finally:
        await server.stop()

    assert render_status == 200
    assert render_config["ok"] is True
    assert render_config["data"]["width"] == DEFAULT_RENDER_VIEWPORT_WIDTH
    assert render_config["data"]["device_scale_factor"] == DEFAULT_RENDER_DEVICE_SCALE_FACTOR

    assert system_status == 200
    assert system_snapshot["ok"] is True
    assert system_snapshot["data"]["render"] == {
        "width": DEFAULT_RENDER_VIEWPORT_WIDTH,
        "device_scale_factor": DEFAULT_RENDER_DEVICE_SCALE_FACTOR,
    }


async def test_runtime_http_api_server_render_config_put_falls_back_for_malformed_payload_values(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0, base_dir=tmp_path)
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

        status, updated = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/render/config",
            method="PUT",
            payload={
                "width": "not-a-number",
                "device_scale_factor": "still-not-a-number",
            },
        )
    finally:
        await server.stop()

    assert status == 200
    assert updated["ok"] is True
    assert updated["data"]["width"] == DEFAULT_RENDER_VIEWPORT_WIDTH
    assert updated["data"]["device_scale_factor"] == DEFAULT_RENDER_DEVICE_SCALE_FACTOR
    assert updated["data"]["apply_status"] == "applied"
    assert updated["data"]["restart_required"] is False
    persisted = Config.from_file(str(config_path))
    assert persisted.get("runtime", {}).get("render", {}) == {
        "width": DEFAULT_RENDER_VIEWPORT_WIDTH,
        "device_scale_factor": DEFAULT_RENDER_DEVICE_SCALE_FACTOR,
    }


async def test_runtime_http_api_server_render_config_clamps_explicit_zero_config_values(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_minimal_fs_session(tmp_path, session_id="qq:user:99999")
    config_path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  filesystem:
    base_dir: "{tmp_path}"
  render:
    width: 0
    device_scale_factor: 0
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

        render_status, render_config = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/render/config",
        )
        system_status, system_snapshot = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/system/configuration",
        )
    finally:
        await server.stop()

    assert render_status == 200
    assert render_config["ok"] is True
    assert render_config["data"] == {
        "width": 320,
        "device_scale_factor": 1.0,
    }

    assert system_status == 200
    assert system_snapshot["ok"] is True
    assert system_snapshot["data"]["render"] == {
        "width": 320,
        "device_scale_factor": 1.0,
    }


async def test_runtime_http_api_server_render_config_put_clamps_explicit_zero_payload_values(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_minimal_fs_session(tmp_path, session_id="qq:user:99999")
    config_path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  filesystem:
    base_dir: "{tmp_path}"
  render:
    width: 1280
    device_scale_factor: 2.5
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

        status, updated = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/render/config",
            method="PUT",
            payload={
                "width": 0,
                "device_scale_factor": 0,
            },
        )
    finally:
        await server.stop()

    assert status == 200
    assert updated["ok"] is True
    assert updated["data"]["width"] == 320
    assert updated["data"]["device_scale_factor"] == 1.0
    assert updated["data"]["apply_status"] == "applied"
    assert updated["data"]["restart_required"] is False
    persisted = Config.from_file(str(config_path))
    assert persisted.get("runtime", {}).get("render", {}) == {
        "width": 320,
        "device_scale_factor": 1.0,
    }


async def test_render_config_put_hot_applies_to_existing_playwright_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0, base_dir=tmp_path)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    backend = components.render_service.get_backend("playwright")
    assert backend is not None
    original_update_render_defaults = backend.update_render_defaults
    hot_apply_calls: list[tuple[int, float]] = []

    def _spy_update_render_defaults(*, viewport_width: int, device_scale_factor: float) -> None:
        hot_apply_calls.append((viewport_width, device_scale_factor))
        original_update_render_defaults(
            viewport_width=viewport_width,
            device_scale_factor=device_scale_factor,
        )

    monkeypatch.setattr(backend, "update_render_defaults", _spy_update_render_defaults)

    result = await components.control_plane.upsert_render_config(
        {"width": 1280, "device_scale_factor": 2.5}
    )

    assert result["width"] == 1280
    assert result["device_scale_factor"] == 2.5
    assert result["apply_status"] == "applied"
    assert result["restart_required"] is False
    assert hot_apply_calls == [(1280, 2.5)]


async def test_render_config_put_reports_apply_failed_when_hot_apply_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0, base_dir=tmp_path)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    backend = components.render_service.get_backend("playwright")
    assert backend is not None

    def _explode(*, viewport_width: int, device_scale_factor: float) -> None:
        _ = (viewport_width, device_scale_factor)
        raise RuntimeError("render hot apply exploded")

    monkeypatch.setattr(backend, "update_render_defaults", _explode)

    result = await components.control_plane.upsert_render_config(
        {"width": 1280, "device_scale_factor": 2.5}
    )

    assert result["width"] == 1280
    assert result["device_scale_factor"] == 2.5
    assert result["apply_status"] == "apply_failed"
    assert result["restart_required"] is True
    assert result["message"] == "已保存，但热应用失败，需要重启"
    assert "render hot apply exploded" in result["technical_detail"]
    persisted = Config.from_file(str(config_path))
    assert persisted.get("runtime", {}).get("render", {}) == {
        "width": 1280,
        "device_scale_factor": 2.5,
    }


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


async def test_runtime_http_api_server_serves_latest_run_steps_with_sanitized_payloads(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0, base_dir=tmp_path)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    run_id = await _open_test_run(components)
    await components.run_manager.append_step(
        RunStep(
            step_id="step:1",
            run_id=run_id,
            thread_id="qq:user:10001",
            step_type="workspace_prepare",
            status="completed",
            payload={"workspace_root": "/workspace", "token": "first-secret"},
            created_at=1,
        )
    )
    await components.run_manager.append_step(
        RunStep(
            step_id="step:2",
            run_id=run_id,
            thread_id="qq:user:10001",
            step_type="exec",
            status="failed",
            payload={
                "stdout_excerpt": "hello",
                "stderr_excerpt": "boom",
                "authorization": "Bearer secret",
            },
            created_at=1,
        )
    )
    await components.run_manager.append_step(
        RunStep(
            step_id="step:3",
            run_id=run_id,
            thread_id="qq:user:10001",
            step_type="approval_resume",
            status="completed",
            payload={"result": "ok"},
            created_at=1,
        )
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"

        run_response = await asyncio.to_thread(request_json, base_url, f"/api/runtime/runs/{quote(run_id, safe=':')}")
        assert run_response["ok"] is True
        assert run_response["data"]["run_id"] == run_id
        assert isinstance(run_response["data"]["metadata"], dict)
        assert isinstance(run_response["data"]["approval_context"], dict)

        steps_response = await asyncio.to_thread(
            request_json,
            base_url,
            f"/api/runtime/runs/{quote(run_id, safe=':')}/steps?limit=2&latest=true",
        )
        assert steps_response["ok"] is True
        steps = steps_response["data"]
        assert [step["step_id"] for step in steps] == ["step:2", "step:3"]
        assert [step["step_seq"] for step in steps] == [2, 3]
        assert steps[0]["payload"]["authorization"] == "[REDACTED]"
        assert steps[0]["payload"]["stdout_excerpt"] == "hello"
        assert steps[0]["payload"]["stderr_excerpt"] == "boom"
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
        assert names == ["today.md"]

        today_file = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/soul/file?name=today.md",
        )
        assert today_file["ok"] is True
        assert today_file["data"]["name"] == "today.md"
        assert str(today_file["data"]["content"]) == ""

        self_alias = await asyncio.to_thread(request_json, base_url, "/api/self/files")
        assert self_alias["ok"] is True
        assert [str(item["name"]) for item in self_alias["data"]["items"]] == names

        created = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/soul/files",
            method="POST",
            payload={"name": "daily/2026-03-23.md", "content": "# 2026-03-23\n- 完成部署"},
        )
        assert created["ok"] is True
        assert created["data"]["name"] == "daily/2026-03-23.md"

        updated = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/soul/file",
            method="PUT",
            payload={"name": "today.md", "content": "[qq:group:42 time=1] 重写 WebUI"},
        )
        assert updated["ok"] is True
        assert "重写 WebUI" in str(updated["data"]["content"])

        status, invalid_path = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/soul/file",
            method="PUT",
            payload={"name": "../escape.md", "content": "bad"},
        )
        assert status == 400
        assert invalid_path["ok"] is False

        created_note = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/memory/sticky-notes/item",
            method="POST",
            payload={"entity_ref": "qq:group:42"},
        )
        assert created_note["ok"] is True
        assert created_note["data"]["entity_ref"] == "qq:group:42"

        saved_note = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/memory/sticky-notes/item",
            method="PUT",
            payload={
                "entity_ref": "qq:group:42",
                "readonly": "十个月只需要成果鉴定。",
                "editable": "补充：不用额外证明。",
            },
        )
        assert saved_note["ok"] is True

        sticky_item = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/memory/sticky-notes/item?entity_ref=qq:group:42",
        )
        assert sticky_item["ok"] is True
        assert sticky_item["data"]["readonly"] == "十个月只需要成果鉴定。"
        assert sticky_item["data"]["editable"] == "补充：不用额外证明。"

        listed = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/memory/sticky-notes?entity_kind=conversation",
        )
        assert listed["ok"] is True
        assert any(
            item["entity_ref"] == "qq:group:42"
            for item in listed["data"]["items"]
        )
    finally:
        await server.stop()


async def test_runtime_http_api_server_serves_and_updates_long_term_memory_config(tmp_path: Path) -> None:
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

        initial = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/memory/long-term/config",
        )
        assert initial["ok"] is True
        assert initial["data"]["enabled"] is False
        assert initial["data"]["window_size"] == 50
        assert initial["data"]["required_target_ids"] == [
            "system:ltm_extract",
            "system:ltm_query_plan",
            "system:ltm_embed",
        ]

        updated = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/memory/long-term/config",
            method="PUT",
            payload={
                "enabled": True,
                "storage_dir": "runtime-data/ltm",
                "window_size": 64,
                "overlap_size": 12,
                "max_entries": 10,
                "extractor_version": "ltm-extractor-v2",
            },
        )
        assert updated["ok"] is True
        assert updated["data"]["enabled"] is True
        assert updated["data"]["storage_dir"] == "runtime-data/ltm"
        assert updated["data"]["window_size"] == 64
        assert updated["data"]["overlap_size"] == 12
        assert updated["data"]["max_entries"] == 10
        assert updated["data"]["extractor_version"] == "ltm-extractor-v2"
        assert updated["data"]["restart_required"] is True
    finally:
        await server.stop()


async def test_runtime_http_api_server_serves_filesystem_catalog_scan_config_defaults(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_minimal_fs_session(tmp_path, session_id="qq:user:99999")
    config_path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  filesystem:
    base_dir: "{tmp_path}"
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
        result = await asyncio.to_thread(request_json, base_url, "/api/filesystem/config")
    finally:
        await server.stop()

    assert result["ok"] is True
    assert result["data"]["base_dir"] == str(tmp_path.resolve())
    assert result["data"]["skill_catalog_dirs"] == ["./extensions/skills"]
    assert result["data"]["subagent_catalog_dirs"] == ["./extensions/subagents"]
    assert result["data"]["configured_skill_catalog_dirs"] is None
    assert result["data"]["configured_subagent_catalog_dirs"] is None
    assert result["data"]["default_skill_catalog_dirs"] == ["./extensions/skills"]
    assert result["data"]["default_subagent_catalog_dirs"] == ["./extensions/subagents"]
    assert result["data"]["resolved_skill_catalog_dirs"] == [
        {
            "host_root_path": str((tmp_path / "extensions" / "skills").resolve()),
            "scope": "project",
        },
    ]
    assert result["data"]["resolved_subagent_catalog_dirs"] == [
        {
            "host_root_path": str((tmp_path / "extensions" / "subagents").resolve()),
            "scope": "project",
        },
    ]


async def test_runtime_http_api_server_updates_filesystem_catalog_scan_config_and_reloads(
    tmp_path: Path,
) -> None:
    skill_fixtures_root = Path(__file__).resolve().parent.parent / "fixtures" / "skills"
    initial_skills_dir = tmp_path / "initial-skills"
    initial_subagents_dir = tmp_path / "initial-subagents"
    initial_skills_dir.mkdir(parents=True, exist_ok=True)
    initial_subagents_dir.mkdir(parents=True, exist_ok=True)
    custom_subagents_dir = tmp_path / "custom-subagents"
    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="通过自定义扫描目录发现的子代理",
        root_dir=custom_subagents_dir,
    )
    _write_minimal_fs_session(tmp_path, session_id="qq:user:99999")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  filesystem:
    base_dir: "{tmp_path}"
    skill_catalog_dirs:
      - "{initial_skills_dir}"
    subagent_catalog_dirs:
      - "{initial_subagents_dir}"
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
        updated = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/filesystem/config",
            method="PUT",
            payload={
                "skill_catalog_dirs": [str(skill_fixtures_root)],
                "subagent_catalog_dirs": [str(custom_subagents_dir)],
            },
        )
        skills = await asyncio.to_thread(request_json, base_url, "/api/skills")
        subagents = await asyncio.to_thread(request_json, base_url, "/api/subagents")
    finally:
        await server.stop()

    assert updated["ok"] is True
    assert updated["data"]["apply_status"] == "applied"
    assert updated["data"]["restart_required"] is False
    assert updated["data"]["message"] == "已保存并已生效"
    assert updated["data"]["configured_skill_catalog_dirs"] == [str(skill_fixtures_root)]
    assert updated["data"]["configured_subagent_catalog_dirs"] == [str(custom_subagents_dir)]
    assert updated["data"]["skill_catalog_dirs"] == [str(skill_fixtures_root)]
    assert updated["data"]["subagent_catalog_dirs"] == [str(custom_subagents_dir)]
    assert updated["data"]["resolved_skill_catalog_dirs"] == [
        {
            "host_root_path": str(skill_fixtures_root.resolve()),
            "scope": "user",
        }
    ]
    assert updated["data"]["resolved_subagent_catalog_dirs"] == [
        {
            "host_root_path": str(custom_subagents_dir.resolve()),
            "scope": "user",
        }
    ]
    assert any(item["skill_name"] == "sample_configured_skill" for item in skills["data"])
    assert any(item["subagent_name"] == "excel-worker" for item in subagents["data"])


async def test_runtime_http_api_server_reports_filesystem_apply_failure_after_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  default_agent_id: "aca"
  filesystem:
    enabled: true
    base_dir: "{tmp_path}"
  profiles:
    aca:
      name: "Aca"
      prompt_ref: "prompt/default"
  prompts:
    prompt/default: "hello"
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

    async def _fail_reload() -> dict[str, object]:
        raise ValueError("reload exploded")

    monkeypatch.setattr(components.config_control_plane, "reload_runtime_configuration", _fail_reload)
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)
    custom_skills_dir = tmp_path / "custom-skills"

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        updated = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/filesystem/config",
            method="PUT",
            payload={
                "skill_catalog_dirs": [str(custom_skills_dir.resolve())],
            },
        )
    finally:
        await server.stop()

    assert updated["ok"] is True
    assert updated["data"]["apply_status"] == "apply_failed"
    assert updated["data"]["restart_required"] is False
    assert updated["data"]["message"] == "已写入，但应用失败"
    assert "reload exploded" in updated["data"]["technical_detail"]
    assert updated["data"]["configured_skill_catalog_dirs"] == [str(custom_skills_dir.resolve())]

    saved_config = Config.from_file(str(config_path))
    runtime_conf = dict(saved_config.get("runtime", {}) or {})
    filesystem_conf = dict(runtime_conf.get("filesystem", {}) or {})
    assert filesystem_conf["skill_catalog_dirs"] == [str(custom_skills_dir.resolve())]


async def test_runtime_http_api_server_plugin_configs_include_display_names(tmp_path: Path) -> None:
    pytest.skip("旧 plugin config API 已删除, 新 API 在 test_plugin_integration 里覆盖")
    pytest.skip("旧 plugin config API 已删除, 新 API 在 test_plugin_integration 里覆盖")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  default_agent_id: "aca"
  profiles:
    aca:
      name: "Aca"
      prompt_ref: "prompt/default"
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
        assert first["loadable"] is True
        assert first["load_error"] == ""
    finally:
        await server.stop()


async def test_runtime_http_api_server_plugin_config_put_refreshes_live_plugins(tmp_path: Path) -> None:
    pytest.skip("旧 plugin config API 已删除, 新 API 在 test_plugin_integration 里覆盖")
    pytest.skip("旧 plugin config API 已删除, 新 API 在 test_plugin_integration 里覆盖")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  default_agent_id: "aca"
  profiles:
    aca:
      name: "Aca"
      prompt_ref: "prompt/default"
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
    await components.plugin_manager.ensure_started()
    assert "ops_control" in [plugin.name for plugin in components.plugin_manager.loaded]
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"

        toggled = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/system/plugins/config",
            method="PUT",
            payload={
                "items": [
                    {
                        "path": "acabot.runtime.plugins.ops_control:OpsControlPlugin",
                        "enabled": False,
                    }
                ]
            },
        )
        assert toggled["ok"] is True
        assert "ops_control" not in [plugin.name for plugin in components.plugin_manager.loaded]
    finally:
        await server.stop()


async def test_runtime_http_api_server_marks_broken_plugin_paths_in_config_view(tmp_path: Path) -> None:
    pytest.skip("旧 plugin config API 已删除, 新 API 在 test_plugin_integration 里覆盖")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  default_agent_id: "aca"
  profiles:
    aca:
      name: "Aca"
      prompt_ref: "prompt/default"
  prompts:
    prompt/default: "hello"
  plugins:
    - path: "acabot.runtime.plugins.computer_tool_adapter:ComputerToolAdapterPlugin"
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
        assert first["loadable"] is False
        assert "computer_tool_adapter" in first["path"]
        assert str(first["load_error"]).strip() != ""
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


async def test_runtime_http_api_server_preserves_hidden_model_provider_fields_on_partial_update(tmp_path: Path) -> None:
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

        created = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/models/providers/openai-main",
            method="PUT",
            payload={
                "name": "OpenAI 主线路",
                "kind": "openai_compatible",
                "base_url": "https://llm.example.com/v1",
                "api_key_env": "OPENAI_API_KEY",
                "default_headers": {"X-Trace": "1"},
                "default_query": {"api-version": "2024-01-01"},
                "default_body": {"metadata": {"source": "seed"}},
            },
        )
        assert created["ok"] is True

        updated = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/models/providers/openai-main",
            method="PUT",
            payload={
                "name": "OpenAI 主线路(改名)",
                "kind": "openai_compatible",
                "base_url": "https://llm.example.com/v1",
                "api_key_env": "OPENAI_API_KEY",
            },
        )
        assert updated["ok"] is True

        provider_detail = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/models/providers/openai-main",
        )
        assert provider_detail["ok"] is True
        assert provider_detail["data"]["name"] == "OpenAI 主线路(改名)"
        assert provider_detail["data"]["config"]["default_headers"] == {"X-Trace": "1"}
        assert provider_detail["data"]["config"]["default_query"] == {"api-version": "2024-01-01"}
        assert provider_detail["data"]["config"]["default_body"] == {"metadata": {"source": "seed"}}
    finally:
        await server.stop()


async def test_runtime_http_api_server_persists_model_preset_task_kind_and_capabilities(tmp_path: Path) -> None:
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
            "/api/models/providers/openai-main",
            method="PUT",
            payload={
                "name": "OpenAI 主线路",
                "kind": "openai_compatible",
                "base_url": "https://llm.example.com/v1",
                "api_key_env": "OPENAI_API_KEY",
            },
        )
        saved = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/models/presets/embed-main",
            method="PUT",
            payload={
                "provider_id": "openai-main",
                "model": "text-embedding-3-large",
                "task_kind": "embedding",
                "capabilities": [],
                "context_window": 8192,
                "max_output_tokens": None,
                "model_params": {},
            },
        )
        assert saved["ok"] is True
        assert saved["data"]["entity_id"] == "embed-main"

        preset = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/models/presets/embed-main",
        )
        assert preset["ok"] is True
        assert preset["data"]["task_kind"] == "embedding"
        assert preset["data"]["capabilities"] == []
    finally:
        await server.stop()


async def test_runtime_http_api_server_health_check_prefixes_provider_model_for_litellm(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await components.control_plane.upsert_model_provider(
        ModelProvider(
            provider_id="glm",
            name="GLM",
            kind="anthropic",
            config=AnthropicProviderConfig(
                base_url="https://open.bigmodel.cn/api/anthropic",
                api_key_env="GLM_API_KEY",
                anthropic_version="2023-06-01",
            ),
        )
    )
    await components.control_plane.upsert_model_preset(
        ModelPreset(
            preset_id="glm-main",
            provider_id="glm",
            model="glm-4.7",
            task_kind="chat",
            capabilities=["tool_calling"],
            context_window=128000,
        )
    )

    async def fake_complete(self, system_prompt, messages, model=None, request_options=None):
        _ = self, system_prompt, messages, request_options
        return type(
            "Response",
            (),
            {
                "error": None,
                "model_used": model or "",
            },
        )()

    monkeypatch.setattr("acabot.agent.agent.LitellmAgent.complete", fake_complete)

    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"

        result = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/models/presets/glm-main/health-check",
            method="POST",
            payload={},
        )

        assert result["ok"] is True
        assert result["data"]["ok"] is True
        assert result["data"]["model"] == "anthropic/glm-4.7"
        assert result["data"]["metadata"]["model_used"] == "anthropic/glm-4.7"
    finally:
        await server.stop()


async def test_put_admins_updates_session_runtime_without_restart(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, base_dir=tmp_path, write_session=False)
    group_dir = tmp_path / "sessions" / "qq" / "group" / "123"
    group_dir.mkdir(parents=True, exist_ok=True)
    (group_dir / "session.yaml").write_text(
        """
session:
  id: qq:group:123
  template: qq_group
frontstage:
  agent_id: aca
selectors:
  bot_admin:
    is_bot_admin: true
surfaces:
  message.mention:
    admission:
      default:
        mode: respond
    computer:
      default:
        backend: docker
        allow_exec: true
        allow_sessions: true
      cases:
        - case_id: bot_admin_host
          when_ref: bot_admin
          use:
            backend: host
            allow_exec: true
            allow_sessions: true
""".strip(),
        encoding="utf-8",
    )
    (group_dir / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "agent_id": "aca",
                "prompt_ref": "prompt/default",
                "visible_tools": [],
                "visible_skills": [],
                "visible_subagents": [],
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "default.md").write_text("hello", encoding="utf-8")

    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    before_facts = components.app.router.session_runtime.build_facts(
        _session_event(message_type="group", user_id="10001", group_id="123", mentions_self=True, targets_self=True)
    )
    assert before_facts.is_bot_admin is False

    result = await components.control_plane.put_admins(payload={"admin_actor_ids": ["qq:user:10001"]})

    after_facts = components.app.router.session_runtime.build_facts(
        _session_event(message_type="group", user_id="10001", group_id="123", mentions_self=True, targets_self=True)
    )
    assert result["admin_actor_ids"] == ["qq:user:10001"]
    assert after_facts.is_bot_admin is True


async def test_runtime_http_api_server_serves_product_shaped_bot_settings_and_admin_actor_ids_apply_status(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        backend_admin_actor_ids=["qq:private:123456"],
    )
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
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
            task_kind="chat",
            capabilities=["tool_calling"],
            context_window=128000,
        )
    )
    await components.control_plane.upsert_model_preset(
        ModelPreset(
            preset_id="main-b",
            provider_id="openai-main",
            model="gpt-main-b",
            task_kind="chat",
            capabilities=["tool_calling"],
            context_window=256000,
        )
    )
    await components.control_plane.upsert_model_preset(
        ModelPreset(
            preset_id="summary-a",
            provider_id="openai-main",
            model="gpt-summary-a",
            task_kind="chat",
            context_window=64000,
        )
    )
    await components.control_plane.upsert_model_preset(
        ModelPreset(
            preset_id="summary-b",
            provider_id="openai-main",
            model="gpt-summary-b",
            task_kind="chat",
            context_window=64000,
        )
    )
    await components.control_plane.upsert_model_binding(
        ModelBinding(
            binding_id="binding:aca",
            target_id="agent:aca",
            preset_ids=["main-a"],
        )
    )
    await components.control_plane.upsert_model_binding(
        ModelBinding(
            binding_id="binding:summary",
            target_id="system:compactor_summary",
            preset_ids=["summary-a"],
        )
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        status, inbound_before = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/rules/inbound",
        )
        assert status == 404
        assert inbound_before["ok"] is False

        status, bot = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/bot",
        )
        assert status == 501
        assert bot["ok"] is False
        assert "redesign pending" in bot["error"]

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
        assert saved["data"]["admin_actor_ids"] == ["qq:private:123456", "napcat:private:42"]
        assert saved["data"]["apply_status"] == "applied"
        assert saved["data"]["restart_required"] is False
        assert saved["data"]["message"] == "已保存并已生效"

        runtime_conf = dict(components.config_control_plane.config.to_dict().get("runtime", {}) or {})
        backend_conf = dict(runtime_conf.get("backend", {}) or {})
        assert backend_conf["admin_actor_ids"] == ["qq:private:123456", "napcat:private:42"]

        backend_status = await asyncio.to_thread(request_json, base_url, "/api/backend/status")
        assert backend_status["ok"] is True
        assert backend_status["data"]["admin_actor_ids"] == ["napcat:private:42", "qq:private:123456"]

        status, inbound_after = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/rules/inbound",
        )
        assert status == 404
        assert inbound_after["ok"] is False

        bindings = await components.control_plane.list_model_bindings()
        main_binding = next(item for item in bindings if item.binding.target_id == "agent:aca")
        assert main_binding.binding.preset_ids == ["main-a"]
        assert main_binding.binding_state == "resolved"

        catalog = await asyncio.to_thread(request_json, base_url, "/api/ui/catalog")
        assert catalog["ok"] is True
        catalog_binding = next(
            item for item in catalog["data"]["model_bindings"] if item["binding"]["binding_id"] == "binding:aca"
        )
        assert catalog_binding["binding_state"] == "resolved"
        assert catalog_binding["binding"]["preset_ids"] == ["main-a"]
    finally:
        await server.stop()


async def test_runtime_http_api_server_reports_unimplemented_or_unknown_shell_endpoints(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        base_dir=tmp_path,
        write_session=False,
    )
    # Write only the prompt file, not a session, so the session list is empty.
    (tmp_path / "prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prompts" / "default.md").write_text("hello", encoding="utf-8")
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

        status, sessions = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/sessions",
        )
        assert status == 200
        assert sessions["ok"] is True
        assert sessions["data"] == []

        status, session_detail = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/sessions/qq%3Agroup%3A42",
        )
        assert status == 404
        assert session_detail["ok"] is False

        status, session_put = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/sessions/qq%3Agroup%3A42",
            method="PUT",
            payload={"display_name": "ignored"},
        )
        assert status == 404
        assert session_put["ok"] is False

        status, missing_rules_surface = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/rules/inbound",
        )
        assert status == 404
        assert missing_rules_surface["ok"] is False

        status, missing_policies_surface = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/rules/event-policies",
        )
        assert status == 404
        assert missing_policies_surface["ok"] is False
    finally:
        await server.stop()


async def test_runtime_http_api_server_can_post_notification_and_update_thread(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        base_dir=tmp_path,
    )
    config = Config.from_file(str(config_path))
    gateway = FakeGateway()
    components = build_runtime_components(
        config,
        gateway=gateway,
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/notifications",
            method="POST",
            payload={
                "conversation_id": "qq:user:1733064202",
                "text": "AcaBot 主动通知测试",
            },
        )
        assert result["ok"] is True
        assert result["data"]["conversation_id"] == "qq:user:1733064202"
        assert result["data"]["thread_id"] == "qq:user:1733064202"
        assert result["data"]["platform_message_id"] == "msg-1"
        assert result["data"]["text"] == "AcaBot 主动通知测试"
        assert result["data"]["ack"]["status"] == "ok"
        assert result["data"]["ack"]["retcode"] == 0
        assert result["data"]["thread_content"] == "AcaBot 主动通知测试"

        assert len(gateway.sent) == 1
        sent_action = gateway.sent[0]
        assert sent_action.action_type == ActionType.SEND_SEGMENTS
        assert sent_action.target is not None
        assert sent_action.target.message_type == "private"
        assert sent_action.target.user_id == "1733064202"

        thread = await components.thread_manager.get_or_create(
            thread_id="qq:user:1733064202",
            channel_scope="qq:user:1733064202",
        )
        assert thread.working_messages[-1] == {
            "role": "assistant",
            "content": "AcaBot 主动通知测试",
        }

        messages = await components.message_store.get_thread_messages("qq:user:1733064202")
        assert len(messages) == 1
        assert messages[0].content_text == "AcaBot 主动通知测试"
        assert messages[0].platform_message_id == "msg-1"
    finally:
        await server.stop()


async def test_runtime_http_api_server_can_post_notification_with_workspace_relative_image_only(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        base_dir=tmp_path,
    )
    config = Config.from_file(str(config_path))
    gateway = FakeGateway()
    components = build_runtime_components(
        config,
        gateway=gateway,
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    workspace_root = components.computer_runtime.workspace_manager.workspace_dir_for_thread("qq:user:1733064202")
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "x_screenshot.png").write_bytes(b"png-bytes")
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/notifications",
            method="POST",
            payload={
                "conversation_id": "qq:user:1733064202",
                "images": ["x_screenshot.png"],
            },
        )
        assert result["ok"] is True
        assert result["data"]["images"] == ["/workspace/x_screenshot.png"]
        assert result["data"]["text"] is None
        assert result["data"]["ack"]["status"] == "ok"
        assert result["data"]["thread_content"] == "[图片]"

        assert len(gateway.sent) == 1
        sent_action = gateway.sent[0]
        assert sent_action.action_type == ActionType.SEND_SEGMENTS
        image_file = sent_action.payload["segments"][0]["data"]["file"]
        assert image_file != "/workspace/x_screenshot.png"
        assert image_file.endswith("x_screenshot.png")

        thread = await components.thread_manager.get_or_create(
            thread_id="qq:user:1733064202",
            channel_scope="qq:user:1733064202",
        )
        assert thread.working_messages[-1] == {
            "role": "assistant",
            "content": "[图片]",
        }
    finally:
        await server.stop()


async def test_runtime_http_api_server_returns_structured_notification_failure_ack(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        base_dir=tmp_path,
    )
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=NegativeAckGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        status, body = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/notifications",
            method="POST",
            payload={
                "conversation_id": "qq:user:1733064202",
                "text": "fail please",
            },
        )
        assert status == 500
        assert body["ok"] is False
        assert body["error"] == "send failed"
        assert body["data"]["delivered"] is False
        assert body["data"]["ack"]["status"] == "failed"
        assert body["data"]["ack"]["retcode"] == 100
    finally:
        await server.stop()


async def test_runtime_http_api_server_rejects_invalid_notification_payload(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        base_dir=tmp_path,
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

        status, missing_text = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/notifications",
            method="POST",
            payload={"conversation_id": "qq:user:1733064202"},
        )
        assert status == 400
        assert missing_text["ok"] is False
        assert missing_text["error"] == "send requires at least one of text, images, or render"

        status, missing_conversation = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/notifications",
            method="POST",
            payload={"text": "hello"},
        )
        assert status == 400
        assert missing_conversation["ok"] is False
        assert missing_conversation["error"] == "conversation_id is required"

        status, invalid_path = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/notifications",
            method="POST",
            payload={
                "conversation_id": "qq:user:1733064202",
                "images": ["/tmp/out.png"],
            },
        )
        assert status == 400
        assert invalid_path["ok"] is False
        assert "relative path" in invalid_path["error"]
    finally:
        await server.stop()


async def test_runtime_http_api_server_can_inject_synthetic_event_into_real_runtime_chain(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        base_dir=tmp_path,
        allow_synthetic_events=True,
    )
    config = Config.from_file(str(config_path))
    gateway = FakeGateway()
    components = build_runtime_components(
        config,
        gateway=gateway,
        agent=FakeAgent(FakeAgentResponse(text="synthetic ok")),
    )
    runtime_model_request = RuntimeModelRequest(
        provider_kind="openai_compatible",
        model="openai/test-model",
        supports_tools=True,
        provider_id="provider",
        preset_id="main",
        provider_params={"base_url": "https://example.invalid/v1"},
    )
    components.app._resolve_model_requests = lambda decision, agent: (  # type: ignore[method-assign]
        runtime_model_request,
        None,
        runtime_model_request,
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await components.app.start()
    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/runtime/events",
            method="POST",
            payload={
                "conversation_id": "qq:user:99999",
                "text": "帮我测试 synthetic event",
                "sender_nickname": "tester",
            },
        )

        assert result["ok"] is True
        assert result["data"]["synthetic"] is True
        assert result["data"]["conversation_id"] == "qq:user:99999"
        assert result["data"]["thread_id"] == "qq:user:99999"
        assert result["data"]["text"] == "帮我测试 synthetic event"
        assert result["data"]["segments"] == [{"type": "text", "data": {"text": "帮我测试 synthetic event"}}]
        assert result["data"]["run"] is not None
        assert result["data"]["run"]["trigger_event_id"] == result["data"]["event_id"]
        assert result["data"]["run"]["status"] == "completed"

        assert len(gateway.sent) == 1
        thread = await components.thread_manager.get_or_create(
            thread_id="qq:user:99999",
            channel_scope="qq:user:99999",
        )
        assert thread.working_messages[-1] == {"role": "assistant", "content": "synthetic ok"}
    finally:
        await server.stop()
        await components.app.stop()


async def test_runtime_http_api_server_group_synthetic_event_can_mark_mentions_self(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        base_dir=tmp_path,
        allow_synthetic_events=True,
        write_session=False,
    )
    group_dir = tmp_path / "sessions" / "qq" / "group" / "99999"
    group_dir.mkdir(parents=True, exist_ok=True)
    (group_dir / "session.yaml").write_text(
        """
session:
  id: qq:group:99999
  template: qq_group
frontstage:
  agent_id: aca
surfaces:
  message.mention:
    admission:
      default:
        mode: respond
  message.plain:
    admission:
      default:
        mode: record_only
""".strip(),
        encoding="utf-8",
    )
    (group_dir / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "agent_id": "aca",
                "prompt_ref": "prompt/default",
                "visible_tools": [],
                "visible_skills": [],
                "visible_subagents": [],
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "default.md").write_text("hello", encoding="utf-8")

    config = Config.from_file(str(config_path))
    gateway = FakeGateway()
    components = build_runtime_components(
        config,
        gateway=gateway,
        agent=FakeAgent(FakeAgentResponse(text="group synthetic ok")),
    )
    runtime_model_request = RuntimeModelRequest(
        provider_kind="openai_compatible",
        model="openai/test-model",
        supports_tools=True,
        provider_id="provider",
        preset_id="main",
        provider_params={"base_url": "https://example.invalid/v1"},
    )
    components.app._resolve_model_requests = lambda decision, agent: (  # type: ignore[method-assign]
        runtime_model_request,
        None,
        runtime_model_request,
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await components.app.start()
    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/runtime/events",
            method="POST",
            payload={
                "conversation_id": "qq:group:99999",
                "sender_user_id": "1733064202",
                "sender_nickname": "tester",
                "text": "群里提醒一下",
                "targets_self": True,
                "mentions_self": True,
            },
        )

        assert result["ok"] is True
        assert result["data"]["run"] is not None
        assert result["data"]["run"]["status"] == "completed"
        assert len(gateway.sent) == 1
        assert gateway.sent[0].payload["text"] == "group synthetic ok"
    finally:
        await server.stop()
        await components.app.stop()


async def test_runtime_http_api_server_rejects_invalid_synthetic_event_payload(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        base_dir=tmp_path,
        allow_synthetic_events=True,
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

        status, missing_conversation = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/runtime/events",
            method="POST",
            payload={"text": "hello"},
        )
        assert status == 400
        assert missing_conversation["error"] == "conversation_id is required"

        status, missing_content = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/runtime/events",
            method="POST",
            payload={"conversation_id": "qq:user:1733064202"},
        )
        assert status == 400
        assert missing_content["error"] == "synthetic event requires text or segments"

        status, invalid_segments = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/runtime/events",
            method="POST",
            payload={
                "conversation_id": "qq:user:1733064202",
                "segments": [{"type": "text", "data": "not-an-object"}],
            },
        )
        assert status == 400
        assert invalid_segments["error"] == "segments items require object data"
    finally:
        await server.stop()


async def test_runtime_http_api_server_blocks_synthetic_event_injection_when_disabled(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        base_dir=tmp_path,
        allow_synthetic_events=False,
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
        status, payload = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/runtime/events",
            method="POST",
            payload={
                "conversation_id": "qq:user:99999",
                "text": "hello",
            },
        )
        assert status == 403
        assert payload["ok"] is False
        assert payload["error"] == "synthetic events are disabled"
    finally:
        await server.stop()


async def test_runtime_http_api_server_blocks_non_loopback_synthetic_event_injection(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        base_dir=tmp_path,
        allow_synthetic_events=True,
    )
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    status, payload = server.handle_api_request(
        method="POST",
        path="/api/runtime/events",
        query={},
        payload={"conversation_id": "qq:user:99999", "text": "hello"},
        remote_addr="10.0.0.8",
    )

    assert status == 403
    assert payload["ok"] is False
    assert payload["error"] == "synthetic events require loopback access"


async def test_runtime_http_api_server_blocks_non_loopback_extension_refresh(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        base_dir=tmp_path,
        write_session=False,
    )
    (tmp_path / "prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "prompts" / "default.md").write_text("hello", encoding="utf-8")
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    status, payload = server.handle_api_request(
        method="POST",
        path="/api/runtime/refresh-extensions",
        query={},
        payload={"session_id": "qq:group:123", "kind": "skills"},
        remote_addr="10.0.0.8",
    )

    assert status == 403
    assert payload["ok"] is False
    assert payload["error"] == "extension refresh requires loopback access"


async def test_runtime_http_api_server_refresh_extensions_requires_session_id_and_returns_summary(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        base_dir=tmp_path,
        backend_admin_actor_ids=["qq:user:10001"],
        write_session=False,
    )
    _write_skill_package(tmp_path / "extensions" / "skills", "demo-skill", name="demo-skill", description="demo")
    _write_session_bundle(
        tmp_path,
        session_id="qq:group:123",
        visible_tools=["refresh_extensions"],
        visible_skills=["demo-skill"],
        visible_subagents=[],
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
        status, missing = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/runtime/refresh-extensions",
            method="POST",
            payload={"kind": "skills"},
        )
        assert status == 400
        assert missing["ok"] is False
        assert "session_id is required" in missing["error"]

        status, unsupported = await asyncio.to_thread(
            request_json_with_status,
            base_url,
            "/api/runtime/refresh-extensions",
            method="POST",
            payload={"session_id": "qq:group:123", "kind": "subagents"},
        )
        assert status == 400
        assert unsupported["ok"] is False
        assert "unsupported extension refresh kind" in unsupported["error"]

        refreshed = await asyncio.to_thread(
            request_json,
            base_url,
            "/api/runtime/refresh-extensions",
            method="POST",
            payload={"session_id": "qq:group:123", "kind": "skills"},
        )
        assert refreshed["ok"] is True
        assert refreshed["data"]["kind"] == "skills"
        assert refreshed["data"]["session_id"] == "qq:group:123"
        assert refreshed["data"]["visible_skills"] == ["demo-skill"]
    finally:
        await server.stop()


async def test_runtime_http_api_server_blocks_deleting_prompt_that_is_still_referenced(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        filesystem_enabled=True,
        base_dir=tmp_path,
    )
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
    await components.control_plane.create_session(
        {"session_id": "qq:user:10001", "title": "Worker Session"}
    )
    await components.control_plane.update_session_agent(
        "qq:user:10001",
        {"prompt_ref": "prompt/in-use"},
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
        assert "qq:user:10001" in payload["error"]

        prompt = await components.control_plane.get_prompt("prompt/in-use")
        assert prompt is not None
        assert prompt["prompt_ref"] == "prompt/in-use"
    finally:
        await server.stop()


def test_webui_shell_is_vite_bundle_entry() -> None:
    ensure_webui_assets_built()
    html = Path("src/acabot/webui/index.html").read_text(encoding="utf-8")

    assert "<div id=\"app\"></div>" in html
    assert "data-view=\"sessions\"" not in html
    assert "<script type=\"module\"" in html


def test_webui_built_assets_include_render_settings_entrypoint() -> None:
    ensure_webui_assets_built()
    html = Path("src/acabot/webui/index.html").read_text(encoding="utf-8")
    script_match = re.search(r'src="(/assets/[^"]+\.js)"', html)

    assert script_match is not None
    assets_dir = Path("src/acabot/webui/assets")
    js_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(assets_dir.glob("*.js"))
    )

    assert "/api/render/config" in js_sources
    assert "查看 Run 详情" in js_sources
    assert "最近 200 条 Steps" in js_sources


def test_webui_router_removes_legacy_preview_routes() -> None:
    router_source = Path("webui/src/router.ts").read_text(encoding="utf-8")
    sidebar_source = Path("webui/src/components/AppSidebar.vue").read_text(encoding="utf-8")

    assert '"/preview/' not in router_source
    assert "GlassLabView" not in router_source
    assert "GlassEditorialView" not in router_source
    assert "GlassInstrumentView" not in router_source
    assert "MaterialConsoleView" not in router_source
    assert "MaterialDarkStudyView" not in router_source
    assert "MaterialFrostStudyView" not in router_source

    assert "Glass Palettes" not in sidebar_source
    assert "Editorial Study" not in sidebar_source
    assert "Instrument Study" not in sidebar_source
    assert "Material Cold" not in sidebar_source
    assert "Frost Study" not in sidebar_source
    assert "预览" not in sidebar_source


def test_webui_source_supports_accent_theme_switching() -> None:
    app_source = Path("webui/src/App.vue").read_text(encoding="utf-8")
    sidebar_source = Path("webui/src/components/AppSidebar.vue").read_text(encoding="utf-8")

    assert "acabot.accent_theme" in app_source
    assert "accentTheme" in app_source
    assert "data-accent-theme" in app_source
    assert "rose" in app_source
    assert "graphite" in app_source
    assert "--main-ribbon-soft" in app_source
    assert "--main-ribbon-accent" in app_source
    assert "background-blend-mode: screen" in app_source

    assert "accent-btn" in sidebar_source
    assert "update:accent-theme" in sidebar_source
    assert "蔷薇" in sidebar_source
    assert "石墨" in sidebar_source


def test_webui_imports_shared_design_system_stylesheet() -> None:
    main_source = Path("webui/src/main.ts").read_text(encoding="utf-8")
    stylesheet = Path("webui/src/styles/design-system.css")

    assert 'import "./styles/design-system.css"' in main_source
    assert stylesheet.exists()

    css = stylesheet.read_text(encoding="utf-8")
    assert ".ds-page" in css
    assert ".ds-panel" in css
    assert ".ds-hero" in css
    assert ".ds-toolbar" in css
    assert ".ds-field" in css


def test_webui_logs_view_wires_expandable_logs_and_run_details() -> None:
    logs_view = Path("webui/src/views/LogsView.vue").read_text(encoding="utf-8")
    log_stream_panel = Path("webui/src/components/LogStreamPanel.vue").read_text(encoding="utf-8")
    run_detail_panel = Path("webui/src/components/RunDetailPanel.vue").read_text(encoding="utf-8")
    api_source = Path("webui/src/lib/api.ts").read_text(encoding="utf-8")
    home_view = Path("webui/src/views/HomeView.vue").read_text(encoding="utf-8")

    assert "RunDetailPanel" in logs_view
    assert '@view-run="openRunDetails"' in logs_view
    assert ":show-details=\"true\"" in logs_view
    assert ":show-run-details=\"true\"" in logs_view
    assert "run-detail-backdrop" in logs_view
    assert "run-detail-drawer" in logs_view
    assert "position: fixed" in logs_view
    assert "展开详情" in log_stream_panel
    assert "查看 Run 详情" in log_stream_panel
    assert "formatClock" in log_stream_panel
    assert "summary-tag" in log_stream_panel
    assert "primary-field" in log_stream_panel
    assert "最近 200 条 Steps" in run_detail_panel
    assert "activeRequestToken" in run_detail_panel
    assert "requestToken !== activeRequestToken" in run_detail_panel
    assert "apiGetFresh" in api_source
    assert "latest=true" in run_detail_panel
    assert ":show-details=\"false\"" in home_view
    assert ":show-run-details=\"false\"" in home_view


def test_webui_real_pages_migrate_to_shared_design_system() -> None:
    page_paths = [
        "webui/src/views/SoulView.vue",
        "webui/src/views/AdminsView.vue",
        "webui/src/views/PluginsView.vue",
        "webui/src/views/LogsView.vue",
        "webui/src/views/SystemView.vue",
        "webui/src/views/PromptsView.vue",
        "webui/src/views/ProvidersView.vue",
        "webui/src/views/ModelsView.vue",
        "webui/src/views/SkillsView.vue",
        "webui/src/views/SubagentsView.vue",
    ]

    for path in page_paths:
        source = Path(path).read_text(encoding="utf-8")
        assert "ds-page" in source, path
        assert "ds-panel" in source or "ds-hero" in source, path
        assert 'class="panel"' not in source, path


def test_webui_real_pages_admins_view_uses_editable_list_field() -> None:
    component_path = Path("webui/src/components/EditableListField.vue")
    admins_view_path = Path("webui/src/views/AdminsView.vue")

    assert component_path.exists()
    component_source = component_path.read_text(encoding="utf-8")
    admins_view_source = admins_view_path.read_text(encoding="utf-8")

    assert "defineProps" in component_source
    assert "@keydown.enter" in component_source
    assert "ds-field" in component_source
    assert 'textarea class="ds-textarea ds-mono"' not in component_source

    assert "EditableListField" in admins_view_source
    assert "admin_actor_ids" in admins_view_source
    assert 'split("\\n")' not in admins_view_source
    assert '<textarea class="ds-textarea ds-mono"' not in admins_view_source


def test_webui_real_pages_system_view_becomes_shared_system_entrypoint() -> None:
    system_view_source = Path("webui/src/views/SystemView.vue").read_text(encoding="utf-8")
    router_source = Path("webui/src/router.ts").read_text(encoding="utf-8")
    sidebar_source = Path("webui/src/components/AppSidebar.vue").read_text(encoding="utf-8")
    api_source = Path("webui/src/lib/api.ts").read_text(encoding="utf-8")

    assert "/api/system/configuration" in system_view_source
    assert "EditableListField" in system_view_source
    assert "高级信息 / 路径总览" in system_view_source
    assert "保存并尝试生效" in system_view_source
    assert "/api/runtime/reload-config" in system_view_source
    assert "apply_status" in system_view_source

    assert 'redirect: "/system"' in router_source
    assert 'to="/config/admins"' not in sidebar_source
    assert 'to="/system"' in sidebar_source

    assert "/api/system/configuration" in api_source
    assert '"/api/runtime/reload-config"' in api_source


def test_webui_real_pages_skills_view_supports_zip_upload() -> None:
    """Skills 页面应提供 zip 上传入口, API 层应支持 FormData。"""

    skills_view_source = Path("webui/src/views/SkillsView.vue").read_text(encoding="utf-8")
    api_source = Path("webui/src/lib/api.ts").read_text(encoding="utf-8")

    assert "上传 Skill 压缩包" in skills_view_source
    assert 'type="file"' in skills_view_source
    assert "apiPostFormData" in skills_view_source
    assert "FormData" in api_source


def test_webui_real_pages_schedule_view_registers_route_sidebar_and_fresh_api() -> None:
    schedule_view_source = Path("webui/src/views/SchedulesView.vue").read_text(encoding="utf-8")
    router_source = Path("webui/src/router.ts").read_text(encoding="utf-8")
    sidebar_source = Path("webui/src/components/AppSidebar.vue").read_text(encoding="utf-8")
    api_source = Path("webui/src/lib/api.ts").read_text(encoding="utf-8")

    assert 'path: "/schedules"' in router_source
    assert 'to="/schedules"' in sidebar_source
    assert "getSchedulesList" in api_source
    assert "apiGetFresh<ScheduleListResponse>" in api_source
    assert "data-schedule-create-button" in schedule_view_source
    assert "data-schedule-row" in schedule_view_source
    assert "data-schedule-create-modal" in schedule_view_source
    assert "data-schedule-next-fire" in schedule_view_source


async def test_schedule_page_supports_create_toggle_delete_and_visible_refresh(tmp_path: Path) -> None:
    ensure_webui_assets_built()

    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        webui_enabled=True,
        port=0,
        filesystem_enabled=True,
        base_dir=tmp_path,
    )
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    await components.control_plane.create_session(
        {
            "session_id": "qq:user:10001",
            "title": "调度测试会话",
            "template_id": "qq_private",
        }
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await components.app.start()
    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/schedules",
            width=1440,
            height=1080,
            wait_ms=1800,
            init_script="""
              window.confirm = () => true;
            """,
            script="""
              return (async () => {
                const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                const click = (selector) => document.querySelector(selector)?.click();
                const setValue = (selector, value) => {
                  const element = document.querySelector(selector);
                  if (!element) return false;
                  element.focus();
                  element.value = String(value);
                  element.dispatchEvent(new Event('input', { bubbles: true }));
                  element.dispatchEvent(new Event('change', { bubbles: true }));
                  return true;
                };

                click('[data-schedule-create-button]');
                await wait(200);
                const modalOpen = Boolean(document.querySelector('[data-schedule-create-modal]'));
                click('[data-schedule-session-option="qq:user:10001"]');
                click('[data-schedule-kind="interval"]');
                setValue('[data-schedule-interval-input]', 1);
                setValue('[data-schedule-note-input]', '网页创建的调度任务');
                click('[data-schedule-create-submit]');

                for (let index = 0; index < 40; index += 1) {
                  if (document.querySelector('[data-schedule-row]')) break;
                  await wait(100);
                }

                const row = document.querySelector('[data-schedule-row]');
                const taskId = row?.getAttribute('data-schedule-row') || '';
                const nextBefore = taskId
                  ? document.querySelector('[data-schedule-next-fire="' + taskId + '"]')?.textContent?.trim() || ''
                  : '';

                for (let index = 0; index < 40; index += 1) {
                  const last = taskId
                    ? document.querySelector('[data-schedule-last-fired="' + taskId + '"]')?.textContent?.trim() || ''
                    : '';
                  if (last && last !== '—') break;
                  await wait(100);
                }

                const lastAfterRefresh = taskId
                  ? document.querySelector('[data-schedule-last-fired="' + taskId + '"]')?.textContent?.trim() || ''
                  : '';

                click('[data-schedule-toggle="' + taskId + '"]');
                for (let index = 0; index < 20; index += 1) {
                  const rowText = row?.textContent || '';
                  if (rowText.includes('已暂停')) break;
                  await wait(100);
                }
                const pausedText = row?.textContent || '';

                click('[data-schedule-toggle="' + taskId + '"]');
                for (let index = 0; index < 20; index += 1) {
                  const rowText = row?.textContent || '';
                  if (rowText.includes('启用中')) break;
                  await wait(100);
                }
                const resumedText = row?.textContent || '';

                click('[data-schedule-delete="' + taskId + '"]');
                for (let index = 0; index < 20; index += 1) {
                  if (!document.querySelector('[data-schedule-row="' + taskId + '"]')) break;
                  await wait(100);
                }

                return {
                  title: document.querySelector('h1')?.textContent?.trim() || '',
                  modalOpen,
                  taskId,
                  nextBefore,
                  lastAfterRefresh,
                  pausedText,
                  resumedText,
                  remainingRows: document.querySelectorAll('[data-schedule-row]').length,
                };
              })();
            """,
        )

        assert result["title"] == "调度任务"
        assert result["modalOpen"] is True
        assert result["taskId"]
        assert result["nextBefore"]
        assert result["lastAfterRefresh"] != "—"
        assert "已暂停" in result["pausedText"]
        assert "启用中" in result["resumedText"]
        assert result["remainingRows"] == 0
    finally:
        await server.stop()
        await components.app.stop()


async def test_webui_real_pages_system_view_includes_render_bootstrap_guard_for_stale_cache(
    tmp_path: Path,
) -> None:
    ensure_webui_assets_built()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0, base_dir=tmp_path)
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
        stale_snapshot = {
            "meta": {"config_path": str(config_path.resolve())},
            "gateway": {
                "host": "127.0.0.1",
                "port": 8080,
                "timeout": 10,
                "token": "",
            },
            "filesystem": {
                "enabled": True,
                "base_dir": str(tmp_path.resolve()),
                "skill_catalog_dirs": [],
                "subagent_catalog_dirs": [],
                "configured_skill_catalog_dirs": None,
                "configured_subagent_catalog_dirs": None,
                "default_skill_catalog_dirs": ["./extensions/skills"],
                "default_subagent_catalog_dirs": ["./extensions/subagents"],
                "resolved_skill_catalog_dirs": [],
                "resolved_subagent_catalog_dirs": [],
            },
            "admins": {"admin_actor_ids": []},
            "paths": {
                "config_path": str(config_path.resolve()),
                "filesystem_base_dir": str(tmp_path.resolve()),
                "prompts_dir": str((tmp_path / "prompts").resolve()),
                "sessions_dir": str((tmp_path / "sessions").resolve()),
                "computer_root_dir": str((tmp_path / "runtime_data" / "workspaces").resolve()),
                "sticky_notes_dir": str((tmp_path / "runtime_data" / "sticky_notes").resolve()),
                "long_term_memory_storage_dir": str(
                    (tmp_path / "runtime_data" / "long_term_memory" / "lancedb").resolve()
                ),
                "resolved_skill_catalog_dirs": [],
                "resolved_subagent_catalog_dirs": [],
                "backend_session_path": str((tmp_path / "runtime_data" / "backend" / "session.json").resolve()),
            },
        }
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/system",
            width=1440,
            height=1200,
            wait_ms=900,
            init_script=f"""
              localStorage.setItem(
                'acabot.api.cache:/api/system/configuration',
                JSON.stringify({{
                  expiresAt: Date.now() + 60000,
                  value: {json.dumps(stale_snapshot)},
                }})
              );
              const originalFetch = window.fetch.bind(window);
              window.fetch = (input, init) => {{
                const rawUrl = typeof input === 'string' ? input : input.url;
                const path = new URL(rawUrl, window.location.origin).pathname;
                if (path === '/api/system/configuration') {{
                  return new Promise(() => {{}});
                }}
                return originalFetch(input, init);
              }};
            """,
            script="""
              return {
                bodyText: document.body.textContent || '',
                isLoading: (document.body.textContent || '').includes('正在加载系统配置'),
                hasRenderPanel: (document.body.textContent || '').includes('Render 默认配置'),
              };
            """,
        )

        assert result["isLoading"] is True
        assert result["hasRenderPanel"] is False
        assert "Render 默认配置" not in result["bodyText"]
    finally:
        await server.stop()


async def test_webui_real_pages_system_view_includes_render_bootstrap_guard_when_stale_cache_missing_filesystem(
    tmp_path: Path,
) -> None:
    ensure_webui_assets_built()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0, base_dir=tmp_path)
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
        stale_snapshot = {
            "meta": {"config_path": str(config_path.resolve())},
            "gateway": {
                "host": "127.0.0.1",
                "port": 8080,
                "timeout": 10,
                "token": "",
            },
            "render": {
                "width": DEFAULT_RENDER_VIEWPORT_WIDTH,
                "device_scale_factor": DEFAULT_RENDER_DEVICE_SCALE_FACTOR,
            },
            "admins": {"admin_actor_ids": []},
            "paths": {
                "config_path": str(config_path.resolve()),
                "filesystem_base_dir": str(tmp_path.resolve()),
                "prompts_dir": str((tmp_path / "prompts").resolve()),
                "sessions_dir": str((tmp_path / "sessions").resolve()),
                "computer_root_dir": str((tmp_path / "runtime_data" / "workspaces").resolve()),
                "sticky_notes_dir": str((tmp_path / "runtime_data" / "sticky_notes").resolve()),
                "long_term_memory_storage_dir": str(
                    (tmp_path / "runtime_data" / "long_term_memory" / "lancedb").resolve()
                ),
                "resolved_skill_catalog_dirs": [],
                "resolved_subagent_catalog_dirs": [],
                "backend_session_path": str((tmp_path / "runtime_data" / "backend" / "session.json").resolve()),
            },
        }
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/system",
            width=1440,
            height=1200,
            wait_ms=900,
            init_script=f"""
              window.__bootErrors = [];
              window.addEventListener('error', (event) => {{
                window.__bootErrors.push(event.message || 'unknown error');
              }});
              localStorage.setItem(
                'acabot.api.cache:/api/system/configuration',
                JSON.stringify({{
                  expiresAt: Date.now() + 60000,
                  value: {json.dumps(stale_snapshot)},
                }})
              );
              const originalFetch = window.fetch.bind(window);
              window.fetch = (input, init) => {{
                const rawUrl = typeof input === 'string' ? input : input.url;
                const path = new URL(rawUrl, window.location.origin).pathname;
                if (path === '/api/system/configuration') {{
                  return new Promise(() => {{}});
                }}
                return originalFetch(input, init);
              }};
            """,
            script="""
              return {
                bodyText: document.body.textContent || '',
                isLoading: (document.body.textContent || '').includes('正在加载系统配置'),
                hasRenderPanel: (document.body.textContent || '').includes('Render 默认配置'),
                bootErrors: Array.isArray(window.__bootErrors) ? window.__bootErrors : [],
              };
            """,
        )

        assert result["bootErrors"] == []
        assert result["isLoading"] is True
        assert result["hasRenderPanel"] is False
        assert "Render 默认配置" not in result["bodyText"]
    finally:
        await server.stop()


async def test_system_page_renders_malformed_system_snapshot_refresh_is_not_cached_when_paths_missing(
    tmp_path: Path,
) -> None:
    ensure_webui_assets_built()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0, base_dir=tmp_path)
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
            url=f"{base_url}/system",
            width=1440,
            height=1200,
            wait_ms=1200,
            init_script="""
              const originalFetch = window.fetch.bind(window);
              window.fetch = async (input, init) => {
                const rawUrl = typeof input === 'string' ? input : input.url;
                const path = new URL(rawUrl, window.location.origin).pathname;
                if (path === '/api/system/configuration') {
                  const response = await originalFetch(input, init);
                  const payload = await response.clone().json();
                  delete payload.data.paths;
                  return new Response(JSON.stringify(payload), {
                    status: response.status,
                    statusText: response.statusText,
                    headers: { 'Content-Type': 'application/json' },
                  });
                }
                return originalFetch(input, init);
              };
            """,
            script="""
              const bodyText = document.body.textContent || '';
              return {
                bodyText,
                hasLoadFailure: bodyText.includes('系统页加载失败'),
                hasRenderPanel: bodyText.includes('Render 默认配置'),
                cachedSnapshot: localStorage.getItem('acabot.api.cache:/api/system/configuration'),
              };
            """,
        )

        assert result["hasLoadFailure"] is True
        assert result["hasRenderPanel"] is False
        assert result["cachedSnapshot"] is None
    finally:
        await server.stop()


async def test_system_page_renders_when_filesystem_configured_dirs_are_null(tmp_path: Path) -> None:
    ensure_webui_assets_built()

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
gateway:
  host: "127.0.0.1"
  port: 8080

agent:

runtime:
  default_agent_id: "aca"
  filesystem:
    enabled: true
    base_dir: "{tmp_path}"
  profiles:
    aca:
      name: "Aca"
      prompt_ref: "prompt/default"
      admin_actor_ids:
        - "qq:private:123456"
  prompts:
    prompt/default: "hello"
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
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/system",
            width=1440,
            height=1200,
            wait_ms=2200,
            script="""
              const renderPanel = Array.from(document.querySelectorAll('article')).find((item) =>
                (item.textContent || '').includes('Render 默认配置')
              );
              const renderInputs = renderPanel ? Array.from(renderPanel.querySelectorAll('input')) : [];
              return {
                title: document.querySelector('h1')?.textContent?.trim() || '',
                bodyText: document.body.textContent || '',
                hasLoadFailure: (document.body.textContent || '').includes('系统页加载失败'),
                hasGatewayPanel: (document.body.textContent || '').includes('共享网关设置'),
                hasRenderPanel: Boolean(renderPanel),
                hasAdvancedSection: (document.body.textContent || '').includes('高级信息 / 路径总览'),
                renderWidth: Number(renderInputs[0]?.value || NaN),
                renderScale: Number(renderInputs[1]?.value || NaN),
              };
            """,
        )

        assert result["title"] == "系统设置"
        assert result["hasLoadFailure"] is False
        assert result["hasGatewayPanel"] is True
        assert result["hasRenderPanel"] is True
        assert result["hasAdvancedSection"] is True
        assert result["renderWidth"] == DEFAULT_RENDER_VIEWPORT_WIDTH
        assert result["renderScale"] == DEFAULT_RENDER_DEVICE_SCALE_FACTOR
        assert "not iterable" not in result["bodyText"]
    finally:
        await server.stop()


async def test_system_page_renders_render_save_uses_render_config_and_refreshes_from_system_snapshot(
    tmp_path: Path,
) -> None:
    ensure_webui_assets_built()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0, base_dir=tmp_path)
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
            url=f"{base_url}/system",
            width=1440,
            height=1200,
            wait_ms=2200,
            script="""
              return (async () => {
                const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                const calls = [];
                const originalFetch = window.fetch.bind(window);
                let sawRenderSave = false;
                window.fetch = async (input, init) => {
                  const rawUrl = typeof input === 'string' ? input : input.url;
                  const path = new URL(rawUrl, window.location.origin).pathname;
                  const method = (init?.method || (typeof input === 'object' && input?.method) || 'GET').toUpperCase();
                  const body = typeof init?.body === 'string' ? init.body : '';
                  calls.push({ path, method, body });
                  const response = await originalFetch(input, init);
                  if (path === '/api/render/config' && method === 'PUT') {
                    sawRenderSave = true;
                  }
                  if (sawRenderSave && path === '/api/system/configuration' && method === 'GET') {
                    const payload = await response.clone().json();
                    payload.data.render = {
                      width: 1777,
                      device_scale_factor: 3.3,
                    };
                    return new Response(JSON.stringify(payload), {
                      status: response.status,
                      statusText: response.statusText,
                      headers: { 'Content-Type': 'application/json' },
                    });
                  }
                  return response;
                };

                const renderPanel = Array.from(document.querySelectorAll('article')).find((item) =>
                  (item.textContent || '').includes('Render 默认配置')
                );
                const saveButton = renderPanel?.querySelector('button');
                const renderInputs = renderPanel ? Array.from(renderPanel.querySelectorAll('input')) : [];
                const setInputValue = (input, value) => {
                  input.focus();
                  input.value = String(value);
                  input.dispatchEvent(new Event('input', { bubbles: true }));
                  input.dispatchEvent(new Event('change', { bubbles: true }));
                };

                if (!renderPanel || !saveButton || renderInputs.length < 2) {
                  throw new Error('render panel not ready');
                }

                setInputValue(renderInputs[0], 1280);
                setInputValue(renderInputs[1], 2.5);
                saveButton.click();

                for (let index = 0; index < 50; index += 1) {
                  const bodyText = document.body.textContent || '';
                  if (bodyText.includes('Render 默认配置：已保存并已生效')) {
                    break;
                  }
                  await wait(100);
                }
                await wait(200);

                const refreshedPanel = Array.from(document.querySelectorAll('article')).find((item) =>
                  (item.textContent || '').includes('Render 默认配置')
                );
                const refreshedInputs = refreshedPanel ? Array.from(refreshedPanel.querySelectorAll('input')) : [];
                return {
                  calls,
                  feedbackText: document.querySelector('.ds-status')?.textContent?.trim() || '',
                  renderWidth: Number(refreshedInputs[0]?.value || NaN),
                  renderScale: Number(refreshedInputs[1]?.value || NaN),
                };
              })();
            """,
        )

        render_calls = [call for call in result["calls"] if call["path"] in {"/api/render/config", "/api/system/configuration"}]

        assert any(call["path"] == "/api/render/config" and call["method"] == "PUT" for call in render_calls)
        assert any(call["path"] == "/api/system/configuration" and call["method"] == "GET" for call in render_calls)
        assert any(
            call["path"] == "/api/render/config"
            and call["method"] == "PUT"
            and json.loads(call["body"]) == {"width": 1280, "device_scale_factor": 2.5}
            for call in render_calls
        )
        assert result["feedbackText"] == "Render 默认配置：已保存并已生效"
        assert result["renderWidth"] == 1777
        assert result["renderScale"] == 3.3
    finally:
        await server.stop()


async def test_models_page_renders_seeded_registry_targets_and_bindings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await _seed_model_registry(components.control_plane)
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/config/models",
            width=1440,
            height=1200,
            wait_ms=2200,
            script="""
              const metaValues = Array.from(document.querySelectorAll('.binding-meta-card .meta-value'));
              return {
                title: document.querySelector('h1')?.textContent?.trim() || '',
                presetIds: Array.from(document.querySelectorAll('.sidebar-column .list-item strong')).map((item) => item.textContent?.trim() || ''),
                targetIds: Array.from(document.querySelectorAll('.binding-sidebar .list-item strong')).map((item) => item.textContent?.trim() || ''),
                statusChips: Array.from(document.querySelectorAll('.binding-sidebar .state-chip')).map((item) => item.textContent?.trim() || ''),
                selectedModel: metaValues[1]?.textContent?.trim() || '',
                bodyText: document.body.textContent || '',
              };
            """,
        )

        assert result["title"] == "模型真源"
        assert "aca-main" in result["presetIds"]
        assert "ltm-embed" in result["presetIds"]
        assert "agent:aca" in result["targetIds"]
        assert "system:ltm_extract" in result["targetIds"]
        assert "resolved" in result["statusChips"]
        assert "gpt-4.1" in result["selectedModel"]
        assert "fallback" in result["bodyText"].lower()
    finally:
        await server.stop()


async def test_models_page_new_preset_flow_surfaces_draft_state_and_saves(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await _seed_model_registry(components.control_plane)
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/config/models",
            width=1440,
            height=1200,
            wait_ms=2200,
            script="""
              return new Promise((resolve) => {
                const addButton = Array.from(document.querySelectorAll('.sidebar-column button'))
                  .find((item) => item.textContent?.trim() === '+');
                  addButton?.click();
                  setTimeout(() => {
                    const summaryTitleOnCreate = document.querySelector('.summary-column h2')?.textContent?.trim() || '';
                    const modalOpen = Boolean(document.querySelector('.modal-shell'));
                    const sideSheetOpen = Boolean(document.querySelector('.side-sheet-shell'));
                    const sideSheetPosition = document.querySelector('.side-sheet-shell')
                      ? window.getComputedStyle(document.querySelector('.side-sheet-shell')).position
                      : '';
                    const fieldByLabel = (text) => Array.from(document.querySelectorAll('.modal-shell .ds-field'))
                      .find((field) => (field.querySelector('span')?.textContent || '').includes(text));
                  const saveButton = Array.from(document.querySelectorAll('.modal-actions button'))
                    .find((item) => item.textContent?.trim() === '保存');
                  const saveButtonRect = saveButton?.getBoundingClientRect();
                  const saveButtonVisible = Boolean(
                    saveButtonRect
                    && saveButtonRect.top >= 0
                    && saveButtonRect.bottom <= window.innerHeight
                  );
                  const presetIdInput = fieldByLabel('Preset ID')?.querySelector('input');
                  const modelInput = fieldByLabel('模型名')?.querySelector('input');
                  if (presetIdInput) {
                    presetIdInput.value = 'new-chat-main';
                    presetIdInput.dispatchEvent(new Event('input', { bubbles: true }));
                  }
                  if (modelInput) {
                    modelInput.value = 'gpt-4.1-mini';
                    modelInput.dispatchEvent(new Event('input', { bubbles: true }));
                  }
                  saveButton?.click();
                  setTimeout(() => {
                        resolve({
                          summaryTitleOnCreate,
                          modalOpen,
                          sideSheetOpen,
                          sideSheetPosition,
                          saveButtonVisible,
                          selectedTitleAfterSave: document.querySelector('.summary-column h2')?.textContent?.trim() || '',
                          presetIds: Array.from(document.querySelectorAll('.sidebar-column .list-item strong'))
                            .map((item) => item.textContent?.trim() || ''),
                      statusTexts: Array.from(document.querySelectorAll('.ds-status')).map((item) => item.textContent?.trim() || ''),
                    });
                  }, 1600);
                  }, 300);
                });
            """,
        )

        assert result["summaryTitleOnCreate"] == "新建模型 Preset"
        assert result["modalOpen"] is True
        assert result["sideSheetOpen"] is True
        assert result["sideSheetPosition"] == "fixed"
        assert result["saveButtonVisible"] is True
        assert result["selectedTitleAfterSave"] == "new-chat-main"
        assert "new-chat-main" in result["presetIds"]
        assert any("已保存" in item for item in result["statusTexts"])
    finally:
        await server.stop()


async def test_models_page_drawer_tones_down_ambient_glow_layers(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await _seed_model_registry(components.control_plane)
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/config/models",
            width=1440,
            height=1200,
            wait_ms=2200,
            script="""
              return new Promise((resolve) => {
                const openButton = Array.from(document.querySelectorAll('.summary-column button'))
                  .find((item) => (item.textContent || '').includes('打开 Preset 设置'));
                openButton?.click();
                setTimeout(() => {
                  const backdrop = document.querySelector('.side-sheet-backdrop');
                  const main = document.querySelector('.main');
                  const bodyBefore = getComputedStyle(document.body, '::before');
                  const mainBefore = main ? getComputedStyle(main, '::before') : null;
                  resolve({
                    overlayActive: document.body.classList.contains('overlay-active'),
                    backdropBackground: backdrop ? getComputedStyle(backdrop).backgroundImage : '',
                    bodyBeforeOpacity: bodyBefore.opacity || '',
                    mainBeforeOpacity: mainBefore?.opacity || '',
                  });
                }, 520);
              });
            """,
        )

        assert result["overlayActive"] is True
        assert "linear-gradient" not in result["backdropBackground"]
        assert float(result["bodyBeforeOpacity"]) <= 0.28
        assert float(result["mainBeforeOpacity"]) <= 0.24
    finally:
        await server.stop()


async def test_models_page_refreshes_binding_state_after_saving_bound_preset(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await _seed_model_registry(components.control_plane)
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/config/models",
            width=1440,
            height=1200,
            wait_ms=2200,
            script="""
              function findButton(containerSelector, text) {
                return Array.from(document.querySelectorAll(containerSelector))
                  .find((item) => (item.textContent || '').includes(text));
              }
              function fieldByLabel(text) {
                return Array.from(document.querySelectorAll('.modal-shell .ds-field'))
                  .find((field) => (field.querySelector('span')?.textContent || '').includes(text));
              }
              return new Promise((resolve) => {
                const presetButton = findButton('.sidebar-column .list-item', 'aca-main');
                presetButton?.click();
                setTimeout(() => {
                  const openButton = findButton('.summary-column button', '打开 Preset 设置');
                  openButton?.click();
                  setTimeout(() => {
                  const modelInput = fieldByLabel('模型名')?.querySelector('input');
                  if (modelInput) {
                    modelInput.value = 'gpt-4.1-refreshed';
                    modelInput.dispatchEvent(new Event('input', { bubbles: true }));
                  }
                  const saveButton = Array.from(document.querySelectorAll('.modal-actions button'))
                    .find((item) => item.textContent?.trim() === '保存');
                  saveButton?.click();
                    setTimeout(() => {
                      const metaValues = Array.from(document.querySelectorAll('.binding-meta-card .meta-value'))
                        .map((item) => item.textContent?.trim() || '');
                      resolve({
                        bindingState: metaValues[0] || '',
                        effectiveModel: metaValues[1] || '',
                        summaryModelText: document.querySelector('.summary-card strong:nth-of-type(1)')?.textContent?.trim() || '',
                        statusTexts: Array.from(document.querySelectorAll('.ds-status')).map((item) => item.textContent?.trim() || ''),
                      });
                    }, 1600);
                  }, 100);
                }, 100);
              });
            """,
        )

        assert result["bindingState"] == "resolved"
        assert result["effectiveModel"] == "gpt-4.1-refreshed"
        assert any("已保存" in item for item in result["statusTexts"])
    finally:
        await server.stop()


async def test_models_page_keeps_existing_binding_id_when_saving_binding(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await _seed_model_registry(components.control_plane)
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/config/models",
            width=1440,
            height=1200,
            wait_ms=2200,
            script="""
              return new Promise((resolve) => {
                const openButton = Array.from(document.querySelectorAll('.binding-editor button'))
                  .find((item) => item.textContent?.trim() === '打开 Binding 设置');
                openButton?.click();
                setTimeout(() => {
                  const bindingInput = document.querySelector('.modal-shell input[readonly]');
                  if (bindingInput) {
                    bindingInput.value = 'binding:renamed';
                    bindingInput.dispatchEvent(new Event('input', { bubbles: true }));
                  }
                  const saveButton = Array.from(document.querySelectorAll('.modal-actions button'))
                    .find((item) => item.textContent?.trim() === '保存 Binding');
                  saveButton?.click();
                  setTimeout(() => {
                    resolve({
                      bindingIdValue: bindingInput?.value || '',
                      isReadonly: Boolean(bindingInput?.readOnly),
                      errorTexts: Array.from(document.querySelectorAll('.ds-status.is-error')).map((item) => item.textContent?.trim() || ''),
                    });
                  }, 1200);
                }, 100);
              });
            """,
        )
        bindings = await asyncio.to_thread(request_json, base_url, "/api/models/bindings")
        agent_binding = next(item for item in bindings["data"] if item["binding"]["target_id"] == "agent:aca")

        assert result["isReadonly"] is True
        assert result["errorTexts"] == []
        assert agent_binding["binding"]["binding_id"] == "binding:agent:aca"
    finally:
        await server.stop()


async def test_memory_page_surfaces_long_term_memory_binding_health(tmp_path: Path) -> None:
    pytest.importorskip("lancedb")
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    runtime_conf = dict(config.get("runtime", {}) or {})
    runtime_conf["long_term_memory"] = {
        "enabled": True,
        "storage_dir": str(tmp_path / "ltm" / "lancedb"),
        "window_size": 48,
        "overlap_size": 8,
        "max_entries": 6,
        "extractor_version": "ltm-extractor-v1",
    }
    next_config = config.to_dict()
    next_config["runtime"] = runtime_conf
    config.replace(next_config)
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await _seed_model_registry(components.control_plane)
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/config/memory",
            width=1440,
            height=1200,
            wait_ms=2200,
            script="""
              const metaCards = Array.from(document.querySelectorAll('.ltm-meta-card'));
              return {
                title: document.querySelector('h1')?.textContent?.trim() || '',
                bindingState: metaCards[1]?.querySelector('.meta-value')?.textContent?.trim() || '',
                bodyText: document.body.textContent || '',
              };
            """,
        )

        assert result["title"] == "长期记忆与 Sticky Notes"
        assert result["bindingState"] == "ready"
        assert "system:ltm_extract" in result["bodyText"]
        assert "system:ltm_query_plan" in result["bodyText"]
        assert "system:ltm_embed" in result["bodyText"]
    finally:
        await server.stop()


async def test_memory_page_surfaces_initial_sticky_note_load_failure(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    async def failing_list_sticky_notes(*, entity_kind: str) -> dict[str, object]:
        _ = entity_kind
        raise RuntimeError("sticky list unavailable")

    components.control_plane.list_sticky_notes = failing_list_sticky_notes  # type: ignore[method-assign]
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/config/memory",
            width=1440,
            height=1100,
            wait_ms=2200,
            script="""
              return {
                errorText: document.querySelector('.error')?.textContent?.trim() || '',
                emptyText: document.querySelector('.main-column .empty')?.textContent?.trim() || '',
              };
            """,
        )

        assert "sticky list unavailable" in result["errorText"]
        assert result["emptyText"] == ""
    finally:
        await server.stop()


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
            payload={"entity_ref": "qq:group:42"},
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


async def test_memory_page_shows_validation_when_creating_note_with_invalid_entity_ref(tmp_path: Path) -> None:
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

        assert result["errorText"]
    finally:
        await server.stop()


async def test_sticky_notes_page_prefers_available_user_note_on_first_load(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    await components.control_plane.save_sticky_note_record(
        entity_ref="qq:user:1733064202",
        readonly="这是一条只读内容",
        editable="这是一条可编辑内容",
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/config/memory/sticky-notes",
            width=1440,
            height=1000,
            wait_ms=2200,
            script="""
              const textareas = Array.from(document.querySelectorAll('textarea'));
              return {
                listText: document.querySelector('.note-list')?.textContent?.trim() || '',
                emptyText: document.querySelector('.main-column .empty')?.textContent?.trim() || '',
                readonlyValue: textareas[0]?.value || '',
                editableValue: textareas[1]?.value || '',
              };
            """,
        )

        assert "qq:user:1733064202" in result["listText"]
        assert result["emptyText"] == ""
        assert result["readonlyValue"] == "这是一条只读内容"
        assert result["editableValue"] == "这是一条可编辑内容"
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


async def test_logs_page_renders_structured_summaries_tags_and_time(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    log_buffer = InMemoryLogBuffer()
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=log_buffer,
    )
    log_buffer.append(
        LogEntry(
            timestamp=1712418950.0,
            level="INFO",
            logger="acabot.runtime.app",
            kind="message",
            message="接收 <- 群聊 [肥猪交流群(1039173249)] [我是你坝(908900359)] 结果他笔试挂了 | 策略=record_only | prompt=prompt/record_only",
            extra={
                "group_name": "肥猪交流群",
                "group_id": "1039173249",
                "sender_name": "我是你坝",
                "sender_id": "908900359",
                "content_preview": "结果他笔试挂了",
                "run_mode": "record_only",
                "prompt_ref": "prompt/record_only",
                "run_id": "run:1",
            },
        )
    )
    log_buffer.append(
        LogEntry(
            timestamp=1712418951.0,
            level="INFO",
            logger="acabot.runtime.tool_broker",
            kind="tool_call",
            message="Tool call",
            extra={
                "tool_name": "message.send",
                "tool_arguments": {"content": "你好"},
                "run_id": "run:1",
            },
        )
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
            wait_ms=1200,
            script="""
              const tags = Array.from(document.querySelectorAll('.summary-tag')).map((item) => item.textContent?.trim() || '');
              const times = Array.from(document.querySelectorAll('.time-chip-inline')).map((item) => item.textContent?.trim() || '');
              const fields = Array.from(document.querySelectorAll('.primary-field')).map((item) => item.textContent?.trim() || '');
              return {
                bodyText: document.body.textContent || '',
                tags,
                times,
                fields,
              };
            """,
        )

        assert "MESSAGE" in result["tags"]
        assert "TOOL CALL" in result["tags"]
        assert any(value.count(":") >= 2 for value in result["times"])
        assert any("肥猪交流群" in value for value in result["fields"])
        assert any("我是你坝" in value for value in result["fields"])
        assert any("record_only" in value for value in result["fields"])
        assert "message.send" in result["bodyText"]
    finally:
        await server.stop()


async def test_memory_page_uses_search_list_create_layout_for_notes_panel(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    await components.control_plane.create_sticky_note(entity_ref="qq:group:42")
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
              const notesPanel = document.querySelector('.note-panel');
              const children = notesPanel
                ? Array.from(notesPanel.children).map((item) => item.className || item.tagName)
                : [];
              return {
                hasSearch: Boolean(document.querySelector('.note-search input')),
                hasList: Boolean(document.querySelector('.note-list')),
                hasCreate: Boolean(document.querySelector('.note-create')),
                children,
              };
            """,
        )

        assert result["hasSearch"] is True
        assert result["hasList"] is True
        assert result["hasCreate"] is True
    finally:
        await server.stop()


async def test_webui_defaults_to_dark_theme_and_exposes_system_mode(tmp_path: Path) -> None:
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
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/",
            width=1440,
            height=1000,
            script="""
              const selector = document.querySelector('[data-theme-mode]');
              const options = selector
                ? Array.from(selector.querySelectorAll('option')).map((item) => item.textContent?.trim() || '')
                : [];
              return {
                theme: document.documentElement.dataset.theme || '',
                themeMode: document.documentElement.dataset.themeMode || '',
                bodyText: document.body.textContent || '',
              };
            """,
        )

        assert result["theme"] == "dark"
        assert result["themeMode"] == "dark"
        assert "跟随系统" in result["bodyText"]
    finally:
        await server.stop()


async def test_memory_page_preserves_state_when_navigating_away_and_back(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    await components.control_plane.create_sticky_note(entity_ref="qq:group:42")
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
            wait_ms=2200,
            script="""
              const memoryLink = Array.from(document.querySelectorAll('a')).find((item) => item.textContent?.trim() === '记忆');
              const pluginsLink = Array.from(document.querySelectorAll('a')).find((item) => item.textContent?.trim() === '插件');
              const search = document.querySelector('.note-search input');
              search.value = 'qq:';
              search.dispatchEvent(new Event('input', { bubbles: true }));
              pluginsLink.click();
              return new Promise((resolve) => {
                setTimeout(() => {
                  memoryLink.click();
                  setTimeout(() => {
                    resolve({
                      searchValue: document.querySelector('.note-search input')?.value || '',
                    });
                  }, 200);
                }, 200);
              });
            """,
        )

        assert result["searchValue"] == "qq:"
    finally:
        await server.stop()


async def test_sessions_page_supports_creating_and_editing_session_owned_agent(tmp_path: Path) -> None:
    """会话页应支持编辑 session-owned agent，并把模型与工具配置真正保存到后端。"""

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0, filesystem_enabled=True, base_dir=tmp_path)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    await _seed_model_registry(components.control_plane)
    await components.control_plane.create_session(
        {
            "session_id": "qq:user:10001",
            "title": "私聊值守",
            "template_id": "qq_private",
        }
    )
    await components.control_plane.create_session(
        {
            "session_id": "qq:group:42",
            "title": "群聊值守",
            "template_id": "qq_group",
        }
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/sessions",
            width=1440,
            height=1000,
            wait_ms=2200,
            script="""
              return new Promise((resolve) => {
                const wait = (ms) => new Promise((done) => setTimeout(done, ms));
                const setInputValue = (input, value) => {
                  if (!input) return;
                  input.value = value;
                  input.dispatchEvent(new Event('input', { bubbles: true }));
                  input.dispatchEvent(new Event('change', { bubbles: true }));
                };
                const titleInput = () => Array.from(document.querySelectorAll('.sv-field'))
                  .find((item) => (item.querySelector('.sv-label')?.textContent || '').includes('标题'))
                  ?.querySelector('input');
                const findSectionButton = (title, label) => {
                  const section = Array.from(document.querySelectorAll('.sv-section'))
                    .find((item) => (item.querySelector('.sv-section-title')?.textContent || '').includes(title));
                  return Array.from(section?.querySelectorAll('button') || [])
                    .find((item) => (item.textContent || '').includes(label)) || null;
                };
                const findCapabilityCardButton = (title) => {
                  const card = Array.from(document.querySelectorAll('.sv-cap-card'))
                    .find((item) => (item.querySelector('.sv-cap-title')?.textContent || '').includes(title));
                  return card?.querySelector('button') || null;
                };

                (async () => {
                  const groupRow = Array.from(document.querySelectorAll('.sv-session-item'))
                    .find((item) => (item.textContent || '').includes('qq:group:42') || (item.textContent || '').includes('群聊值守'));
                  groupRow?.click();
                  await wait(700);

                  setInputValue(titleInput(), '群聊值守二号');
                  Array.from(document.querySelectorAll('.sv-actions .sv-btn-accent'))
                    .find((item) => (item.textContent || '').trim() === '保存')?.click();
                  await wait(700);

                  Array.from(document.querySelectorAll('.sv-tab'))
                    .find((item) => item.textContent?.trim() === 'Agent')?.click();
                  await wait(240);

                  findSectionButton('回复模型', '+ 添加')?.click();
                  await wait(180);
                  const replyOption = Array.from(document.querySelectorAll('.sv-choice-row'))
                    .find((item) => !!item.querySelector('.sv-choice-meta'));
                  const selectedReplyModel = replyOption?.querySelector('.sv-choice-meta')?.textContent?.trim() || '';
                  replyOption?.click();
                  await wait(220);

                  findCapabilityCardButton('工具')?.click();
                  await wait(180);
                  const toolOption = Array.from(document.querySelectorAll('.sv-choice-row'))
                    .find((item) => (item.querySelector('strong')?.textContent || '').trim() === 'read')
                    || Array.from(document.querySelectorAll('.sv-choice-row'))
                      .find((item) => item.querySelector('input[type="checkbox"]'));
                  const selectedTool = toolOption?.querySelector('strong')?.textContent?.trim() || '';
                  const toolCheckbox = toolOption?.querySelector('input[type="checkbox"]');
                  if (toolCheckbox && !toolCheckbox.checked) {
                    toolCheckbox.click();
                  }
                  Array.from(document.querySelectorAll('.sv-modal-foot .sv-btn-accent'))
                    .find((item) => (item.textContent || '').includes('完成'))?.click();
                  await wait(220);

                  Array.from(document.querySelectorAll('.sv-actions .sv-btn-accent'))
                    .find((item) => (item.textContent || '').includes('保存 Agent'))?.click();
                  await wait(900);

                  const createdAgent = await fetch('/api/sessions/qq%3Agroup%3A42/agent').then((resp) => resp.json());
                  const bindingSnapshot = await fetch('/api/models/bindings/' + encodeURIComponent('binding:agent:' + createdAgent?.data?.agent_id)).then((resp) => resp.json());
                  resolve({
                    bodyText: document.body.textContent || '',
                    sessionRows: Array.from(document.querySelectorAll('.sv-session-item'))
                      .map((item) => item.textContent?.trim() || ''),
                    activeTab: Array.from(document.querySelectorAll('.sv-tab'))
                      .find((item) => item.classList.contains('is-active'))?.textContent?.trim() || '',
                    heading: document.querySelector('.sv-session-title')?.textContent?.trim() || '',
                    selectedReplyModel,
                    selectedTool,
                    selectedToolChips: Array.from(document.querySelectorAll('.sv-cap-card .sv-chip'))
                      .map((item) => item.textContent?.trim() || ''),
                    agentPromptRef: createdAgent?.data?.prompt_ref || '',
                    bindingPresetIds: bindingSnapshot?.data?.binding?.preset_ids || [],
                    agentVisibleTools: createdAgent?.data?.visible_tools || [],
                    statusTexts: Array.from(document.querySelectorAll('.sv-toast, .ds-status'))
                      .map((item) => item.textContent?.trim() || ''),
                  });
                })();
              });
            """,
        )

        assert "会话" in result["bodyText"]
        assert any("群聊值守二号" in item for item in result["sessionRows"]) or "群聊值守二号" in result["bodyText"]
        assert result["activeTab"] == "Agent"
        assert result["heading"] == "群聊值守二号"
        assert result["selectedReplyModel"]
        assert result["selectedReplyModel"] in result["bindingPresetIds"]
        assert result["selectedTool"]
        assert result["selectedTool"] in result["selectedToolChips"]
        assert result["agentPromptRef"]
        assert result["selectedTool"] in result["agentVisibleTools"]
        assert any("已保存" in item for item in result["statusTexts"])
    finally:
        await server.stop()


async def test_sessions_page_loads_existing_reply_model_binding_for_session_agent(tmp_path: Path) -> None:
    """会话页打开已有 session 时, 应显示 frontstage agent 已绑定的回复模型。"""

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0, filesystem_enabled=True, base_dir=tmp_path)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        log_buffer=InMemoryLogBuffer(),
    )
    await _seed_model_registry(components.control_plane)
    created = await components.control_plane.create_session(
        {
            "session_id": "qq:user:10002",
            "title": "已有模型会话",
            "template_id": "qq_private",
        }
    )
    agent_id = str(created["agent"]["agent_id"])
    await components.control_plane.upsert_model_binding(
        ModelBinding(
            binding_id=f"binding:agent:{agent_id}",
            target_id=f"agent:{agent_id}",
            preset_ids=["aca-main"],
        )
    )
    server = RuntimeHttpApiServer(config=config, control_plane=components.control_plane)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        result = await asyncio.to_thread(
            run_page_script,
            url=f"{base_url}/sessions",
            width=1440,
            height=1000,
            wait_ms=2200,
            script="""
              return new Promise((resolve) => {
                setTimeout(() => {
                  const agentTab = Array.from(document.querySelectorAll('.sv-tab'))
                    .find((item) => item.textContent?.trim() === 'Agent');
                  agentTab?.click();

                  let attempts = 0;
                  const collect = () => {
                    const presetIds = Array.from(document.querySelectorAll('.sv-model-list .sv-model-id'))
                      .map((item) => item.textContent?.trim() || '');
                    const presetNames = Array.from(document.querySelectorAll('.sv-model-list .sv-model-name'))
                      .map((item) => item.textContent?.trim() || '');
                    const emptyTexts = Array.from(document.querySelectorAll('.sv-cap-empty'))
                      .map((item) => item.textContent?.trim() || '');
                    if (presetIds.length > 0 || attempts >= 30) {
                      resolve({
                        presetIds,
                        presetNames,
                        emptyTexts,
                        bodyText: document.body.textContent || '',
                      });
                      return;
                    }
                    attempts += 1;
                    setTimeout(collect, 120);
                  };
                  collect();
                }, 260);
              });
            """,
        )

        assert result["presetIds"] == ["aca-main"]
        assert "gpt-4.1" in result["presetNames"]
        assert "未选择回复模型" not in result["bodyText"]
    finally:
        await server.stop()


async def test_runtime_http_api_server_uploads_skill_zip_and_refreshes_catalog(tmp_path: Path) -> None:
    """上传 zip 后, skills 列表应立即出现新安装的 skill。"""

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
agent:
  system_prompt: "You are Aca."
runtime:
  default_agent_id: "aca"
  filesystem:
    base_dir: "{tmp_path}"
  profiles:
    aca:
      name: "Aca"
      prompt_ref: "prompt/aca"
  prompts:
    prompt/aca: "hello"
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

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr(
            "uploaded-demo-skill/SKILL.md",
            "---\nname: 上传演示 Skill\ndescription: 用于验证 zip 上传安装。\n---\n\n# 上传演示\n",
        )

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"
        uploaded = await asyncio.to_thread(
            request_multipart,
            base_url,
            "/api/skills/upload",
            files={
                "file": (
                    "uploaded-demo-skill.zip",
                    zip_buffer.getvalue(),
                    "application/zip",
                )
            },
        )
        listed = await asyncio.to_thread(request_json, base_url, "/api/skills")
    finally:
        await server.stop()

    assert uploaded["ok"] is True
    assert uploaded["data"]["installed_skill"]["skill_name"] == "uploaded-demo-skill"
    assert any(item["skill_name"] == "uploaded-demo-skill" for item in listed["data"])
    assert (tmp_path / "extensions" / "skills" / "uploaded-demo-skill" / "SKILL.md").exists()
