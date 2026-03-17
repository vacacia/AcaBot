from pathlib import Path

import pytest

from acabot.runtime.backend.persona import build_backend_persona_prompt
from acabot.runtime.backend.session import BackendSessionBindingStore, BackendSessionService


def test_backend_session_binding_load_returns_none_when_file_missing(tmp_path: Path):
    store = BackendSessionBindingStore(tmp_path / "missing.json")
    assert store.load() is None


def test_backend_session_binding_roundtrip(tmp_path: Path):
    store = BackendSessionBindingStore(tmp_path / "session.json")
    store.save(
        backend_id="main",
        transport="rpc",
        pi_session_id="pi-session-1",
        created_at=1,
        last_active_at=2,
        status="ready",
    )
    binding = store.load()
    assert binding.backend_id == "main"
    assert binding.pi_session_id == "pi-session-1"


def test_backend_persona_prompt_captures_guardrails():
    prompt = build_backend_persona_prompt()
    assert "Aca maintainer" in prompt
    assert "query" in prompt
    assert "change" in prompt
    assert "普通用户不直接和后台交互" in prompt
    assert "raw pi session 命令不作为默认后台控制面" in prompt


async def test_backend_session_service_methods_raise_not_implemented():
    service = BackendSessionService()
    with pytest.raises(NotImplementedError):
        await service.ensure_backend_session()
    with pytest.raises(NotImplementedError):
        await service.send_change("change config")
    with pytest.raises(NotImplementedError):
        await service.fork_query_from_stable_checkpoint("hello")
