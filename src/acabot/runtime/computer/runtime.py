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
from .editing import prepare_text_edit
from .media import build_read_image_content, detect_supported_image_mime
from .reading import format_read_text
from .contracts import (
    AttachmentStageResult,
    CommandExecutionResult,
    CommandSession,
    ComputerBackend,
    ComputerPolicyDecision,
    ComputerBackendNotImplemented,
    ComputerPolicy,
    ComputerRuntimeConfig,
    WorldInputBundle,
    WorldPathEditResult,
    WorldPathReadResult,
    WorldPathWriteResult,
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
        skill_catalog: "SkillCatalog | None" = None,
    ) -> None:
        """初始化 computer runtime.

        Args:
            config (ComputerRuntimeConfig): computer 子系统运行配置.
            gateway (Any | None): 当前 gateway, 主要用于附件二次解析.
            run_manager (RunManager | None): run 生命周期管理器.
            default_policy (ComputerPolicy | None): 没有显式 computer 决策时的默认 policy.
            skill_catalog (SkillCatalog | None): 当前 skill catalog.
        """

        self.config = config
        self.gateway = gateway
        self.run_manager = run_manager
        self.skill_catalog = skill_catalog
        self.default_policy = default_policy or ComputerPolicy(
            backend="host",
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

    # region run_ctx
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
            agent_id=ctx.agent.agent_id,
            backend_kind=backend.kind,
            workspace_host_path=str(workspace_dir),
            workspace_visible_root="/workspace",
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

        base = parse_computer_policy(ctx.agent.config.get("computer"), defaults=ctx.agent.computer_policy)
        if ctx.computer_policy_decision is None:
            return base
        decision = ctx.computer_policy_decision
        return ComputerPolicy(
            backend=str(decision.backend or base.backend),
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
                agent_id=ctx.agent.agent_id,
                actor_kind=(
                    ctx.computer_policy_decision.actor_kind
                    if ctx.computer_policy_decision is not None
                    else (
                        "subagent"
                        if str(ctx.decision.metadata.get("run_kind", "") or "") == "subagent"
                        else "frontstage_agent"
                    )
                ),
                self_scope_id=ctx.agent.agent_id,
                visible_skill_names=(
                    list(ctx.computer_policy_decision.visible_skills)
                    if ctx.computer_policy_decision is not None
                    and ctx.computer_policy_decision.visible_skills is not None
                    else list(ctx.agent.skills)
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
    # region stage_attachments
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
        """把当前事件的附件正式拉进宿主机 workspace.

        Args:
            thread_id (str): 当前 thread ID.
            run_id (str): 当前 run_id.
            event_id (str): 当前事件 ID.
            attachments (list[EventAttachment]): 要落地的附件列表.
            category (str): 当前附件分类, 默认是 `inbound`.
            world_view: 当前 run 的 Work World 视图.

        Returns:
            AttachmentStageResult: 当前这次 staging 的结果汇总.
        """

        normalized_category = sanitize_filename(category) or "inbound"
        normalized_event_id = sanitize_filename(event_id) or "event"
        target_root = self.workspace_manager.attachments_dir_for_thread(thread_id) / normalized_category / normalized_event_id
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
                snapshot.metadata["execution_path"] = (
                    str(Path(world_view.execution_view.workspace_path) / relative_text)
                    if world_view.execution_view.workspace_path
                    else ""
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

    async def read_world_path(
        self,
        *,
        world_view,
        world_path: str,
        offset: int | None = None,
        limit: int | None = None,
    ) -> WorldPathReadResult:
        """按 world path 读取文件.

        Args:
            world_view: 当前 run 的 Work World 视图.
            world_path (str): 目标 world path.
            offset (int | None): 起始行号, 从 1 开始.
            limit (int | None): 最多返回多少行.

        Returns:
            WorldPathReadResult: 返回给前台工具的读取结果.
        """

        resolved_world_path, host_path = await self._resolve_file_target_for_world_path(
            world_view=world_view,
            world_path=world_path,
            allow_missing=False,
        )
        data = await self.backends["host"].read_bytes(
            path=host_path,
        )
        mime_type = detect_supported_image_mime(data)
        if mime_type:
            content = build_read_image_content(data=data, mime_type=mime_type)
            return WorldPathReadResult(
                world_path=resolved_world_path,
                text="",
                content=content,
                mime_type=mime_type,
            )

        text = data.decode("utf-8", errors="replace")
        page = format_read_text(
            text=text,
            path=resolved_world_path,
            offset=offset,
            limit=limit,
        )
        return WorldPathReadResult(
            world_path=resolved_world_path,
            text=page.text,
            content=page.text,
            mime_type="",
        )

    async def list_workspace_attachments(self, *, thread_id: str) -> list[WorkspaceFileEntry]:
        """列出当前 thread workspace 下已经落地的附件.

        Args:
            thread_id (str): 当前 thread ID.

        Returns:
            list[WorkspaceFileEntry]: `/attachments` 下的目录项.
        """

        attachments_root = self.workspace_manager.attachments_dir_for_thread(thread_id)
        if not attachments_root.exists():
            return []
        items = await self.backends["host"].list_entries(path=attachments_root)
        return [
            WorkspaceFileEntry(
                path=self._join_world_path("/workspace/attachments", item.path),
                kind=item.kind,
                size_bytes=item.size_bytes,
                modified_at=item.modified_at,
            )
            for item in items
        ]

    async def write_world_path(
        self,
        *,
        world_view,
        world_path: str,
        content: str,
    ) -> WorldPathWriteResult:
        """按 world path 写文本文件.

        Args:
            world_view: 当前 run 的 Work World 视图.
            world_path (str): 目标 world path.
            content (str): 要写入的文本.

        Returns:
            WorldPathWriteResult: 返回给前台工具的写入结果.
        """

        resolved_world_path, host_path = await self._resolve_file_target_for_world_path(
            world_view=world_view,
            world_path=world_path,
            allow_missing=True,
        )
        await self.backends["host"].write_text(
            path=host_path,
            content=content,
        )
        if resolved_world_path.startswith("/skills"):
            self.refresh_world_skills_view(world_view)
        return WorldPathWriteResult(
            world_path=resolved_world_path,
            size_bytes=len(content.encode("utf-8")),
        )

    async def edit_world_path(
        self,
        *,
        world_view,
        world_path: str,
        old_text: str,
        new_text: str,
    ) -> WorldPathEditResult:
        """按 world path 改一个文本文件里的指定文字.

        Args:
            world_view: 当前 run 的 Work World 视图.
            world_path (str): 目标 world path.
            old_text (str): 要匹配的旧文本.
            new_text (str): 要写入的新文本.

        Returns:
            WorldPathEditResult: 返回给前台工具的编辑结果.
        """

        resolved_world_path, host_path = await self._resolve_file_target_for_world_path(
            world_view=world_view,
            world_path=world_path,
            allow_missing=False,
        )
        raw_content = await self.backends["host"].read_bytes(
            path=host_path,
        )
        prepared = prepare_text_edit(
            path=resolved_world_path,
            content=raw_content.decode("utf-8", errors="replace"),
            old_text=old_text,
            new_text=new_text,
        )
        await self.backends["host"].write_text(
            path=host_path,
            content=prepared.content,
        )
        if resolved_world_path.startswith("/skills"):
            self.refresh_world_skills_view(world_view)
        return WorldPathEditResult(
            world_path=resolved_world_path,
            diff=prepared.diff,
            first_changed_line=prepared.first_changed_line,
        )

    async def _resolve_file_target_for_world_path(
        self,
        *,
        world_view,
        world_path: str,
        allow_missing: bool,
    ) -> tuple[str, Path]:
        """把 world path 变成真正要读写的宿主机文件路径.

        Args:
            world_view: 当前 run 的 Work World 视图.
            world_path (str): 目标 world path.
            allow_missing (bool): 写文件时允许目标文件暂时不存在.

        Returns:
            tuple[str, Path]: 规范化后的 world path 和真正要操作的宿主机路径.
        """

        await self._ensure_skills_ready_for_world_path(
            world_view=world_view,
            world_path=world_path,
        )
        skill_relative_path = self._skills_relative_path(world_path)
        if skill_relative_path is None:
            resolved = world_view.resolve(world_path)
            return resolved.world_path, Path(resolved.host_path)

        normalized_world_path = self._normalize_world_path(world_path)
        skill_name = skill_relative_path.split("/", 1)[0] if skill_relative_path else ""
        if skill_name:
            world_view.resolve(f"/skills/{skill_name}")
        else:
            world_view.resolve("/skills")
        canonical_root = self.workspace_manager.skills_dir_for_thread(world_view.thread_id).resolve()
        host_path = (canonical_root / skill_relative_path).resolve()
        try:
            host_path.relative_to(canonical_root)
        except ValueError as exc:
            raise ValueError("world path escapes skills root") from exc
        if not allow_missing and not host_path.exists():
            raise FileNotFoundError(f"skill path not materialized in current world: {normalized_world_path}")
        return normalized_world_path, host_path

    async def _ensure_skills_ready_for_world_path(
        self,
        *,
        world_view,
        world_path: str,
    ) -> None:
        """在读取或写入 `/skills/...` 前, 先把当前要用到的 skill 准备好.

        Args:
            world_view: 当前 run 的 Work World 视图.
            world_path (str): 目标 world path.
        """

        skill_relative_path = self._skills_relative_path(world_path)
        if skill_relative_path is None or self.skill_catalog is None:
            return
        skill_name = skill_relative_path.split("/", 1)[0] if skill_relative_path else ""
        if not skill_name or skill_name not in set(world_view.visible_skill_names):
            return
        manifest = self.skill_catalog.get(skill_name)
        if manifest is None:
            return
        await self.ensure_skill_mirrored(
            thread_id=world_view.thread_id,
            skill_name=skill_name,
            source_dir=manifest.host_skill_root_path,
        )
        self.refresh_world_skills_view(world_view)

    @staticmethod
    def _skills_relative_path(world_path: str) -> str | None:
        """从 world path 里取出 `/skills` 根内的相对路径.

        Args:
            world_path (str): 原始 world path.

        Returns:
            str | None: `/skills` 根内相对路径. 不是 `/skills/...` 时返回 `None`.
        """

        normalized = ComputerRuntime._normalize_world_path(world_path)
        if normalized == "/skills":
            return ""
        if not normalized.startswith("/skills/"):
            return None
        return normalized[len("/skills/"):]

    @staticmethod
    def _normalize_world_path(world_path: str) -> str:
        """把传进来的 world path 收成稳定的绝对路径.

        Args:
            world_path (str): 原始 world path.

        Returns:
            str: 规范化后的绝对 world path.
        """

        raw = str(world_path or "").strip()
        if not raw:
            raise ValueError("world path is required")
        if not raw.startswith("/"):
            raw = f"/{raw}"
        parts = [part for part in raw.split("/") if part and part != "."]
        normalized_parts: list[str] = []
        for part in parts:
            if part == "..":
                raise ValueError("world path cannot escape root")
            normalized_parts.append(part)
        return "/" + "/".join(normalized_parts)

    # region skill
    async def ensure_skill_mirrored(self, thread_id: str, skill_name: str, source_dir: str | Path) -> str:
        """把一个 skill 物化到当前 thread 的共享 skills 目录里.

        Args:
            thread_id (str): 当前 thread ID.
            skill_name (str): skill 名字.
            source_dir (str | Path): skill 真源目录.

        Returns:
            str: 物化后的宿主机路径.
        """

        source = Path(source_dir)
        target = self.workspace_manager.skills_dir_for_thread(thread_id) / skill_name
        if target.exists():
            return str(target)
        shutil.copytree(source, target)
        return str(target)

    # NOTE: 会把这个 thread 里已经 load 过的 skill 全部镜像到共享 workspace 的 skills 目录里
    # 一旦某个 skill 被显式 load 过，后续 run 理论上可以把它继续保留在这个 thread 的 /skills 世界里
    # 
    def mark_skill_loaded(self, thread_id: str, skill_name: str) -> None:
        """记录当前 thread 已经显式加载过某个 skill.

        Args:
            thread_id (str): 当前 thread ID.
            skill_name (str): skill 名字.
        """

        if not skill_name:
            return
        self._loaded_skills.setdefault(thread_id, set()).add(skill_name)

    def list_loaded_skills(self, thread_id: str) -> list[str]:
        """列出当前 thread 已标记为 loaded 的 skills.

        Args:
            thread_id (str): 当前 thread ID.

        Returns:
            list[str]: 已标记 loaded 的 skill 名列表.
        """

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
                source_dir=manifest.host_skill_root_path,
            )
            mirrored.append(skill_name)
        if world_view is not None:
            self.refresh_world_skills_view(world_view)
        return mirrored

    def list_mirrored_skills(self, thread_id: str) -> list[str]:
        """列出当前 thread 宿主机上已经物化出来的 skills.

        Args:
            thread_id (str): 当前 thread ID.

        Returns:
            list[str]: 已物化 skill 名列表.
        """

        skills_dir = self.workspace_manager.skills_dir_for_thread(thread_id)
        if not skills_dir.exists():
            return []
        return sorted(path.name for path in skills_dir.iterdir() if path.is_dir())

    async def remove_mirrored_skills(self, thread_id: str) -> None:
        """清空当前 thread 已物化的 skills 目录.

        Args:
            thread_id (str): 当前 thread ID.
        """

        skills_dir = self.workspace_manager.skills_dir_for_thread(thread_id)
        if skills_dir.exists():
            shutil.rmtree(skills_dir)
        skills_dir.mkdir(parents=True, exist_ok=True)
        self._loaded_skills.pop(thread_id, None)

    # region bash
    async def bash_world(
        self,
        *,
        thread_id: str,
        run_id: str = "",
        command: str,
        timeout: int | None = None,
        policy: ComputerPolicy,
        world_view=None,
    ) -> CommandExecutionResult:
        """在当前 shell 用的目录里跑一条命令.

        Args:
            thread_id (str): 当前 thread ID.
            run_id (str): 当前 run ID.
            command (str): 要执行的命令.
            timeout (int | None): 可选超时秒数.
            policy (ComputerPolicy): 当前有效 computer policy.
            world_view: 当前 run 的 Work World 视图.

        Returns:
            CommandExecutionResult: 命令执行结果.
        """

        return await self.exec_once(
            thread_id=thread_id,
            run_id=run_id,
            command=command,
            timeout=timeout,
            policy=policy,
            world_view=world_view,
        )

    async def exec_once(
        self,
        *,
        thread_id: str,
        run_id: str = "",
        command: str,
        timeout: int | None = None,
        policy: ComputerPolicy,
        world_view=None,
    ) -> CommandExecutionResult:
        """执行一次性 shell 命令.

        Args:
            thread_id (str): 当前 thread ID.
            run_id (str): 当前 run_id.
            command (str): 要执行的命令.
            timeout (int | None): 可选超时秒数.
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
        result = await backend.exec_once(
            host_path=workspace,
            command=command,
            policy=policy,
            timeout=timeout,
        )
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

    # region session
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
                world_view.execution_view.workspace_path if world_view is not None else "/workspace"
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
        """向一个已存在的 shell session 写入输入.

        Args:
            thread_id (str): 当前 thread ID.
            session_id (str): 目标 session ID.
            command (str): 要写入的文本.
            run_id (str): 当前 run_id.
        """

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
        """读取一个 shell session 当前缓冲区的输出窗口.

        Args:
            thread_id (str): 当前 thread ID.
            session_id (str): 目标 session ID.
            run_id (str): 当前 run_id.

        Returns:
            CommandExecutionResult: 当前输出窗口快照.
        """

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
        """关闭一个已存在的 shell session.

        Args:
            thread_id (str): 当前 thread ID.
            session_id (str): 目标 session ID.
            run_id (str): 当前 run_id.
        """

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
        """列出当前 thread 活跃的 shell session IDs.

        Args:
            thread_id (str): 当前 thread ID.

        Returns:
            list[str]: 活跃 session ID 列表.
        """

        return sorted(self._sessions.get(thread_id, {}))

    async def close_all_sessions(self, thread_id: str) -> None:
        """关闭当前 thread 的全部 shell sessions.

        Args:
            thread_id (str): 当前 thread ID.
        """

        for session_id in list(self._sessions.get(thread_id, {})):
            await self.close_session(thread_id=thread_id, session_id=session_id)

    async def stop_workspace_sandbox(self, thread_id: str) -> None:
        """停止当前 thread 对应的 backend sandbox.

        Args:
            thread_id (str): 当前 thread ID.
        """

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
        """读取当前 thread 对应 backend 的 sandbox 状态.

        Args:
            thread_id (str): 当前 thread ID.

        Returns:
            WorkspaceSandboxStatus: 当前 sandbox 状态摘要.
        """

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
        """清空当前 thread 的 workspace、session 和镜像 skill 状态.

        Args:
            thread_id (str): 当前 thread ID.
        """

        await self.close_all_sessions(thread_id)
        await self.stop_workspace_sandbox(thread_id)
        self._loaded_skills.pop(thread_id, None)
        self._thread_backend_state.pop(thread_id, None)
        workspace = self.workspace_manager.workspace_dir_for_thread(thread_id)
        if workspace.exists():
            shutil.rmtree(workspace)

    async def list_workspaces(self) -> list[WorkspaceState]:
        """列出当前宿主机上已存在的全部 workspaces.

        Returns:
            list[WorkspaceState]: 当前全部 workspace 状态摘要.
        """

        items: list[WorkspaceState] = []
        for path in self.workspace_manager.list_workspaces():
            thread_id = self.workspace_manager.thread_id_from_workspace_path(path)
            items.append(
                WorkspaceState(
                    thread_id=thread_id,
                    agent_id="",
                    backend_kind=self._backend_for_thread(thread_id),
                    workspace_host_path=str(path),
                    workspace_visible_root="/workspace",
                    available_tools=self._available_tools(self.default_policy),
                    attachment_count=(
                        sum(1 for item in (path / "attachments").rglob("*") if item.is_file())
                        if (path / "attachments").exists()
                        else 0
                    ),
                    mirrored_skill_names=self.list_mirrored_skills(thread_id),
                    active_session_ids=self.list_session_ids(thread_id),
                )
            )
        return items


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

        tools = ["read", "write", "edit"]
        workspace_visible = True
        workspace_shell_path = "/workspace"
        if world_view is not None:
            workspace_policy = world_view.root_policies.get("workspace")
            workspace_visible = bool(workspace_policy is not None and workspace_policy.visible)
            workspace_shell_path = str(world_view.execution_view.workspace_path or "")
        if policy.allow_exec and workspace_visible and workspace_shell_path:
            tools.append("bash")
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
        """读取一个必须存在的 shell session.

        Args:
            thread_id (str): 当前 thread ID.
            session_id (str): 目标 session ID.

        Returns:
            CommandSession: 命中的 session.

        Raises:
            KeyError: session 不存在时抛出.
        """

        session = self._sessions.get(thread_id, {}).get(session_id)
        if session is None:
            raise KeyError("unknown session_id")
        return session

    def _backend_for_thread(self, thread_id: str) -> str:
        """推断当前 thread 当前正在使用哪个 backend.

        Args:
            thread_id (str): 当前 thread ID.

        Returns:
            str: 当前 backend 名字.
        """

        sessions = self._sessions.get(thread_id, {})
        if sessions:
            return next(iter(sessions.values())).backend_kind
        backend_kind = self._thread_backend_state.get(thread_id, "")
        if backend_kind:
            return backend_kind
        return "host"

    def _set_thread_backend_state(self, thread_id: str, backend_kind: str) -> None:
        """记录当前 thread 最近一次实际使用的 backend.

        Args:
            thread_id (str): 当前 thread ID.
            backend_kind (str): backend 名字.
        """

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
        """向当前 run 追加一条 computer 子系统步骤记录.

        Args:
            run_id (str): 当前 run_id.
            thread_id (str): 当前 thread ID.
            step_type (str): 步骤类型.
            status (str): 当前步骤状态.
            payload (dict[str, Any]): 步骤附加数据.
        """

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
