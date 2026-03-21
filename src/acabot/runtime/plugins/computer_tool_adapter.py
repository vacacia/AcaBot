"""runtime.plugins.computer_tool_adapter 暴露 computer 子系统的 tool 适配层.

这个模块不是 computer 本体.
它不拥有 workspace, backend, session 或 attachment staging 的生命周期.

它把 `runtime.computer` 里的基础设施能力包装成给 ToolBroker 注册的工具
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from acabot.agent import ToolSpec

from ..computer import ComputerPolicy, ComputerRuntime
from ..plugin_manager import RuntimePlugin, RuntimePluginContext, RuntimeToolRegistration
from ..skills import SkillCatalog
from ..tool_broker import ToolExecutionContext, ToolResult


class ComputerToolAdapterPlugin(RuntimePlugin):
    """把 computer runtime 暴露成给 ToolBroker 使用的一组普通工具.

    负责:
    - 注册工具 schema
    - 把 tool call 转给 `ComputerRuntime`
    - 把结果转成 `ToolResult`
    """

    name = "computer_tool_adapter"

    def __init__(self) -> None:
        self._computer_runtime: ComputerRuntime | None = None
        self._skill_catalog: SkillCatalog | None = None

    async def setup(self, runtime: RuntimePluginContext) -> None:
        self._computer_runtime = runtime.computer_runtime
        self._skill_catalog = runtime.skill_catalog

    def runtime_tools(self) -> list[RuntimeToolRegistration]:
        return [
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="read",
                    description="Read a UTF-8 text file from the current Work World. Use world paths like /workspace/..., /skills/..., /self/... .",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                        },
                        "required": ["path"],
                    },
                ),
                handler=self._read,
            ),
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="write",
                    description="Write a UTF-8 text file into the current Work World. Use world paths like /workspace/..., /skills/..., /self/... .",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                ),
                handler=self._write,
            ),
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="ls",
                    description="List files and directories from the current Work World. Use world paths like /workspace/..., /skills/..., /self/... .",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                        },
                    },
                ),
                handler=self._ls,
            ),
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="grep",
                    description="Search text recursively inside the current Work World. Use world paths like /workspace/..., /skills/..., /self/... .",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "pattern": {"type": "string"},
                        },
                        "required": ["pattern"],
                    },
                ),
                handler=self._grep,
            ),
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="exec",
                    description="Run a one-shot shell command inside the current Work World execution view.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                        },
                        "required": ["command"],
                    },
                ),
                handler=self._exec,
            ),
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="bash_open",
                    description="Open a shared shell session bound to the current Work World execution view.",
                    parameters={"type": "object", "properties": {}},
                ),
                handler=self._bash_open,
            ),
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="bash_write",
                    description="Send input into an existing shell session.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "session_id": {"type": "string"},
                            "command": {"type": "string"},
                        },
                        "required": ["session_id", "command"],
                    },
                ),
                handler=self._bash_write,
            ),
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="bash_read",
                    description="Read the current output window of a shell session.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "session_id": {"type": "string"},
                        },
                        "required": ["session_id"],
                    },
                ),
                handler=self._bash_read,
            ),
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="bash_close",
                    description="Close an existing shell session.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "session_id": {"type": "string"},
                        },
                        "required": ["session_id"],
                    },
                ),
                handler=self._bash_close,
            ),
        ]

    async def _read(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        service = self._require_runtime()
        await self._ensure_loaded_skill_mirrors(ctx)
        path = str(arguments.get("path", "") or "/workspace")
        content = await service.read_world_file(
            world_view=self._require_world_view(ctx),
            world_path=path,
        )
        return ToolResult(
            llm_content=content,
            raw={"path": path, "content": content},
        )

    async def _write(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        service = self._require_runtime()
        await self._ensure_loaded_skill_mirrors(ctx)
        path = str(arguments.get("path", "") or "")
        content = str(arguments.get("content", "") or "")
        policy = self._policy_from_ctx(ctx)
        await service.write_world_file(
            world_view=self._require_world_view(ctx),
            world_path=path,
            content=content,
            policy=policy,
        )
        return ToolResult(
            llm_content=f"Wrote {path}",
            raw={"path": path, "written": True},
        )

    async def _ls(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        service = self._require_runtime()
        await self._ensure_loaded_skill_mirrors(ctx)
        path = str(arguments.get("path", "/workspace") or "/workspace")
        items = await service.list_world_entries(
            world_view=self._require_world_view(ctx),
            world_path=path,
        )
        lines = [f"{item.kind} {item.path}" for item in items]
        return ToolResult(
            llm_content="\n".join(lines) if lines else "(empty)",
            raw={"items": [self._serialize(item) for item in items]},
        )

    async def _grep(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        service = self._require_runtime()
        await self._ensure_loaded_skill_mirrors(ctx)
        matches = await service.grep_world(
            world_view=self._require_world_view(ctx),
            world_path=str(arguments.get("path", "/workspace") or "/workspace"),
            pattern=str(arguments.get("pattern", "") or ""),
        )
        lines = [f"{item['path']}:{item['line']}: {item['content']}" for item in matches]
        return ToolResult(
            llm_content="\n".join(lines) if lines else "(no matches)",
            raw={"matches": matches},
        )

    async def _exec(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        service = self._require_runtime()
        await self._ensure_loaded_skill_mirrors(ctx)
        result = await service.exec_once(
            thread_id=ctx.thread_id,
            run_id=ctx.run_id,
            command=str(arguments.get("command", "") or ""),
            policy=self._policy_from_ctx(ctx),
            world_view=self._require_world_view(ctx),
        )
        return ToolResult(
            llm_content=self._format_command_result(result),
            raw=self._serialize(result),
        )

    async def _bash_open(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        _ = arguments
        service = self._require_runtime()
        await self._ensure_loaded_skill_mirrors(ctx)
        session = await service.open_session(
            thread_id=ctx.thread_id,
            run_id=ctx.run_id,
            agent_id=ctx.agent_id,
            policy=self._policy_from_ctx(ctx),
            world_view=self._require_world_view(ctx),
        )
        return ToolResult(
            llm_content=f"Opened session {session.session_id}",
            raw={"session_id": session.session_id},
            metadata={"session_id": session.session_id},
        )

    async def _bash_write(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        service = self._require_runtime()
        session_id = str(arguments.get("session_id", "") or "")
        command = str(arguments.get("command", "") or "")
        await service.write_session(
            thread_id=ctx.thread_id,
            session_id=session_id,
            command=command,
            run_id=ctx.run_id,
        )
        return ToolResult(
            llm_content=f"Sent input to session {session_id}",
            raw={"session_id": session_id, "written": True},
        )

    async def _bash_read(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        service = self._require_runtime()
        session_id = str(arguments.get("session_id", "") or "")
        result = await service.read_session(
            thread_id=ctx.thread_id,
            session_id=session_id,
            run_id=ctx.run_id,
        )
        return ToolResult(
            llm_content=self._format_command_result(result),
            raw=self._serialize(result),
        )

    async def _bash_close(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        service = self._require_runtime()
        session_id = str(arguments.get("session_id", "") or "")
        await service.close_session(
            thread_id=ctx.thread_id,
            session_id=session_id,
            run_id=ctx.run_id,
        )
        return ToolResult(
            llm_content=f"Closed session {session_id}",
            raw={"session_id": session_id, "closed": True},
        )

    def _require_runtime(self) -> ComputerRuntime:
        if self._computer_runtime is None:
            raise RuntimeError("computer runtime unavailable")
        return self._computer_runtime

    @staticmethod
    def _require_world_view(ctx: ToolExecutionContext):
        if ctx.world_view is None:
            raise RuntimeError("world view unavailable")
        return ctx.world_view

    async def _ensure_loaded_skill_mirrors(self, ctx: ToolExecutionContext) -> None:
        if self._computer_runtime is None or self._skill_catalog is None:
            return
        await self._computer_runtime.ensure_loaded_skills_mirrored(
            ctx.thread_id,
            self._skill_catalog,
            world_view=ctx.world_view,
        )

    @staticmethod
    def _policy_from_ctx(ctx: ToolExecutionContext) -> ComputerPolicy:
        return ComputerPolicy(
            backend=str(ctx.metadata.get("backend_kind", "host") or "host"),
            allow_exec=bool(ctx.metadata.get("allow_exec", False)),
            allow_sessions=bool(ctx.metadata.get("allow_sessions", False)),
            auto_stage_attachments=True,
            network_mode=str(ctx.metadata.get("network_mode", "enabled") or "enabled"),
        )

    @staticmethod
    def _format_command_result(result: Any) -> str:
        parts = [f"ok={getattr(result, 'ok', False)}", f"exit_code={getattr(result, 'exit_code', None)}"]
        stdout = str(getattr(result, "stdout_excerpt", "") or "")
        stderr = str(getattr(result, "stderr_excerpt", "") or "")
        if stdout:
            parts.append(f"stdout:\n{stdout}")
        if stderr:
            parts.append(f"stderr:\n{stderr}")
        return "\n".join(parts)

    @staticmethod
    def _serialize(value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, list):
            return [ComputerToolAdapterPlugin._serialize(item) for item in value]
        if isinstance(value, dict):
            return {key: ComputerToolAdapterPlugin._serialize(item) for key, item in value.items()}
        return value
