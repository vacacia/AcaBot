from __future__ import annotations

from pathlib import Path

from acabot.runtime.backend.pi_adapter import PiBackendAdapter


async def test_pi_adapter_starts_real_pi_and_gets_state(tmp_path: Path):
    adapter = PiBackendAdapter(
        command=["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
        cwd=tmp_path,
    )

    state = await adapter.ensure_started()

    assert adapter.started is True
    assert state["type"] == "response"
    assert state["command"] == "get_state"
    assert state["success"] is True
    assert state["data"]["isStreaming"] is False
    assert state["data"]["sessionId"]

    await adapter.dispose()
    assert adapter.started is False


async def test_pi_adapter_prompt_gets_real_response_from_pi(tmp_path: Path):
    adapter = PiBackendAdapter(
        command=["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
        cwd=tmp_path,
    )

    result = await adapter.prompt(
        "Reply with exactly: ACABOT_PI_RPC_OK"
    )

    assert result["transport"] == "rpc"
    assert result["session_id"]
    assert "ACABOT_PI_RPC_OK" in result["text"]
    assert result["response"]["command"] == "prompt"
    assert result["response"]["success"] is True

    state_after = await adapter.ensure_started()
    assert result["session_id"] == state_after["data"]["sessionId"]
    assert result["session_file"] == state_after["data"].get("sessionFile", "")

    await adapter.dispose()


async def test_pi_adapter_query_path_uses_real_fork(tmp_path: Path):
    adapter = PiBackendAdapter(
        command=["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
        cwd=tmp_path,
    )

    await adapter.prompt("Remember this exact token: BACKEND_CANONICAL_TOKEN_123")
    result = await adapter.fork_from_stable_checkpoint(
        "Repeat the exact token from the previous user message. Reply with exactly: BACKEND_CANONICAL_TOKEN_123"
    )

    assert result["transport"] == "rpc"
    assert result["forked"] is True
    assert result["session_id"]
    assert "BACKEND_CANONICAL_TOKEN_123" in result["text"]

    await adapter.dispose()
