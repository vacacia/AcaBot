"""RuntimeControlPlane 的 workspace 管理子模块."""

from __future__ import annotations

import time

from ..computer import (
    ComputerRuntime,
    WorkspaceFileEntry,
    WorkspaceSandboxStatus,
    WorkspaceState,
)
from ..contracts import RunStep
from ..storage.runs import RunManager
from ..storage.threads import ThreadManager
from .snapshots import AgentSwitchSnapshot


class RuntimeWorkspaceControlOps:
    """封装 RuntimeControlPlane 的 workspace / computer 相关能力."""

    def __init__(
        self,
        *,
        run_manager: RunManager,
        thread_manager: ThreadManager | None,
        computer_runtime: ComputerRuntime | None,
    ) -> None:
        self.run_manager = run_manager
        self.thread_manager = thread_manager
        self.computer_runtime = computer_runtime

    async def list_workspaces(self) -> list[WorkspaceState]:
        if self.computer_runtime is None:
            return []
        return await self.computer_runtime.list_workspaces()

    async def list_workspace_entries(
        self,
        *,
        thread_id: str,
        relative_path: str = "/",
    ) -> list[WorkspaceFileEntry]:
        if self.computer_runtime is None:
            return []
        return await self.computer_runtime.list_workspace_entries(
            thread_id=thread_id,
            relative_path=relative_path,
        )

    async def read_workspace_file(self, *, thread_id: str, relative_path: str) -> str:
        if self.computer_runtime is None:
            raise RuntimeError("computer runtime unavailable")
        return await self.computer_runtime.read_workspace_file(
            thread_id=thread_id,
            relative_path=relative_path,
        )

    async def list_workspace_sessions(self, *, thread_id: str) -> list[str]:
        if self.computer_runtime is None:
            return []
        return self.computer_runtime.list_session_ids(thread_id)

    async def list_workspace_attachments(self, *, thread_id: str) -> list[WorkspaceFileEntry]:
        if self.computer_runtime is None:
            return []
        return await self.computer_runtime.list_workspace_attachments(thread_id=thread_id)

    async def get_sandbox_status(self, *, thread_id: str) -> WorkspaceSandboxStatus:
        if self.computer_runtime is None:
            return WorkspaceSandboxStatus(
                thread_id=thread_id,
                backend_kind="",
                active=False,
                message="computer runtime unavailable",
            )
        return await self.computer_runtime.get_sandbox_status(thread_id)

    async def list_mirrored_skills(self, *, thread_id: str) -> list[str]:
        if self.computer_runtime is None:
            return []
        return self.computer_runtime.list_mirrored_skills(thread_id)

    async def list_workspace_activity(
        self,
        *,
        thread_id: str,
        limit: int = 50,
        step_types: list[str] | None = None,
    ):
        return await self.run_manager.list_thread_steps(
            thread_id,
            limit=limit,
            step_types=step_types,
        )

    async def set_thread_computer_override(
        self,
        *,
        thread_id: str,
        force: bool = False,
    ) -> AgentSwitchSnapshot:
        _ = force
        return AgentSwitchSnapshot(
            ok=False,
            thread_id=thread_id,
            message="thread computer override removed; edit session config instead",
        )

    async def clear_thread_computer_override(
        self,
        *,
        thread_id: str,
        force: bool = False,
    ) -> AgentSwitchSnapshot:
        _ = force
        return AgentSwitchSnapshot(
            ok=False,
            thread_id=thread_id,
            message="thread computer override removed; edit session config instead",
        )

    async def prune_workspace(self, *, thread_id: str, force: bool = False) -> AgentSwitchSnapshot:
        if self.computer_runtime is None:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="computer runtime unavailable")
        active_runs = [run for run in await self.run_manager.list_active() if run.thread_id == thread_id]
        active_sessions = self.computer_runtime.list_session_ids(thread_id)
        if (active_runs or active_sessions) and not force:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="workspace in use")
        if force:
            await self.computer_runtime.close_all_sessions(thread_id)
            for run in active_runs:
                await self.run_manager.append_step(
                    self._control_plane_step(
                        run_id=run.run_id,
                        thread_id=thread_id,
                        step_type="workspace_prune",
                        status="cancelled",
                        payload={"reason": "workspace pruned by operator"},
                    )
                )
                await self.run_manager.mark_cancelled(run.run_id, "workspace pruned by operator")
        await self.computer_runtime.prune_workspace(thread_id)
        return AgentSwitchSnapshot(ok=True, thread_id=thread_id, message="workspace pruned")

    async def stop_workspace_sandbox(self, *, thread_id: str, force: bool = False) -> AgentSwitchSnapshot:
        if self.computer_runtime is None:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="computer runtime unavailable")
        active_runs = [run for run in await self.run_manager.list_active() if run.thread_id == thread_id]
        active_sessions = self.computer_runtime.list_session_ids(thread_id)
        if (active_runs or active_sessions) and not force:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="sandbox in use")
        if force:
            await self.computer_runtime.close_all_sessions(thread_id)
            for run in active_runs:
                await self.run_manager.append_step(
                    self._control_plane_step(
                        run_id=run.run_id,
                        thread_id=thread_id,
                        step_type="sandbox_stop",
                        status="cancelled",
                        payload={"reason": "sandbox stopped by operator"},
                    )
                )
                await self.run_manager.mark_cancelled(run.run_id, "sandbox stopped by operator")
        await self.computer_runtime.stop_workspace_sandbox(thread_id)
        return AgentSwitchSnapshot(ok=True, thread_id=thread_id, message="sandbox stopped")

    @staticmethod
    def _control_plane_step(
        *,
        run_id: str,
        thread_id: str,
        step_type: str,
        status: str,
        payload: dict[str, object],
    ) -> RunStep:
        return RunStep(
            step_id=f"step:control:{int(time.time() * 1000)}:{step_type}:{run_id}",
            run_id=run_id,
            thread_id=thread_id,
            step_type=step_type,
            status=status,
            payload=payload,
            created_at=int(time.time()),
        )
