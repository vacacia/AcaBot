from pathlib import Path

from acabot.runtime.backend.bridge import BackendBridge
from acabot.runtime.backend.contracts import BackendRequest, BackendSourceRef
from acabot.runtime.backend.pi_adapter import PiBackendAdapter
from acabot.runtime.backend.session import BackendSessionBindingStore, ConfiguredBackendSessionService
import pytest


class FakeSessionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def send_change(self, summary: str) -> object:
        self.calls.append(("change", summary))
        return {"kind": "change", "summary": summary}

    async def fork_query_from_stable_checkpoint(self, summary: str) -> object:
        self.calls.append(("query", summary))
        return {"kind": "query", "summary": summary}


def _build_request(*, request_kind: str, summary: str) -> BackendRequest:
    return BackendRequest(
        request_id="req:1",
        source_kind="frontstage_internal",
        request_kind=request_kind,
        source_ref=BackendSourceRef(
            thread_id="thread:1",
            channel_scope="qq:group:123",
            event_id="event:1",
        ),
        summary=summary,
        created_at=123,
    )


async def test_backend_bridge_routes_frontstage_query_to_query_fork():
    session = FakeSessionService()
    bridge = BackendBridge(session=session)

    result = await bridge.handle_frontstage_request(
        _build_request(request_kind="query", summary="查询当前配置")
    )

    assert result == {"kind": "query", "summary": "查询当前配置"}
    assert session.calls == [("query", "查询当前配置")]


async def test_backend_bridge_routes_frontstage_change_to_canonical_session():
    session = FakeSessionService()
    bridge = BackendBridge(session=session)

    result = await bridge.handle_frontstage_request(
        _build_request(request_kind="change", summary="修改当前配置")
    )

    assert result == {"kind": "change", "summary": "修改当前配置"}
    assert session.calls == [("change", "修改当前配置")]


async def test_backend_bridge_routes_admin_direct_query_to_query_fork():
    session = FakeSessionService()
    bridge = BackendBridge(session=session)

    result = await bridge.handle_admin_direct(
        _build_request(request_kind="query", summary="管理员查询配置")
    )

    assert result == {"kind": "query", "summary": "管理员查询配置"}
    assert session.calls == [("query", "管理员查询配置")]


async def test_backend_bridge_rejects_unknown_request_kind():
    session = FakeSessionService()
    bridge = BackendBridge(session=session)

    with pytest.raises(ValueError):
        await bridge.handle_frontstage_request(
            _build_request(request_kind="unknown", summary="bad request")
        )

    assert session.calls == []


async def test_backend_bridge_with_real_pi_service_handles_change_and_query(tmp_path: Path):
    adapter = PiBackendAdapter(
        command=["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
        cwd=tmp_path,
    )
    session = ConfiguredBackendSessionService(
        binding_store=BackendSessionBindingStore(tmp_path / "session.json"),
        adapter=adapter,
    )
    bridge = BackendBridge(session=session)

    change_result = await bridge.handle_frontstage_request(
        _build_request(request_kind="change", summary="Reply with exactly: BRIDGE_CHANGE_OK")
    )
    assert "BRIDGE_CHANGE_OK" in change_result["text"]

    query_result = await bridge.handle_frontstage_request(
        _build_request(request_kind="query", summary="Reply with exactly: BRIDGE_QUERY_OK")
    )
    assert query_result["forked"] is True
    assert "BRIDGE_QUERY_OK" in query_result["text"]

    await adapter.dispose()
