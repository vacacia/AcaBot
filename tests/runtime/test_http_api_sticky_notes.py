"""sticky note HTTP API 测试."""

from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from acabot.config import Config
from acabot.runtime import RuntimeHttpApiServer, build_runtime_components

from .test_bootstrap import FakeAgent, FakeAgentResponse, FakeGateway


def _request_json(base_url: str, path: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    raw_payload = None
    headers = {}
    if payload is not None:
        raw_payload = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url}{path}", data=raw_payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8"))


def _server(tmp_path) -> RuntimeHttpApiServer:
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "runtime_root": str(tmp_path / ".acabot-runtime"),
                "webui": {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": 0,
                },
            },
        }
    )
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    return RuntimeHttpApiServer(config=config, control_plane=components.control_plane)


async def test_runtime_http_api_sticky_note_endpoints_use_entity_ref_contract(tmp_path) -> None:
    server = _server(tmp_path)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"

        status, created = await asyncio.to_thread(
            _request_json,
            base_url,
            "/api/memory/sticky-notes/item",
            method="POST",
            payload={"entity_ref": "qq:user:10001"},
        )
        assert status == 200
        assert created["data"]["entity_ref"] == "qq:user:10001"

        status, saved = await asyncio.to_thread(
            _request_json,
            base_url,
            "/api/memory/sticky-notes/item",
            method="PUT",
            payload={
                "entity_ref": "qq:user:10001",
                "readonly": "用户名字叫阿卡西亚",
                "editable": "喜欢直接结论",
            },
        )
        assert status == 200
        assert saved["data"]["readonly"] == "用户名字叫阿卡西亚"
        assert saved["data"]["editable"] == "喜欢直接结论"

        status, listed = await asyncio.to_thread(
            _request_json,
            base_url,
            "/api/memory/sticky-notes?entity_kind=user",
        )
        assert status == 200
        assert listed["data"]["entity_kind"] == "user"
        assert listed["data"]["items"][0]["entity_ref"] == "qq:user:10001"

        status, loaded = await asyncio.to_thread(
            _request_json,
            base_url,
            "/api/memory/sticky-notes/item?entity_ref=qq:user:10001",
        )
        assert status == 200
        assert loaded["data"]["entity_ref"] == "qq:user:10001"
        assert loaded["data"]["readonly"] == "用户名字叫阿卡西亚"

        status, deleted = await asyncio.to_thread(
            _request_json,
            base_url,
            "/api/memory/sticky-notes/item?entity_ref=qq:user:10001",
            method="DELETE",
        )
        assert status == 200
        assert deleted["data"] == {"deleted": True}
    finally:
        await server.stop()


async def test_runtime_http_api_sticky_note_rejects_invalid_entity_ref(tmp_path) -> None:
    server = _server(tmp_path)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"

        status, result = await asyncio.to_thread(
            _request_json,
            base_url,
            "/api/memory/sticky-notes/item",
            method="POST",
            payload={"entity_ref": "thread:front:qq:group:1"},
        )

        assert status == 400
        assert result["ok"] is False
    finally:
        await server.stop()


async def test_runtime_http_api_sticky_note_rejects_invalid_entity_kind(tmp_path) -> None:
    server = _server(tmp_path)

    await server.start()
    try:
        port = server._httpd.server_address[1]  # type: ignore[union-attr]
        base_url = f"http://127.0.0.1:{port}"

        status, result = await asyncio.to_thread(
            _request_json,
            base_url,
            "/api/memory/sticky-notes?entity_kind=thread",
        )

        assert status == 400
        assert result["ok"] is False
    finally:
        await server.stop()
