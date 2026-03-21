from acabot.runtime import AgentProfile, ComputerPolicy, CommandExecutionResult, WorkspaceFileEntry
from acabot.runtime.plugins.computer_tool_adapter import ComputerToolAdapterPlugin
from acabot.runtime.tool_broker import ToolExecutionContext
from acabot.types import EventSource


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id="run:1",
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="aca",
        target=EventSource(platform="qq", message_type="private", user_id="10001", group_id=None),
        profile=AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            default_model="test-model",
            computer_policy=ComputerPolicy(),
            config={},
        ),
        world_view=object(),
        metadata={},
    )


async def test_computer_tool_adapter_ls_serializes_slots_dataclass() -> None:
    class Runtime:
        async def ensure_loaded_skills_mirrored(self, *args, **kwargs):
            _ = args, kwargs

        async def list_world_entries(self, **kwargs):
            assert kwargs["world_path"] == "/workspace"
            assert kwargs["world_view"] is not None
            return [WorkspaceFileEntry(path="/workspace/demo.txt", kind="file", size_bytes=12, modified_at=1)]

    plugin = ComputerToolAdapterPlugin()
    plugin._computer_runtime = Runtime()

    result = await plugin._ls({"path": "/workspace"}, _ctx())

    assert result.raw == {
        "items": [
            {
                "path": "/workspace/demo.txt",
                "kind": "file",
                "size_bytes": 12,
                "modified_at": 1,
            }
        ]
    }


async def test_computer_tool_adapter_exec_serializes_slots_dataclass() -> None:
    class Runtime:
        async def ensure_loaded_skills_mirrored(self, *args, **kwargs):
            _ = args, kwargs

        async def exec_once(self, **kwargs):
            assert kwargs["world_view"] is not None
            return CommandExecutionResult(
                ok=True,
                exit_code=0,
                stdout_excerpt="hello",
                stderr_excerpt="",
                stdout_truncated=False,
                stderr_truncated=False,
                metadata={"backend": "host"},
            )

    plugin = ComputerToolAdapterPlugin()
    plugin._computer_runtime = Runtime()

    result = await plugin._exec({"command": "echo hello"}, _ctx())

    assert result.raw == {
        "ok": True,
        "exit_code": 0,
        "stdout_excerpt": "hello",
        "stderr_excerpt": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "metadata": {"backend": "host"},
    }
