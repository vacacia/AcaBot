from pathlib import Path

import pytest

from acabot.runtime.backend.persona import build_backend_persona_prompt
from acabot.runtime.backend.pi_adapter import PiBackendAdapter
from acabot.runtime.backend.session import (
    BackendSessionBindingStore,
    BackendSessionService,
    ConfiguredBackendSessionService,
)


def test_backend_session_binding_load_returns_none_when_file_missing(tmp_path: Path):
    store = BackendSessionBindingStore(tmp_path / "missing.json")
    assert store.load() is None


def test_backend_session_binding_roundtrip(tmp_path: Path):
    store = BackendSessionBindingStore(tmp_path / "session.json")
    store.save(
        backend_id="main",
        transport="rpc",
        pi_session_id="pi-session-1",
        session_file="/tmp/pi-session-1.jsonl",
        created_at=1,
        last_active_at=2,
        status="ready",
    )
    binding = store.load()
    assert binding.backend_id == "main"
    assert binding.pi_session_id == "pi-session-1"
    assert binding.session_file == "/tmp/pi-session-1.jsonl"


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


async def test_configured_backend_session_service_uses_real_adapter(tmp_path: Path):
    binding_store = BackendSessionBindingStore(tmp_path / "session.json")
    adapter = PiBackendAdapter(
        command=["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
        cwd=tmp_path,
    )
    service = ConfiguredBackendSessionService(
        binding_store=binding_store,
        adapter=adapter,
    )

    assert service.is_configured() is True

    binding = await service.ensure_backend_session()
    assert binding.backend_id == "main"
    assert binding.transport == "rpc"
    assert binding.pi_session_id
    assert binding_store.load() is not None

    change_result = await service.send_change("Reply with exactly: BACKEND_CHANGE_OK")
    assert "BACKEND_CHANGE_OK" in change_result["text"]

    query_result = await service.fork_query_from_stable_checkpoint(
        "Reply with exactly: BACKEND_QUERY_OK"
    )
    assert query_result["forked"] is True
    assert "BACKEND_QUERY_OK" in query_result["text"]

    await adapter.dispose()


async def test_configured_backend_session_service_rejects_raw_pi_session_commands(
    tmp_path: Path,
):
    binding_store = BackendSessionBindingStore(tmp_path / "session.json")
    adapter = PiBackendAdapter(
        command=["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
        cwd=tmp_path,
    )
    service = ConfiguredBackendSessionService(
        binding_store=binding_store,
        adapter=adapter,
    )

    binding = await service.ensure_backend_session()

    with pytest.raises(ValueError):
        await service.send_change("/new")

    reloaded = binding_store.load()
    assert reloaded is not None
    assert reloaded.pi_session_id == binding.pi_session_id

    await adapter.dispose()


async def test_configured_backend_session_service_persists_prompt_final_state(
    tmp_path: Path,
):
    binding_store = BackendSessionBindingStore(tmp_path / "session.json")
    adapter = PiBackendAdapter(
        command=["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
        cwd=tmp_path,
    )
    service = ConfiguredBackendSessionService(
        binding_store=binding_store,
        adapter=adapter,
    )

    await service.ensure_backend_session()
    result = await service.send_change("Reply with exactly: FINAL_STATE_OK")
    reloaded = binding_store.load()

    assert reloaded is not None
    assert reloaded.pi_session_id == result["session_id"]
    assert reloaded.session_file == result["session_file"]

    await adapter.dispose()


async def test_configured_backend_session_service_restores_canonical_session_after_restart(
    tmp_path: Path,
):
    binding_store = BackendSessionBindingStore(tmp_path / "session.json")

    adapter1 = PiBackendAdapter(
        command=["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
        cwd=tmp_path,
    )
    service1 = ConfiguredBackendSessionService(
        binding_store=binding_store,
        adapter=adapter1,
    )

    binding1 = await service1.ensure_backend_session()
    generated = await service1.send_change(
        "Generate a random-looking 40-character uppercase alphanumeric token. "
        "Reply with the token only and nothing else."
    )
    token = str(generated["text"]).strip()
    assert len(token) >= 24
    assert " " not in token
    await adapter1.dispose()

    adapter2 = PiBackendAdapter(
        command=["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
        cwd=tmp_path,
    )
    service2 = ConfiguredBackendSessionService(
        binding_store=binding_store,
        adapter=adapter2,
    )

    binding2 = await service2.ensure_backend_session()
    assert binding2.pi_session_id == binding1.pi_session_id

    result = await service2.send_change(
        "What exact token did you generate in your previous reply before this message? "
        "Reply with that token only and nothing else."
    )
    assert str(result["text"]).strip() == token

    await adapter2.dispose()
