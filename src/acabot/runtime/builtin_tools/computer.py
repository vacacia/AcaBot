"""runtime.builtin_tools.computer 提供 computer builtin tool 的注册入口.

这个文件负责把 `runtime.computer` 的前台文件能力接成稳定的基础工具.
它和下面这些组件直接相连:
- `runtime.computer`: 真正读文件、写文件
- `runtime.tool_broker`: 保存工具目录并接住模型调用
- `runtime.bootstrap`: 启动时调用这里完成 builtin tool 注册

这里表达的是 computer 的前台工具表面:
- 定义 tool spec
- 接住 tool call
- 转给 `ComputerRuntime`
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from acabot.agent import ToolSpec

from ..computer import ComputerPolicy, ComputerRuntime
from ..tool_broker import ToolBroker, ToolExecutionContext, ToolResult


# region source
BUILTIN_COMPUTER_TOOL_SOURCE = "builtin:computer"


# endregion


# region surface
class BuiltinComputerToolSurface:
    """computer builtin tool 的注册和执行入口.

    Attributes:
        computer_runtime (ComputerRuntime | None): 真实 computer runtime.
    """

    def __init__(
        self,
        *,
        computer_runtime: ComputerRuntime | None,
    ) -> None:
        """保存 builtin computer tool 需要的共享依赖.

        Args:
            computer_runtime: 真实 computer runtime.
        """

        self.computer_runtime = computer_runtime

    def register(self, tool_broker: ToolBroker) -> list[str]:
        """把 computer builtin tool 注册到 ToolBroker.

        Args:
            tool_broker: 当前 runtime 使用的 ToolBroker.

        Returns:
            list[str]: 这次注册的工具名列表.
        """

        tool_broker.unregister_source(BUILTIN_COMPUTER_TOOL_SOURCE)
        names: list[str] = []
        for spec, handler in self._tool_definitions():
            tool_broker.register_tool(
                spec,
                handler,
                source=BUILTIN_COMPUTER_TOOL_SOURCE,
            )
            names.append(spec.name)
        return names

    def _tool_definitions(self) -> list[tuple[ToolSpec, Any]]:
        """返回当前保留的 computer builtin tool 定义列表.

        Returns:
            list[tuple[ToolSpec, Any]]: `(spec, handler)` 列表.
        """

        return [
            (
                ToolSpec(
                    name="read",
                    description=(
                        "Read the contents of a file from the current Work World. "
                        "Supports text files and images (jpg, png, gif, webp). "
                        "For text files, output is truncated to 2000 lines or 50KB "
                        "(whichever is hit first). Use offset/limit for large files. "
                        "When you need the full file, continue with offset until complete. "
                        "Use world paths like /workspace/..., /skills/..., /self/... ."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "offset": {"type": "integer"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["path"],
                    },
                ),
                self._read,
            ),
            (
                ToolSpec(
                    name="write",
                    description=(
                        "Write content to a file. Creates the file if it doesn't exist, "
                        "overwrites if it does. Automatically creates parent directories."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                ),
                self._write,
            ),
            (
                ToolSpec(
                    name="edit",
                    description=(
                        "Edit a file by replacing exact text. The oldText must match exactly "
                        "(including whitespace). Use this for precise, surgical edits."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "oldText": {"type": "string"},
                            "newText": {"type": "string"},
                        },
                        "required": ["path", "oldText", "newText"],
                    },
                ),
                self._edit,
            ),
            (
                ToolSpec(
                    name="bash",
                    description=(
                        "Execute a shell command in the current Work World. "
                        "Use this for directory exploration and text search."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "timeout": {"type": "integer"},
                        },
                        "required": ["command"],
                    },
                ),
                self._bash,
            ),
        ]

    async def _read(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        """读取当前 Work World 里的文件."""

        service = self._require_runtime()
        path = str(arguments.get("path", "") or "/workspace")
        offset = arguments.get("offset")
        limit = arguments.get("limit")
        result = await service.read_world_path(
            world_view=self._require_world_view(ctx),
            world_path=path,
            offset=int(offset) if offset is not None else None,
            limit=int(limit) if limit is not None else None,
        )
        return ToolResult(
            llm_content=result.content,
            raw=self._serialize(result),
        )

    async def _write(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        """写入当前 Work World 里的文本文件."""

        service = self._require_runtime()
        path = str(arguments.get("path", "") or "")
        content = str(arguments.get("content", "") or "")
        result = await service.write_world_path(
            world_view=self._require_world_view(ctx),
            world_path=path,
            content=content,
        )
        return ToolResult(
            llm_content=(
                f"Successfully wrote {result.size_bytes} bytes to {result.world_path}"
            ),
            raw=self._serialize(result),
        )

    async def _edit(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        """替换当前 Work World 里的指定文字."""

        service = self._require_runtime()
        path = str(arguments.get("path", "") or "")
        old_text = str(arguments.get("oldText", "") or "")
        new_text = str(arguments.get("newText", "") or "")
        result = await service.edit_world_path(
            world_view=self._require_world_view(ctx),
            world_path=path,
            old_text=old_text,
            new_text=new_text,
        )
        return ToolResult(
            llm_content=f"Successfully replaced text in {result.world_path}.",
            raw=self._serialize(result),
        )

    async def _bash(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        """在当前 Work World 里执行一条 shell 命令."""

        service = self._require_runtime()
        command = str(arguments.get("command", "") or "")
        timeout = arguments.get("timeout")
        result = await service.bash_world(
            thread_id=ctx.thread_id,
            run_id=ctx.run_id,
            command=command,
            timeout=int(timeout) if timeout is not None else None,
            world_view=self._require_world_view(ctx),
            policy=self._policy_from_ctx(ctx),
        )
        return ToolResult(
            llm_content=self._bash_result_text(result),
            raw=self._serialize(result),
        )

    def _require_runtime(self) -> ComputerRuntime:
        """返回当前必需的 computer runtime.

        Returns:
            ComputerRuntime: 当前 computer runtime.

        Raises:
            RuntimeError: 当 runtime 缺失时抛错.
        """

        if self.computer_runtime is None:
            raise RuntimeError("computer runtime unavailable")
        return self.computer_runtime

    @staticmethod
    def _require_world_view(ctx: ToolExecutionContext):
        """确保当前工具调用带着 world view."""

        if ctx.world_view is None:
            raise RuntimeError("world view unavailable")
        return ctx.world_view

    @staticmethod
    def _policy_from_ctx(ctx: ToolExecutionContext) -> ComputerPolicy:
        """从工具上下文里拼出当前命令要用的 computer policy."""

        return ComputerPolicy(
            backend=str(ctx.metadata.get("backend_kind", "host") or "host"),
            allow_exec=bool(ctx.metadata.get("allow_exec", False)),
            allow_sessions=bool(ctx.metadata.get("allow_sessions", False)),
            auto_stage_attachments=True,
            network_mode=str(ctx.metadata.get("network_mode", "enabled") or "enabled"),
        )

    @staticmethod
    def _bash_result_text(result: Any) -> str:
        """把命令结果整理成模型好读的文字."""

        stdout = str(getattr(result, "stdout_excerpt", "") or "")
        stderr = str(getattr(result, "stderr_excerpt", "") or "")
        exit_code = getattr(result, "exit_code", None)
        if stdout and not stderr:
            return stdout
        parts: list[str] = []
        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append(f"stderr:\n{stderr}")
        if not parts:
            parts.append(f"Command exited with code {exit_code}")
        return "\n\n".join(parts)

    @staticmethod
    def _serialize(value: Any) -> Any:
        """把 dataclass 结果转成普通字典, 方便 raw 返回值保存."""

        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, list):
            return [BuiltinComputerToolSurface._serialize(item) for item in value]
        if isinstance(value, dict):
            return {key: BuiltinComputerToolSurface._serialize(item) for key, item in value.items()}
        return value


# endregion


__all__ = [
    "BUILTIN_COMPUTER_TOOL_SOURCE",
    "BuiltinComputerToolSurface",
]
