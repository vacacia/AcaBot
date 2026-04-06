"""验证 WebUI HTTP API 对 HEAD 探测的兼容性。"""

import asyncio
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from acabot.config import Config
from acabot.runtime import build_runtime_components
from acabot.runtime.control.http_api import RuntimeHttpApiServer
from acabot.runtime.control.log_buffer import InMemoryLogBuffer

from .test_outbox import FakeGateway
from .test_webui_api import FakeAgent, FakeAgentResponse, _write_config


def request_head(base_url: str, path: str) -> tuple[int, dict[str, str], bytes]:
    """发送一个 HEAD 请求并返回状态、响应头和响应体。"""

    request = Request(f"{base_url}{path}", method="HEAD")
    try:
        with urlopen(request, timeout=5) as response:
            return int(response.status), dict(response.headers.items()), response.read()
    except HTTPError as exc:
        return int(exc.code), dict(exc.headers.items()), exc.read()


async def test_runtime_http_api_server_supports_head_for_static_and_api(tmp_path: Path) -> None:
    """静态页和 API 都应该接受 HEAD，便于 VSCode 端口探测。"""

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

        static_status, static_headers, static_body = await asyncio.to_thread(request_head, base_url, "/")
        assert static_status == 200
        assert static_body == b""
        assert "text/html" in str(static_headers.get("Content-Type", ""))
        assert "HEAD" in str(static_headers.get("Access-Control-Allow-Methods", ""))

        api_status, api_headers, api_body = await asyncio.to_thread(request_head, base_url, "/api/status")
        assert api_status == 200
        assert api_body == b""
        assert "application/json" in str(api_headers.get("Content-Type", ""))
        assert "HEAD" in str(api_headers.get("Access-Control-Allow-Methods", ""))
    finally:
        await server.stop()
