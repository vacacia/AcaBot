"""builtin tool 注册链测试.

这个文件只测试一件事: runtime 自带的 core tool 不再走 plugin 生命周期.
它和下面这些组件直接相关:
- `runtime.bootstrap`: 负责启动时注册 builtin tool
- `runtime.tool_broker`: 保存最终的工具目录
- `runtime.plugin_runtime_host`: 只负责真正的外部 plugin 管理, 不该影响 core tool
- `runtime.control.config_control_plane`: 热刷新配置时, core tool 也不该消失
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from acabot.config import Config
from acabot.runtime import ResolvedAgent, ComputerPolicy, ToolBroker, ToolExecutionContext, build_runtime_components
from acabot.runtime.builtin_tools.computer import BuiltinComputerToolSurface
from acabot.runtime.builtin_tools.message import BUILTIN_MESSAGE_TOOL_SOURCE, BuiltinMessageToolSurface
from acabot.types import EventSource

from tests.runtime._agent_fakes import FakeAgent, FakeAgentResponse
from tests.runtime.test_outbox import FakeGateway


# region helper

def _tool_sources(components) -> dict[str, str]:
    """返回当前 ToolBroker 里每个工具的来源.

    Args:
        components: `build_runtime_components()` 返回的运行时组件集合.

    Returns:
        dict[str, str]: `tool_name -> source` 映射.
    """

    return {
        item["name"]: str(item["source"])
        for item in components.tool_broker.list_registered_tools()
    }


class _SpyComputerRuntime:
    """只暴露 builtin computer 新接口的测试用 runtime.

    Attributes:
        read_calls (list[dict[str, object]]): 收到的 read 调用记录.
        write_calls (list[dict[str, object]]): 收到的 write 调用记录.
        edit_calls (list[dict[str, object]]): 收到的 edit 调用记录.
        bash_calls (list[dict[str, object]]): 收到的 bash 调用记录.
        ensure_loaded_skill_calls (int): 旧 skill 镜像 helper 被调了多少次.
    """

    def __init__(self) -> None:
        """初始化测试用 runtime 的调用记录."""

        self.read_calls: list[dict[str, object]] = []
        self.write_calls: list[dict[str, object]] = []
        self.edit_calls: list[dict[str, object]] = []
        self.bash_calls: list[dict[str, object]] = []
        self.ensure_loaded_skill_calls = 0
        self.read_result_content: object = "content:/workspace/demo.txt"

    async def read_world_path(self, *, world_view, world_path: str, offset=None, limit=None):
        """记录 read_world_path 调用, 再回一份测试用读取结果.

        Args:
            world_view: 当前 world view.
            world_path (str): 目标 world path.
            offset: 起始行号.
            limit: 最多返回多少行.

        Returns:
            SimpleNamespace: 测试里要用的读取返回值.
        """

        self.read_calls.append(
            {
                "world_view": world_view,
                "world_path": world_path,
                "offset": offset,
                "limit": limit,
            }
        )
        text = self.read_result_content if isinstance(self.read_result_content, str) else ""
        return SimpleNamespace(
            world_path=world_path,
            text=text,
            content=self.read_result_content,
        )

    async def write_world_path(self, *, world_view, world_path: str, content: str):
        """记录 write_world_path 调用, 再回一份测试用写入结果.

        Args:
            world_view: 当前 world view.
            world_path (str): 目标 world path.
            content (str): 要写入的文本.

        Returns:
            SimpleNamespace: 测试里要用的写入返回值.
        """

        self.write_calls.append(
            {
                "world_view": world_view,
                "world_path": world_path,
                "content": content,
            }
        )
        return SimpleNamespace(world_path=world_path, size_bytes=len(content.encode("utf-8")))

    async def edit_world_path(self, *, world_view, world_path: str, old_text: str, new_text: str):
        """记录 edit_world_path 调用, 再回一份测试用编辑结果.

        Args:
            world_view: 当前 world view.
            world_path (str): 目标 world path.
            old_text (str): 要匹配的旧文本.
            new_text (str): 要写入的新文本.

        Returns:
            SimpleNamespace: 测试里要用的编辑返回值.
        """

        self.edit_calls.append(
            {
                "world_view": world_view,
                "world_path": world_path,
                "old_text": old_text,
                "new_text": new_text,
            }
        )
        return SimpleNamespace(
            world_path=world_path,
            diff="-1 old\n+1 new",
            first_changed_line=1,
        )

    async def bash_world(
        self,
        *,
        thread_id: str,
        run_id: str,
        command: str,
        timeout=None,
        world_view,
        policy,
    ):
        """记录 bash_world 调用, 再回一份测试用命令结果.

        Args:
            thread_id (str): 当前线程 ID.
            run_id (str): 当前 run ID.
            command (str): 要执行的命令.
            timeout: 可选超时秒数.
            world_view: 当前 world view.
            policy: 当前 computer policy.

        Returns:
            SimpleNamespace: 测试里要用的命令结果.
        """

        self.bash_calls.append(
            {
                "thread_id": thread_id,
                "run_id": run_id,
                "command": command,
                "timeout": timeout,
                "world_view": world_view,
                "policy": policy,
            }
        )
        return SimpleNamespace(
            ok=True,
            exit_code=0,
            stdout_excerpt="hello from bash",
            stderr_excerpt="",
            stdout_truncated=False,
            stderr_truncated=False,
            metadata={},
        )

    async def ensure_loaded_skills_mirrored(self, thread_id: str, skill_catalog, world_view=None) -> list[str]:
        """保留旧 helper, 让测试能发现它是不是还被调用了.

        Args:
            thread_id (str): 当前线程 ID.
            skill_catalog: 当前 skill catalog.
            world_view: 当前 world view.

        Returns:
            list[str]: 固定空列表.
        """

        _ = thread_id, skill_catalog, world_view
        self.ensure_loaded_skill_calls += 1
        return []


def _tool_execution_context(*, enabled_tools: list[str]) -> ToolExecutionContext:
    """构造一份最小可用的 ToolExecutionContext.

    Args:
        enabled_tools (list[str]): 当前 run 允许的工具名.

    Returns:
        ToolExecutionContext: 最小工具执行上下文.
    """

    return ToolExecutionContext(
        run_id="run-1",
        thread_id="thread-1",
        actor_id="actor-1",
        agent_id="aca",
        target=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        agent=ResolvedAgent(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/aca",
            enabled_tools=list(enabled_tools),
            computer_policy=ComputerPolicy(),
        ),
        world_view=SimpleNamespace(name="world-view"),
        metadata={
            "visible_tools": list(enabled_tools),
            "backend_kind": "host",
            "allow_exec": True,
            "allow_sessions": True,
            "network_mode": "enabled",
        },
    )


# endregion


# region tests

async def test_build_runtime_components_registers_core_tools_as_builtin_sources() -> None:
    """启动 runtime 后, core tool 应该直接注册成 builtin 来源."""

    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/aca",
                    }
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    sources = _tool_sources(components)
    read_tool = next(
        item for item in components.tool_broker.list_registered_tools() if item["name"] == "read"
    )

    write_tool = next(
        item for item in components.tool_broker.list_registered_tools() if item["name"] == "write"
    )
    edit_tool = next(
        item for item in components.tool_broker.list_registered_tools() if item["name"] == "edit"
    )
    bash_tool = next(
        item for item in components.tool_broker.list_registered_tools() if item["name"] == "bash"
    )

    assert sources["read"] == "builtin:computer"
    assert "2000 lines or 50KB" in read_tool["description"]
    assert "Use offset/limit for large files" in read_tool["description"]
    assert "continue with offset until complete" in read_tool["description"]
    assert read_tool["parameters"]["properties"]["offset"]["type"] == "integer"
    assert read_tool["parameters"]["properties"]["limit"]["type"] == "integer"
    assert sources["write"] == "builtin:computer"
    assert write_tool["description"] == (
        "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. "
        "Automatically creates parent directories."
    )
    assert sources["edit"] == "builtin:computer"
    assert edit_tool["description"] == (
        "Edit a file by replacing exact text. The oldText must match exactly "
        "(including whitespace). Use this for precise, surgical edits."
    )
    assert edit_tool["parameters"]["properties"]["oldText"]["type"] == "string"
    assert edit_tool["parameters"]["properties"]["newText"]["type"] == "string"
    assert sources["bash"] == "builtin:computer"
    assert bash_tool["parameters"]["properties"]["command"]["type"] == "string"
    assert bash_tool["parameters"]["properties"]["timeout"]["type"] == "integer"
    assert "exec" not in sources
    assert "ls" not in sources
    assert "grep" not in sources
    assert "exec" not in sources
    assert "bash_open" not in sources
    assert "bash_write" not in sources
    assert "bash_read" not in sources
    assert "bash_close" not in sources
    assert sources["Skill"] == "builtin:skills"
    assert sources["sticky_note_read"] == "builtin:sticky_notes"
    assert sources["sticky_note_append"] == "builtin:sticky_notes"
    assert sources["delegate_subagent"] == "builtin:subagents"
    assert sources["message"] == BUILTIN_MESSAGE_TOOL_SOURCE
    assert "sticky_note_put" not in sources
    assert "sticky_note_get" not in sources
    assert "sticky_note_list" not in sources
    assert "sticky_note_delete" not in sources


async def test_builtin_core_tools_survive_reconciler_run(tmp_path: Path) -> None:
    """reconcile 外部 plugin 时, builtin core tool 也要一直留在 broker 里."""

    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "runtime_root": str(tmp_path / "runtime_data"),
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    await components.plugin_reconciler.reconcile_all()
    sources = _tool_sources(components)

    assert sources["read"] == "builtin:computer"
    assert sources["Skill"] == "builtin:skills"
    assert sources["delegate_subagent"] == "builtin:subagents"


async def test_runtime_config_reload_keeps_builtin_core_tools(tmp_path: Path) -> None:
    """控制面热刷新配置后, builtin core tool 也不该消失."""

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "agent:",
                '  system_prompt: "You are Aca."',
                "runtime:",
                '  default_agent_id: "aca"',
                "  profiles:",
                "    aca:",
                '      name: "Aca"',
                '      prompt_ref: "prompt/aca"',
                "  prompts:",
                '    prompt/aca: "You are Aca."',
            ]
        ),
        encoding="utf-8",
    )
    config = Config.from_file(str(config_path))

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    before = _tool_sources(components)

    result = await components.config_control_plane.reload_runtime_configuration()
    after = _tool_sources(components)

    assert "session_count" in result
    assert before["read"] == "builtin:computer"
    assert before["Skill"] == "builtin:skills"
    assert before["delegate_subagent"] == "builtin:subagents"
    assert after["read"] == "builtin:computer"
    assert after["Skill"] == "builtin:skills"
    assert after["delegate_subagent"] == "builtin:subagents"


async def test_builtin_computer_surface_uses_read_world_path_interface() -> None:
    """builtin computer read 应该走 todo3 新接口名."""

    runtime = _SpyComputerRuntime()
    broker = ToolBroker()
    surface = BuiltinComputerToolSurface(
        computer_runtime=runtime,
    )
    surface.register(broker)

    ctx = _tool_execution_context(enabled_tools=["read"])
    result = await broker.execute(
        tool_name="read",
        arguments={"path": "/workspace/demo.txt"},
        ctx=ctx,
    )

    assert runtime.ensure_loaded_skill_calls == 0
    assert runtime.read_calls == [
        {
            "world_view": ctx.world_view,
            "world_path": "/workspace/demo.txt",
            "offset": None,
            "limit": None,
        }
    ]
    assert result.llm_content == "content:/workspace/demo.txt"


async def test_builtin_computer_surface_uses_write_world_path_interface() -> None:
    """builtin computer write 应该走 todo3 新接口名."""

    runtime = _SpyComputerRuntime()
    broker = ToolBroker()
    surface = BuiltinComputerToolSurface(
        computer_runtime=runtime,
    )
    surface.register(broker)
    ctx = _tool_execution_context(enabled_tools=["write"])

    result = await broker.execute(
        tool_name="write",
        arguments={"path": "/workspace/demo.txt", "content": "hello"},
        ctx=ctx,
    )

    assert runtime.ensure_loaded_skill_calls == 0
    assert len(runtime.write_calls) == 1
    assert runtime.write_calls[0]["world_view"] is ctx.world_view
    assert runtime.write_calls[0]["world_path"] == "/workspace/demo.txt"
    assert runtime.write_calls[0]["content"] == "hello"
    assert result.llm_content == "Successfully wrote 5 bytes to /workspace/demo.txt"


async def test_builtin_computer_surface_uses_edit_world_path_interface() -> None:
    """builtin computer edit 应该走 runtime 的 edit_world_path 接口."""

    runtime = _SpyComputerRuntime()
    broker = ToolBroker()
    surface = BuiltinComputerToolSurface(
        computer_runtime=runtime,
    )
    surface.register(broker)
    ctx = _tool_execution_context(enabled_tools=["edit"])

    result = await broker.execute(
        tool_name="edit",
        arguments={
            "path": "/workspace/demo.txt",
            "oldText": "old text",
            "newText": "new text",
        },
        ctx=ctx,
    )

    assert runtime.ensure_loaded_skill_calls == 0
    assert runtime.edit_calls == [
        {
            "world_view": ctx.world_view,
            "world_path": "/workspace/demo.txt",
            "old_text": "old text",
            "new_text": "new text",
        }
    ]
    assert result.llm_content == "Successfully replaced text in /workspace/demo.txt."


async def test_builtin_computer_surface_uses_bash_world_interface() -> None:
    """builtin computer bash 应该走 runtime 的 bash_world 接口."""

    runtime = _SpyComputerRuntime()
    broker = ToolBroker()
    surface = BuiltinComputerToolSurface(
        computer_runtime=runtime,
    )
    surface.register(broker)
    ctx = _tool_execution_context(enabled_tools=["bash"])

    result = await broker.execute(
        tool_name="bash",
        arguments={"command": "printf 'hello from bash'", "timeout": 9},
        ctx=ctx,
    )

    assert runtime.bash_calls == [
        {
            "thread_id": ctx.thread_id,
            "run_id": ctx.run_id,
            "command": "printf 'hello from bash'",
            "timeout": 9,
            "world_view": ctx.world_view,
            "policy": ctx.agent.computer_policy,
        }
    ]
    assert "hello from bash" in result.llm_content


async def test_builtin_computer_surface_calls_runtime_without_skill_side_work() -> None:
    """builtin computer surface 应该直接调 runtime 入口, 不自己处理 skill 镜像."""

    runtime = _SpyComputerRuntime()
    broker = ToolBroker()
    surface = BuiltinComputerToolSurface(
        computer_runtime=runtime,
    )
    surface.register(broker)
    ctx = _tool_execution_context(enabled_tools=["read", "write", "edit", "bash"])

    await broker.execute(
        tool_name="read",
        arguments={"path": "/workspace/demo.txt"},
        ctx=ctx,
    )
    await broker.execute(
        tool_name="write",
        arguments={"path": "/workspace/demo.txt", "content": "hello"},
        ctx=ctx,
    )
    await broker.execute(
        tool_name="edit",
        arguments={"path": "/workspace/demo.txt", "oldText": "hello", "newText": "world"},
        ctx=ctx,
    )
    await broker.execute(
        tool_name="bash",
        arguments={"command": "printf 'hello from bash'"},
        ctx=ctx,
    )

    assert runtime.ensure_loaded_skill_calls == 0
    assert runtime.read_calls[0]["world_path"] == "/workspace/demo.txt"
    assert runtime.write_calls[0]["world_path"] == "/workspace/demo.txt"
    assert runtime.edit_calls[0]["world_path"] == "/workspace/demo.txt"
    assert runtime.bash_calls[0]["command"] == "printf 'hello from bash'"


async def test_builtin_computer_surface_keeps_image_blocks_in_read_result() -> None:
    """builtin computer read 返回图片时, 不该把内容块压成字符串."""

    runtime = _SpyComputerRuntime()
    runtime.read_result_content = [
        {"type": "text", "text": "Read image file [image/png]"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]
    broker = ToolBroker()
    surface = BuiltinComputerToolSurface(
        computer_runtime=runtime,
    )
    surface.register(broker)
    ctx = _tool_execution_context(enabled_tools=["read"])

    result = await broker.execute(
        tool_name="read",
        arguments={"path": "/workspace/pixel.png"},
        ctx=ctx,
    )

    assert isinstance(result.llm_content, list)
    assert result.llm_content[0]["type"] == "text"
    assert result.llm_content[1]["type"] == "image_url"


def test_message_tool_contract_describes_workspace_relative_local_file_rule() -> None:
    broker = ToolBroker()
    surface = BuiltinMessageToolSurface()
    surface.register(broker)

    registration = next(item for item in broker.list_registered_tools() if item["name"] == "message")
    images_description = registration["parameters"]["properties"]["images"]["description"]

    assert "relative paths under the workspace" in images_description
    assert "copy or move it into the workspace first" in images_description


async def test_message_tool_rewrites_relative_local_file_paths_into_workspace_world_paths() -> None:
    broker = ToolBroker()
    surface = BuiltinMessageToolSurface()
    surface.register(broker)
    ctx = _tool_execution_context(enabled_tools=["message"])

    result = await broker.execute(
        tool_name="message",
        arguments={"action": "send", "images": ["reports/out.png"]},
        ctx=ctx,
    )

    plan = result.user_actions[0]
    assert plan.action.payload["images"] == ["/workspace/reports/out.png"]


async def test_message_tool_rejects_absolute_local_file_paths_for_qq_send() -> None:
    broker = ToolBroker()
    surface = BuiltinMessageToolSurface()
    surface.register(broker)
    ctx = _tool_execution_context(enabled_tools=["message"])

    result = await broker.execute(
        tool_name="message",
        arguments={"action": "send", "images": ["/tmp/out.png"]},
        ctx=ctx,
    )

    assert "relative path" in result.llm_content
    assert result.user_actions == []


async def test_message_tool_rejects_parent_traversal_local_file_paths_for_qq_send() -> None:
    broker = ToolBroker()
    surface = BuiltinMessageToolSurface()
    surface.register(broker)
    ctx = _tool_execution_context(enabled_tools=["message"])

    parent_result = await broker.execute(
        tool_name="message",
        arguments={"action": "send", "images": ["../secret/out.png"]},
        ctx=ctx,
    )
    dotted_parent_result = await broker.execute(
        tool_name="message",
        arguments={"action": "send", "images": ["./../secret/out.png"]},
        ctx=ctx,
    )

    assert "relative path" in parent_result.llm_content or "safe relative path" in parent_result.llm_content
    assert parent_result.user_actions == []
    assert "relative path" in dotted_parent_result.llm_content or "safe relative path" in dotted_parent_result.llm_content
    assert dotted_parent_result.user_actions == []


# endregion
