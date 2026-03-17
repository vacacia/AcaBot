from acabot.runtime.backend.pi_adapter import PiBackendAdapter


async def test_pi_adapter_exposes_minimal_backend_api():
    adapter = PiBackendAdapter(command=["pi", "--mode", "rpc"])
    await adapter.ensure_started()
    assert adapter.started is True

    prompt_result = await adapter.prompt("hello")
    assert prompt_result["transport"] == "rpc"
    assert prompt_result["command"] == ["pi", "--mode", "rpc"]
    assert prompt_result["prompt"] == "hello"

    fork_result = await adapter.fork_from_stable_checkpoint("hello")
    assert fork_result["transport"] == "rpc"
    assert fork_result["prompt"] == "hello"
    assert fork_result["forked"] is True

    await adapter.dispose()
    assert adapter.started is False
