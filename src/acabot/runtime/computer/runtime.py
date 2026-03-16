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
    ComputerBackendNotImplemented,
    ComputerPolicy,
    ComputerRuntimeConfig,
    ComputerRuntimeOverride,
    WorkspaceFileEntry,
    WorkspaceSandboxStatus,
    WorkspaceState,
    parse_computer_override,
    parse_computer_policy,
)
from .workspace import WorkspaceManager, sanitize_filename

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
        self._thread_override_backends: dict[str, str] = {}

    async def prepare_run_context(self, ctx: "RunContext") -> None:
        policy = self.effective_policy_for_ctx(ctx)
        workspace_dir = self.workspace_manager.ensure_workspace_layout(ctx.thread.thread_id)
        backend = self.backends[policy.backend]
        await backend.ensure_workspace(
            host_path=workspace_dir,
            visible_root=self.workspace_manager.visible_root(),
        )
        staged = AttachmentStageResult()
        if policy.auto_stage_attachments and ctx.event.attachments:
            staged = await self.stage_attachments(
                thread_id=ctx.thread.thread_id,
                run_id=ctx.run.run_id,
                event_id=ctx.event.event_id,
                attachments=list(ctx.event.attachments),
            )
        ctx.computer_policy_effective = policy
        ctx.computer_backend_kind = backend.kind
        self._set_thread_backend_state(ctx.thread.thread_id, backend.kind)
        ctx.attachment_snapshots = list(staged.snapshots)
        ctx.workspace_state = WorkspaceState(
            thread_id=ctx.thread.thread_id,
            agent_id=ctx.profile.agent_id,
            backend_kind=backend.kind,
            workspace_host_path=str(workspace_dir),
            workspace_visible_root=self.workspace_manager.visible_root(),
            read_only=bool(policy.read_only),
            available_tools=["read", "write", "ls", "grep", "exec", "bash_open", "bash_write", "bash_read", "bash_close"],
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
                "workspace_root": self.workspace_manager.visible_root(),
                "attachment_count": len(staged.snapshots),
            },
        )

    def effective_policy_for_ctx(self, ctx: "RunContext") -> ComputerPolicy:
        policy = parse_computer_policy(ctx.profile.config.get("computer"), defaults=ctx.profile.computer_policy)
        override = parse_computer_override(ctx.thread.metadata.get("computer_override"))
        return self._apply_override(policy, override)

    async def stage_attachments(
        self,
        *,
        thread_id: str,
        run_id: str = "",
        event_id: str,
        attachments: list[EventAttachment],
        category: str = "inbound",
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

    async def write_workspace_file(
        self,
        *,
        thread_id: str,
        relative_path: str,
        content: str,
        policy: ComputerPolicy,
    ) -> None:
        if policy.read_only or not policy.allow_write:
            raise PermissionError("write is disabled by computer policy")
        host_path = self.workspace_manager.workspace_dir_for_thread(thread_id)
        return await self.backends["host"].write_text(
            host_path=host_path,
            relative_path=relative_path,
            content=content,
        )

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
    ) -> list[str]:
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
    ) -> CommandExecutionResult:
        workspace = self.workspace_manager.workspace_dir_for_thread(thread_id)
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
    ) -> CommandSession:
        workspace = self.workspace_manager.workspace_dir_for_thread(thread_id)
        session = CommandSession(
            session_id=f"session:{thread_id}:{int(time.time() * 1000)}",
            thread_id=thread_id,
            backend_kind=policy.backend,
            cwd_visible=self.workspace_manager.visible_root(),
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
        if thread_id not in self._thread_override_backends and not self._sessions.get(thread_id):
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
                    available_tools=["read", "write", "ls", "grep", "exec", "bash_open", "bash_write", "bash_read", "bash_close"],
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
        thread.metadata["computer_override"] = {
            "backend": override.backend,
            "read_only": override.read_only,
            "allow_write": override.allow_write,
            "allow_exec": override.allow_exec,
            "allow_sessions": override.allow_sessions,
            "network_mode": override.network_mode,
        }
        if override.backend:
            self._thread_override_backends[thread.thread_id] = override.backend
        else:
            self._thread_override_backends.pop(thread.thread_id, None)

    async def clear_thread_override(self, *, thread) -> None:
        thread.metadata.pop("computer_override", None)
        self._thread_override_backends.pop(thread.thread_id, None)
        if not self._sessions.get(thread.thread_id) and thread.thread_id not in self._thread_backend_state:
            self._set_thread_backend_state(thread.thread_id, "host")

    @staticmethod
    def _apply_override(policy: ComputerPolicy, override: ComputerRuntimeOverride) -> ComputerPolicy:
        return ComputerPolicy(
            backend=override.backend or policy.backend,
            read_only=policy.read_only if override.read_only is None else bool(override.read_only),
            allow_write=policy.allow_write if override.allow_write is None else bool(override.allow_write),
            allow_exec=policy.allow_exec if override.allow_exec is None else bool(override.allow_exec),
            allow_sessions=policy.allow_sessions if override.allow_sessions is None else bool(override.allow_sessions),
            auto_stage_attachments=policy.auto_stage_attachments,
            network_mode=override.network_mode or policy.network_mode,
        )

    def _require_session(self, thread_id: str, session_id: str) -> CommandSession:
        session = self._sessions.get(thread_id, {}).get(session_id)
        if session is None:
            raise KeyError("unknown session_id")
        return session

    def _backend_for_thread(self, thread_id: str) -> str:
        sessions = self._sessions.get(thread_id, {})
        if sessions:
            return next(iter(sessions.values())).backend_kind
        override_backend = self._thread_override_backends.get(thread_id, "")
        if override_backend:
            return override_backend
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
