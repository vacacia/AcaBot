"""runtime.computer.runtime 提供 computer 子系统统一入口."""

from __future__ import annotations

import shutil
from pathlib import Path
import time
import uuid
from typing import TYPE_CHECKING, Any

from acabot.types import EventAttachment

from .attachments import AttachmentResolver, GatewayAttachmentResolver
from .backends import DockerSandboxBackend, HostComputerBackend, RemoteComputerBackend
from .contracts import (
    AttachmentStageResult,
    CommandExecutionResult,
    CommandSession,
    ComputerBackend,
    ComputerPolicyDecision,
    ComputerBackendNotImplemented,
    ComputerPolicy,
    ComputerRuntimeConfig,
    ComputerRuntimeOverride,
    ResolvedWorldPath,
    WorldInputBundle,
    WorkspaceFileEntry,
    WorkspaceSandboxStatus,
    WorkspaceState,
    parse_computer_policy,
)
from .workspace import WorkspaceManager, sanitize_filename
from .world import WorkWorldBuilder

if TYPE_CHECKING:
    from ..contracts import RunContext
    from ..storage.runs import RunManager
    from ..skills import SkillCatalog


class ComputerRuntime:
    """computer 子系统的统一运行时入口."""

    def __init__(
        self,
        *,
        config: ComputerRuntimeConfig,
        gateway: Any | None = None,
        run_manager: "RunManager | None" = None,
        default_policy: ComputerPolicy | None = None,
    ) -> None:
        self.config = config
        self.gateway = gateway
        self.run_manager = run_manager
        self.default_policy = default_policy or ComputerPolicy(
            backend="host",
            read_only=False,
            allow_write=True,
            allow_exec=True,
            allow_sessions=True,
            auto_stage_attachments=True,
            network_mode="enabled",
        )
        self.workspace_manager = WorkspaceManager(config)
        self.world_builder = WorkWorldBuilder(self.workspace_manager)
        self.backends: dict[str, ComputerBackend] = {
            "host": HostComputerBackend(
                stdout_window_bytes=config.exec_stdout_window_bytes,
                stderr_window_bytes=config.exec_stderr_window_bytes,
            ),
            "docker": DockerSandboxBackend(
                image=config.docker_image,
                stdout_window_bytes=config.exec_stdout_window_bytes,
                stderr_window_bytes=config.exec_stderr_window_bytes,
                network_mode=config.docker_network_mode,
            ),
            "remote": RemoteComputerBackend(),
        }
        self.attachment_resolver: AttachmentResolver = GatewayAttachmentResolver()
        self._sessions: dict[str, dict[str, CommandSession]] = {}
        self._loaded_skills: dict[str, set[str]] = {}
        self._thread_backend_state: dict[str, str] = {}

    async def prepare_run_context(self, ctx: "RunContext") -> None:
        """为当前 run 准备 computer 相关上下文.

        Args:
            ctx (RunContext): 当前 run 的执行上下文.
        """

        policy = self.effective_policy_for_ctx(ctx)
        world_view = self.build_world_view(ctx, policy=policy)
        workspace_dir = Path(world_view.workspace_root_host_path)
        backend = self.backends[policy.backend]
        await backend.ensure_workspace(
            host_path=workspace_dir,
            visible_root=world_view.execution_view.workspace_path,
        )
        staged = AttachmentStageResult()
        if policy.auto_stage_attachments and ctx.event.attachments:
            staged = await self.stage_attachments(
                thread_id=ctx.thread.thread_id,
                run_id=ctx.run.run_id,
                event_id=ctx.event.event_id,
                attachments=list(ctx.event.attachments),
                world_view=world_view,
            )
        ctx.computer_policy_effective = policy
        ctx.computer_backend_kind = backend.kind
        ctx.world_view = world_view
        self._set_thread_backend_state(ctx.thread.thread_id, backend.kind)
        ctx.attachment_snapshots = list(staged.snapshots)
        ctx.workspace_state = WorkspaceState(
            thread_id=ctx.thread.thread_id,
            agent_id=ctx.profile.agent_id,
            backend_kind=backend.kind,
            workspace_host_path=str(workspace_dir),
            workspace_visible_root="/workspace",
            read_only=False,
            available_tools=self._available_tools(policy, world_view=world_view),
            attachment_count=len(staged.snapshots),
            mirrored_skill_names=self.list_mirrored_skills(ctx.thread.thread_id),
            active_session_ids=self.list_session_ids(ctx.thread.thread_id),
        )
        await self._append_run_step(
            run_id=ctx.run.run_id,
            thread_id=ctx.thread.thread_id,
            step_type="workspace_prepare",
            status="completed",
            payload={
                "backend_kind": backend.kind,
                "workspace_root": "/workspace",
                "attachment_count": len(staged.snapshots),
                "execution_workspace_path": world_view.execution_view.workspace_path,
            },
        )

    def effective_policy_for_ctx(self, ctx: "RunContext") -> ComputerPolicy:
        """计算当前 run 的有效 computer policy.

        Args:
            ctx (RunContext): 当前 run 的执行上下文.

        Returns:
            ComputerPolicy: 当前 run 的有效 computer policy.
        """

        base = parse_computer_policy(ctx.profile.config.get("computer"), defaults=ctx.profile.computer_policy)
        if ctx.computer_policy_decision is None:
            return base
        decision = ctx.computer_policy_decision
        return ComputerPolicy(
            backend=str(decision.backend or base.backend),
            read_only=base.read_only,
            allow_write=base.allow_write,
            allow_exec=bool(decision.allow_exec),
            allow_sessions=bool(decision.allow_sessions),
            auto_stage_attachments=base.auto_stage_attachments,
            network_mode=base.network_mode,
        )

    def build_world_view(self, ctx: "RunContext", *, policy: ComputerPolicy):
        """根据当前上下文构造 Work World 视图.

        Args:
            ctx (RunContext): 当前 run 的执行上下文.
            policy (ComputerPolicy): 当前 run 的有效 computer policy.

        Returns:
            WorldView: 当前 run 的 world 视图.
        """

        return self.world_builder.build(
            WorldInputBundle(
                thread_id=ctx.thread.thread_id,
                profile_id=ctx.profile.agent_id,
                actor_kind=(
                    ctx.computer_policy_decision.actor_kind
                    if ctx.computer_policy_decision is not None
                    else (
                        "subagent"
                        if str(ctx.decision.metadata.get("run_kind", "") or "") == "subagent"
                        else "frontstage_agent"
                    )
                ),
                self_scope_id=ctx.profile.agent_id,
                visible_skill_names=(
                    list(ctx.computer_policy_decision.visible_skills)
                    if ctx.computer_policy_decision is not None
                    and ctx.computer_policy_decision.visible_skills is not None
                    else list(ctx.profile.skills)
                ),
                computer_policy=(
                    ctx.computer_policy_decision
                    if ctx.computer_policy_decision is not None
                    else self._fallback_computer_policy_decision(ctx, policy)
                ),
            )
        )

    def _fallback_computer_policy_decision(
        self,
        ctx: "RunContext",
        policy: ComputerPolicy,
    ):
        """在没有 session-driven computer decision 时生成最小兜底决策.

        Args:
            ctx (RunContext): 当前 run 的执行上下文.
            policy (ComputerPolicy): 当前 run 的有效 computer policy.

        Returns:
            ComputerPolicyDecision: 最小兜底 computer 决策.
        """

        _ = ctx
        actor_kind = "subagent" if str(ctx.decision.metadata.get("run_kind", "") or "") == "subagent" else "frontstage_agent"
        return ComputerPolicyDecision(
            actor_kind=actor_kind,
            backend=policy.backend,
            allow_exec=policy.allow_exec,
            allow_sessions=policy.allow_sessions,
            roots={
                "workspace": {"visible": True},
                "skills": {"visible": True},
                "self": {"visible": actor_kind != "subagent"},
            },
            visible_skills=None,
        )

    async def stage_attachments(
        self,
        *,
        thread_id: str,
        run_id: str = "",
        event_id: str,
        attachments: list[EventAttachment],
        category: str = "inbound",
        world_view=None,
    ) -> AttachmentStageResult:
        normalized_category = sanitize_filename(category) or "inbound"
        target_root = self.workspace_manager.attachments_dir_for_thread(thread_id) / normalized_category / event_id
        result = AttachmentStageResult()
        total = 0
        for index, attachment in enumerate(attachments):
            snapshot = await self.attachment_resolver.stage(
                attachment=attachment,
                event_id=event_id,
                attachment_index=index,
                target_dir=target_root,
                config=self.config,
                gateway=self.gateway,
            )
            if world_view is not None and snapshot.staged_path:
                relative = Path(snapshot.staged_path).resolve().relative_to(Path(world_view.workspace_root_host_path).resolve())
                relative_text = str(relative).replace("\\", "/")
                snapshot.metadata["world_path"] = f"/workspace/{relative_text}"
                snapshot.metadata["execution_path"] = str(
                    Path(world_view.execution_view.workspace_path) / relative_text
                )
            total += snapshot.size_bytes
            if total > self.config.max_total_attachment_bytes_per_run:
                snapshot.download_status = "failed"
                snapshot.error = "run attachment limit exceeded"
                snapshot.size_bytes = 0
            result.snapshots.append(snapshot)
        result.total_size_bytes = sum(item.size_bytes for item in result.snapshots)
        result.had_failures = any(item.download_status != "staged" for item in result.snapshots)
        await self._append_run_step(
            run_id=run_id,
            thread_id=thread_id,
            step_type="attachment_stage",
            status="completed_with_errors" if result.had_failures else "completed",
            payload={
                "event_id": event_id,
                "category": normalized_category,
                "attachment_count": len(result.snapshots),
                "total_size_bytes": result.total_size_bytes,
                "had_failures": result.had_failures,
            },
        )
        return result

    async def list_world_entries(
        self,
        *,
        world_view,
        world_path: str = "/workspace",
    ) -> list[WorkspaceFileEntry]:
        """按 world path 列出目录项.

        Args:
            world_view: 当前 run 的 Work World 视图.
            world_path (str): 目标 world path.

        Returns:
            list[WorkspaceFileEntry]: 当前路径下的目录项列表.
        """

        resolved = world_view.resolve(world_path)
        items = await self.backends["host"].list_entries(
            host_path=Path(resolved.host_path),
            relative_path="/",
        )
        return [
            WorkspaceFileEntry(
                path=self._join_world_path(resolved.world_path, item.path),
                kind=item.kind,
                size_bytes=item.size_bytes,
                modified_at=item.modified_at,
            )
            for item in items
        ]

    async def read_world_file(self, *, world_view, world_path: str) -> str:
        """按 world path 读取文件.

        Args:
            world_view: 当前 run 的 Work World 视图.
            world_path (str): 目标 world path.

        Returns:
            str: 文件文本内容.
        """

        resolved = world_view.resolve(world_path)
        return await self.backends["host"].read_text(
            host_path=Path(resolved.host_path).parent,
            relative_path=Path(resolved.host_path).name,
        )

    async def list_workspace_entries(
        self,
        *,
        thread_id: str,
        relative_path: str = "/",
    ) -> list[WorkspaceFileEntry]:
        host_path = self.workspace_manager.workspace_dir_for_thread(thread_id)
        return await self.backends["host"].list_entries(host_path=host_path, relative_path=relative_path)

    async def read_workspace_file(
        self,
        *,
        thread_id: str,
        relative_path: str,
    ) -> str:
        host_path = self.workspace_manager.workspace_dir_for_thread(thread_id)
        return await self.backends["host"].read_text(host_path=host_path, relative_path=relative_path)

    async def list_workspace_attachments(self, *, thread_id: str) -> list[WorkspaceFileEntry]:
        attachments_root = self.workspace_manager.attachments_dir_for_thread(thread_id)
        if not attachments_root.exists():
            return []
        return await self.backends["host"].list_entries(
            host_path=self.workspace_manager.workspace_dir_for_thread(thread_id),
            relative_path="/attachments",
        )

    async def write_world_file(
        self,
        *,
        world_view,
        world_path: str,
        content: str,
        policy: ComputerPolicy,
    ) -> None:
        """按 world path 写文件.

        Args:
            world_view: 当前 run 的 Work World 视图.
            world_path (str): 目标 world path.
            content (str): 要写入的文本.
            policy (ComputerPolicy): 当前有效 computer policy.
        """

        resolved = world_view.resolve(world_path)
        await self.backends["host"].write_text(
            host_path=Path(resolved.host_path).parent,
            relative_path=Path(resolved.host_path).name,
            content=content,
        )

    async def write_workspace_file(
        self,
        *,
        thread_id: str,
        relative_path: str,
        content: str,
        policy: ComputerPolicy,
    ) -> None:
        _ = policy
        host_path = self.workspace_manager.workspace_dir_for_thread(thread_id)
        return await self.backends["host"].write_text(
            host_path=host_path,
            relative_path=relative_path,
            content=content,
        )

    async def grep_world(
        self,
        *,
        world_view,
        world_path: str,
        pattern: str,
    ) -> list[dict[str, Any]]:
        """按 world path 做 grep.

        Args:
            world_view: 当前 run 的 Work World 视图.
            world_path (str): 目标 world path.
            pattern (str): 正则模式.

        Returns:
            list[dict[str, Any]]: 匹配结果.
        """

        resolved = world_view.resolve(world_path)
        matches = await self.backends["host"].grep_text(
            host_path=Path(resolved.host_path),
            relative_path="/",
            pattern=pattern,
        )
        normalized: list[dict[str, Any]] = []
        for item in matches:
            normalized.append(
                {
                    **item,
                    "path": self._join_world_path(resolved.world_path, item["path"]),
                }
            )
        return normalized

    async def grep_workspace(
        self,
        *,
        thread_id: str,
        relative_path: str,
        pattern: str,
    ) -> list[dict[str, Any]]:
        host_path = self.workspace_manager.workspace_dir_for_thread(thread_id)
        return await self.backends["host"].grep_text(
            host_path=host_path,
            relative_path=relative_path,
            pattern=pattern,
        )

    async def ensure_skill_mirrored(self, thread_id: str, skill_name: str, source_dir: str | Path) -> str:
        source = Path(source_dir)
        target = self.workspace_manager.skills_dir_for_thread(thread_id) / skill_name
        if target.exists():
            return str(target)
        shutil.copytree(source, target)
        return str(target)

    def mark_skill_loaded(self, thread_id: str, skill_name: str) -> None:
        if not skill_name:
            return
        self._loaded_skills.setdefault(thread_id, set()).add(skill_name)

    def list_loaded_skills(self, thread_id: str) -> list[str]:
        return sorted(self._loaded_skills.get(thread_id, set()))

    async def ensure_loaded_skills_mirrored(
        self,
        thread_id: str,
        skill_catalog: "SkillCatalog",
        world_view=None,
    ) -> list[str]:
        """确保当前 thread 已加载的 skills 已经镜像到宿主机.

        Args:
            thread_id (str): 当前 thread ID.
            skill_catalog (SkillCatalog): skill catalog.
            world_view: 当前 run 的 Work World 视图.

        Returns:
            list[str]: 本次确认存在的 skill 名列表.
        """

        mirrored: list[str] = []
        for skill_name in self.list_loaded_skills(thread_id):
            manifest = skill_catalog.get(skill_name)
            if manifest is None:
                continue
            await self.ensure_skill_mirrored(
                thread_id=thread_id,
                skill_name=skill_name,
                source_dir=manifest.root_dir,
            )
            mirrored.append(skill_name)
        if world_view is not None:
            self.refresh_world_skills_view(world_view)
        return mirrored

    def list_mirrored_skills(self, thread_id: str) -> list[str]:
        skills_dir = self.workspace_manager.skills_dir_for_thread(thread_id)
        if not skills_dir.exists():
            return []
        return sorted(path.name for path in skills_dir.iterdir() if path.is_dir())

    async def remove_mirrored_skills(self, thread_id: str) -> None:
        skills_dir = self.workspace_manager.skills_dir_for_thread(thread_id)
        if skills_dir.exists():
            shutil.rmtree(skills_dir)
        skills_dir.mkdir(parents=True, exist_ok=True)
        self._loaded_skills.pop(thread_id, None)

    async def exec_once(
        self,
        *,
        thread_id: str,
        run_id: str = "",
        command: str,
        policy: ComputerPolicy,
        world_view=None,
    ) -> CommandExecutionResult:
        """执行一次性 shell 命令.

        Args:
            thread_id (str): 当前 thread ID.
            run_id (str): 当前 run_id.
            command (str): 要执行的命令.
            policy (ComputerPolicy): 当前有效 computer policy.
            world_view: 当前 run 的 Work World 视图.

        Returns:
            CommandExecutionResult: 执行结果.
        """

        if world_view is not None:
            self._ensure_workspace_shell_access(world_view)
        workspace = Path(
            world_view.workspace_root_host_path if world_view is not None else self.workspace_manager.workspace_dir_for_thread(thread_id)
        )
        backend = self.backends[policy.backend]
        result = await backend.exec_once(host_path=workspace, command=command, policy=policy)
        self._set_thread_backend_state(thread_id, backend.kind)
        await self._append_run_step(
            run_id=run_id,
            thread_id=thread_id,
            step_type="exec",
            status="completed" if result.ok else "failed",
            payload={
                "command": command,
                "exit_code": result.exit_code,
                "stdout_truncated": result.stdout_truncated,
                "stderr_truncated": result.stderr_truncated,
                "metadata": dict(result.metadata),
                "execution_cwd": (
                    world_view.execution_view.workspace_path if world_view is not None else str(workspace)
                ),
            },
        )
        return result

    async def open_session(
        self,
        *,
        thread_id: str,
        run_id: str = "",
        agent_id: str,
        policy: ComputerPolicy,
        world_view=None,
    ) -> CommandSession:
        """打开一个 shell session.

        Args:
            thread_id (str): 当前 thread ID.
            run_id (str): 当前 run_id.
            agent_id (str): 当前 agent_id.
            policy (ComputerPolicy): 当前有效 computer policy.
            world_view: 当前 run 的 Work World 视图.

        Returns:
            CommandSession: 新建 session.
        """

        if world_view is not None:
            self._ensure_workspace_shell_access(world_view)
        workspace = Path(
            world_view.workspace_root_host_path if world_view is not None else self.workspace_manager.workspace_dir_for_thread(thread_id)
        )
        session = CommandSession(
            session_id=f"session:{thread_id}:{int(time.time() * 1000)}",
            thread_id=thread_id,
            backend_kind=policy.backend,
            cwd_visible=(
                world_view.execution_view.workspace_path if world_view is not None else self.workspace_manager.visible_root()
            ),
            cwd_host_path=str(workspace),
            created_at=int(time.time()),
        )
        await self.backends[policy.backend].open_session(session=session, policy=policy)
        self._sessions.setdefault(thread_id, {})[session.session_id] = session
        self._set_thread_backend_state(thread_id, session.backend_kind)
        await self._append_run_step(
            run_id=run_id,
            thread_id=thread_id,
            step_type="bash_open",
            status="completed",
            payload={
                "session_id": session.session_id,
                "backend_kind": session.backend_kind,
                "agent_id": agent_id,
            },
        )
        return session

    async def write_session(self, *, thread_id: str, session_id: str, command: str, run_id: str = "") -> None:
        session = self._require_session(thread_id, session_id)
        await self.backends[session.backend_kind].write_session(session, command)
        await self._append_run_step(
            run_id=run_id,
            thread_id=thread_id,
            step_type="bash_write",
            status="completed",
            payload={"session_id": session_id, "command": command},
        )

    async def read_session(self, *, thread_id: str, session_id: str, run_id: str = "") -> CommandExecutionResult:
        session = self._require_session(thread_id, session_id)
        result = CommandExecutionResult(
            ok=True,
            stdout_excerpt="".join(session.stdout_buffer),
            stderr_excerpt="".join(session.stderr_buffer),
            stdout_truncated=session.stdout_size >= self.config.exec_stdout_window_bytes,
            stderr_truncated=session.stderr_size >= self.config.exec_stderr_window_bytes,
        )
        await self._append_run_step(
            run_id=run_id,
            thread_id=thread_id,
            step_type="bash_read",
            status="completed",
            payload={
                "session_id": session_id,
                "stdout_truncated": result.stdout_truncated,
                "stderr_truncated": result.stderr_truncated,
            },
        )
        return result

    async def close_session(self, *, thread_id: str, session_id: str, run_id: str = "") -> None:
        session = self._require_session(thread_id, session_id)
        await self.backends[session.backend_kind].close_session(session)
        self._sessions.get(thread_id, {}).pop(session_id, None)
        if not self._sessions.get(thread_id):
            self._sessions.pop(thread_id, None)
        await self._append_run_step(
            run_id=run_id,
            thread_id=thread_id,
            step_type="bash_close",
            status="completed",
            payload={"session_id": session_id},
        )

    def list_session_ids(self, thread_id: str) -> list[str]:
        return sorted(self._sessions.get(thread_id, {}))

    async def close_all_sessions(self, thread_id: str) -> None:
        for session_id in list(self._sessions.get(thread_id, {})):
            await self.close_session(thread_id=thread_id, session_id=session_id)

    async def stop_workspace_sandbox(self, thread_id: str) -> None:
        workspace = self.workspace_manager.workspace_dir_for_thread(thread_id)
        backend_kind = self._backend_for_thread(thread_id)
        backend = self.backends.get(backend_kind)
        if backend is None:
            return
        try:
            await backend.stop_workspace_sandbox(thread_id=thread_id, host_path=workspace)
        except ComputerBackendNotImplemented:
            return
        if not self._sessions.get(thread_id):
            self._set_thread_backend_state(thread_id, "host")

    async def get_sandbox_status(self, thread_id: str) -> WorkspaceSandboxStatus:
        workspace = self.workspace_manager.workspace_dir_for_thread(thread_id)
        backend_kind = self._backend_for_thread(thread_id)
        backend = self.backends.get(backend_kind)
        if backend is None:
            return WorkspaceSandboxStatus(
                thread_id=thread_id,
                backend_kind=backend_kind,
                active=False,
                message="unknown backend",
            )
        try:
            status = await backend.get_sandbox_status(thread_id=thread_id, host_path=workspace)
        except ComputerBackendNotImplemented as exc:
            return WorkspaceSandboxStatus(
                thread_id=thread_id,
                backend_kind=backend_kind,
                active=False,
                message=str(exc),
            )
        status.session_count = len(self.list_session_ids(thread_id))
        return status

    async def prune_workspace(self, thread_id: str) -> None:
        await self.close_all_sessions(thread_id)
        await self.stop_workspace_sandbox(thread_id)
        self._loaded_skills.pop(thread_id, None)
        self._thread_backend_state.pop(thread_id, None)
        workspace = self.workspace_manager.workspace_dir_for_thread(thread_id)
        if workspace.exists():
            shutil.rmtree(workspace)

    async def list_workspaces(self) -> list[WorkspaceState]:
        items: list[WorkspaceState] = []
        for path in self.workspace_manager.list_workspaces():
            thread_id = self.workspace_manager.thread_id_from_workspace_path(path)
            items.append(
                WorkspaceState(
                    thread_id=thread_id,
                    agent_id="",
                    backend_kind=self._backend_for_thread(thread_id),
                    workspace_host_path=str(path),
                    workspace_visible_root=self.workspace_manager.visible_root(),
                    read_only=False,
                    available_tools=self._available_tools(self.default_policy),
                    attachment_count=len(list((path / "attachments").rglob("*"))) if (path / "attachments").exists() else 0,
                    mirrored_skill_names=self.list_mirrored_skills(thread_id),
                    active_session_ids=self.list_session_ids(thread_id),
                )
            )
        return items

    async def set_thread_override(
        self,
        *,
        thread,
        override: ComputerRuntimeOverride,
    ) -> None:
        """提示 thread computer override 已删除.

        Args:
            thread: 目标 thread.
            override: 请求设置的 override.

        Raises:
            RuntimeError: 固定抛出, 提示这条旧能力已经删除.
        """

        _ = thread, override
        raise RuntimeError("thread computer override removed; edit session config instead")

    async def clear_thread_override(self, *, thread) -> None:
        """提示 thread computer override 已删除.

        Args:
            thread: 目标 thread.

        Raises:
            RuntimeError: 固定抛出, 提示这条旧能力已经删除.
        """

        _ = thread
        raise RuntimeError("thread computer override removed; edit session config instead")

    @staticmethod
    def _join_world_path(base_world_path: str, child_visible_path: str) -> str:
        """把子路径拼回完整 world path.

        Args:
            base_world_path (str): 当前已解析的 world path.
            child_visible_path (str): backend 返回的子路径, 例如 `/demo.txt`.

        Returns:
            str: 完整 world path.
        """

        base = base_world_path.rstrip("/")
        child = str(child_visible_path or "").strip()
        if child in {"", "/"}:
            return base or "/"
        return f"{base}/{child.lstrip('/')}"

    @staticmethod
    def _available_tools(policy: ComputerPolicy, world_view=None) -> list[str]:
        """根据当前 policy 生成可用工具列表.

        Args:
            policy (ComputerPolicy): 当前有效 computer policy.
            world_view: 当前 run 的 Work World 视图.

        Returns:
            list[str]: 当前 run 里应该显示的 computer 工具列表.
        """

        tools = ["read", "write", "ls", "grep"]
        workspace_shell_access = True
        if world_view is not None:
            workspace_policy = world_view.root_policies.get("workspace")
            workspace_shell_access = bool(
                workspace_policy is not None
                and workspace_policy.visible
                and world_view.execution_view.workspace_path
            )
        if policy.allow_exec and workspace_shell_access:
            tools.append("exec")
        if policy.allow_sessions and workspace_shell_access:
            tools.extend(["bash_open", "bash_write", "bash_read", "bash_close"])
        return tools

    def refresh_world_skills_view(self, world_view) -> None:
        """刷新当前 world 的 skills 视图目录.

        Args:
            world_view: 当前 run 的 Work World 视图.
        """

        view_root = Path(world_view.skills_root_host_path)
        source_root = self.workspace_manager.skills_dir_for_thread(world_view.thread_id)
        view_root.mkdir(parents=True, exist_ok=True)
        allowed = set(world_view.visible_skill_names)
        for child in list(view_root.iterdir()):
            if child.name in allowed:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        for skill_name in sorted(allowed):
            source = source_root / skill_name
            target = view_root / skill_name
            if not source.exists():
                continue
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

    @staticmethod
    def _ensure_workspace_shell_access(world_view) -> None:
        """确保当前 world 允许 shell 进入 workspace.

        Args:
            world_view: 当前 run 的 Work World 视图.

        Raises:
            PermissionError: workspace 不允许 shell 使用时抛出.
        """

        workspace_policy = world_view.root_policies.get("workspace")
        if workspace_policy is None or not workspace_policy.visible:
            raise PermissionError("workspace is not visible in current world")
        if not world_view.execution_view.workspace_path:
            raise PermissionError("workspace is not available in current execution view")

    def _require_session(self, thread_id: str, session_id: str) -> CommandSession:
        session = self._sessions.get(thread_id, {}).get(session_id)
        if session is None:
            raise KeyError("unknown session_id")
        return session

    def _backend_for_thread(self, thread_id: str) -> str:
        sessions = self._sessions.get(thread_id, {})
        if sessions:
            return next(iter(sessions.values())).backend_kind
        backend_kind = self._thread_backend_state.get(thread_id, "")
        if backend_kind:
            return backend_kind
        return "host"

    def _set_thread_backend_state(self, thread_id: str, backend_kind: str) -> None:
        if not thread_id or not backend_kind:
            return
        self._thread_backend_state[thread_id] = backend_kind

    async def _append_run_step(
        self,
        *,
        run_id: str,
        thread_id: str,
        step_type: str,
        status: str,
        payload: dict[str, Any],
    ) -> None:
        if not run_id or self.run_manager is None:
            return
        from ..contracts import RunStep

        await self.run_manager.append_step(
            RunStep(
                step_id=f"step:computer:{uuid.uuid4().hex}",
                run_id=run_id,
                thread_id=thread_id,
                step_type=step_type,
                status=status,
                payload=dict(payload),
                created_at=int(time.time()),
            )
        )


__all__ = ["ComputerRuntime"]
