"""runtime.computer 提供 computer 子系统的基础设施实现.

负责:
- workspace 拓扑与路径约束
- host / docker / remote backend 抽象
- inbound attachment staging
- shell session 生命周期
- skill mirror seam

如果要把这些能力给模型使用, 需要在上层再通过 tool adapter 暴露.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import os
from pathlib import Path
import re
import shutil
import time
import uuid
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from acabot.types import EventAttachment

if TYPE_CHECKING:
    from .models import RunContext
    from .runs import RunManager
    from .skills import SkillCatalog


ComputerBackendKind = str
ComputerNetworkMode = str
AttachmentSourceKind = str
AttachmentDownloadStatus = str


class ComputerBackendNotImplemented(RuntimeError):
    """选择了当前版本未实现的 backend."""


@dataclass(slots=True)
class ComputerPolicy:
    """Agent 级 computer policy.

    这是“这个 agent 默认怎么用 computer 子系统”的稳定策略,
    不是 runtime plugin 或 tool 的配置.
    """

    backend: ComputerBackendKind = "host"
    read_only: bool = False
    allow_write: bool = True
    allow_exec: bool = True
    allow_sessions: bool = True # 长连接
    auto_stage_attachments: bool = True # 自动下载/暂存消息附件
    network_mode: ComputerNetworkMode = "enabled"


@dataclass(slots=True)
class ComputerRuntimeOverride:
    """thread metadata 中的运行时 computer override.

    只覆盖 thread 级的临时执行策略, 不改变 agent 的真源配置.
    """

    backend: str = ""
    read_only: bool | None = None
    allow_write: bool | None = None
    allow_exec: bool | None = None
    allow_sessions: bool | None = None
    network_mode: str = ""
    # auto_stage_attachments 像 profile / policy 的稳定行为, 不适合 runtime override.

@dataclass(slots=True)
class WorkspaceState:
    """当前 run 可见的 computer/workspace 状态摘要.

    它是给 runtime、tool 上下文和 prompt slot 用的轻量视图,
    不是完整文件树或完整 sandbox 状态.
    """

    thread_id: str
    agent_id: str
    backend_kind: str
    workspace_host_path: str # 宿主机上的真实目录路径
    workspace_visible_root: str # 模型和工具看到的稳定路径前缀, 如 `/workspace`
    read_only: bool
    available_tools: list[str] = field(default_factory=list)
    attachment_count: int = 0 # 这轮 staged 到 workspace 的附件数量
    mirrored_skill_names: list[str] = field(default_factory=list) # 这块 workspace 镜像进来的 skill
    active_session_ids: list[str] = field(default_factory=list) # 当前 thread 下 active 的 shell session 列表


@dataclass(slots=True)
class WorkspaceSandboxStatus:
    """当前 thread workspace 对应 sandbox 的状态."""

    thread_id: str
    backend_kind: str
    active: bool
    session_count: int = 0
    container_id: str = "" # 如果是 docker backend, 这里是容器 ID, 否则留空
    message: str = "" # 给 control plane 的简短说明


@dataclass(slots=True)
class WorkspaceFileEntry:
    """workspace 里的一条文件或目录记录."""

    path: str
    kind: str
    size_bytes: int = 0
    modified_at: int = 0


@dataclass(slots=True)
class AttachmentSnapshot:
    """已经索引或落地的 inbound attachment.一条附件从“平台引用”到“本地副本”的状态快照."""

    event_id: str # 附件是从哪条事件来的
    attachment_index: int # 在这条 event 的附件列表里, 它是第几个
    type: str # image/file/audio/video ...
    original_source: str # 附件原始来源, 可能是 URL, 也可能是平台内部 ID 等等
    source_kind: AttachmentSourceKind # source 是哪种来源类型, 如 direct_url、platform_file_id、platform_api_resolved
    staged_path: str = ""
    size_bytes: int = 0
    download_status: AttachmentDownloadStatus = "pending"
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AttachmentStageResult:
    """一次 attachment staging 的结果."""

    snapshots: list[AttachmentSnapshot] = field(default_factory=list)
    total_size_bytes: int = 0
    had_failures: bool = False


@dataclass(slots=True)
class CommandExecutionResult:
    """一次 exec 或 bash_read 的结果."""

    ok: bool
    exit_code: int | None = None
    stdout_excerpt: str = "" # 截断后的 stdout 摘要
    stderr_excerpt: str = "" # 截断后的 stderr 摘要
    stdout_truncated: bool = False # stdout 是否被截断
    stderr_truncated: bool = False # stderr 是否被截断
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CommandSession:
    """一个 thread 级 shell session."""

    session_id: str
    thread_id: str
    backend_kind: str
    cwd_visible: str # 上层/模型看的当前工作目录, 一般是 /workspace
    cwd_host_path: str # 宿主机上的真实工作目录
    created_at: int
    process: asyncio.subprocess.Process | None = field(default=None, repr=False) # 真正的底层进程对象
    stdout_buffer: deque[str] = field(default_factory=deque, repr=False)
    stderr_buffer: deque[str] = field(default_factory=deque, repr=False)
    stdout_size: int = 0
    stderr_size: int = 0


@dataclass(slots=True)
class ComputerRuntimeConfig:
    """computer 子系统的全局运行配置.

    这描述的是 runtime 基础设施默认值和资源限制,
    不是某个 agent 或某个 thread 的临时状态.
    """

    root_dir: str # 整个 computer/workspace 系统的根目录
    skill_catalog_dir: str
    max_attachment_size_bytes: int = 64 * 1024 * 1024
    max_total_attachment_bytes_per_run: int = 256 * 1024 * 1024
    attachment_download_timeout_sec: int = 30
    attachment_download_retries: int = 2
    exec_stdout_window_bytes: int = 256 * 1024
    exec_stderr_window_bytes: int = 256 * 1024
    docker_image: str = "python:3.12-slim"
    docker_network_mode: str = "bridge"
    docker_read_only_rootfs: bool = True

# region ComputerBackendProtocol
class ComputerBackend(Protocol):
    """computer backend 协议.

    backend 是 computer 子系统底层执行后端.
    tool 层不应该直接知道具体 backend 怎么工作.
    """

    kind: str

    async def ensure_workspace(self, *, host_path: Path, visible_root: str) -> None:
        ...

    async def list_entries(self, *, host_path: Path, relative_path: str) -> list[WorkspaceFileEntry]:
        ...

    async def read_text(self, *, host_path: Path, relative_path: str) -> str:
        ...

    async def write_text(self, *, host_path: Path, relative_path: str, content: str) -> None:
        ...

    async def grep_text(self, *, host_path: Path, relative_path: str, pattern: str) -> list[dict[str, Any]]:
        ...

    async def exec_once(self, *, host_path: Path, command: str, policy: ComputerPolicy) -> CommandExecutionResult:
        ...

    async def open_session(self, *, session: CommandSession, policy: ComputerPolicy) -> None:
        ...

    async def write_session(self, session: CommandSession, command: str) -> None:
        ...

    async def close_session(self, session: CommandSession) -> None:
        ...

    async def stop_workspace_sandbox(self, *, thread_id: str, host_path: Path) -> None:
        ...

    async def get_sandbox_status(self, *, thread_id: str, host_path: Path) -> WorkspaceSandboxStatus:
        ...

# region AttachmentResolverProtocol
class AttachmentResolver(Protocol):
    """附件 staging 解析协议.

    负责把平台附件引用解析成 workspace 里的本地副本或失败快照.
    """

    async def stage(
        self,
        *,
        attachment: EventAttachment,
        event_id: str,
        attachment_index: int,
        target_dir: Path,
        config: ComputerRuntimeConfig,
        gateway: Any | None,
    ) -> AttachmentSnapshot:
        ...


def parse_computer_policy(
    raw: object,
    *,
    defaults: ComputerPolicy | None = None,
) -> ComputerPolicy:
    """把原始配置归一化成 ComputerPolicy."""

    base = defaults or ComputerPolicy()
    if raw is None or raw == "":
        return ComputerPolicy(
            backend=base.backend,
            read_only=base.read_only,
            allow_write=base.allow_write,
            allow_exec=base.allow_exec,
            allow_sessions=base.allow_sessions,
            auto_stage_attachments=base.auto_stage_attachments,
            network_mode=base.network_mode,
        )
    if not isinstance(raw, dict):
        raise ValueError("computer policy must be a mapping")
    return ComputerPolicy(
        backend=str(raw.get("backend", base.backend) or base.backend),
        read_only=bool(raw.get("read_only", base.read_only)),
        allow_write=bool(raw.get("allow_write", base.allow_write)),
        allow_exec=bool(raw.get("allow_exec", base.allow_exec)),
        allow_sessions=bool(raw.get("allow_sessions", base.allow_sessions)),
        auto_stage_attachments=bool(
            raw.get("auto_stage_attachments", base.auto_stage_attachments)
        ),
        network_mode=str(raw.get("network_mode", base.network_mode) or base.network_mode),
    )


def parse_computer_override(raw: object) -> ComputerRuntimeOverride:
    """从 thread metadata 读取 computer override."""

    if not isinstance(raw, dict):
        return ComputerRuntimeOverride()
    return ComputerRuntimeOverride(
        backend=str(raw.get("backend", "") or ""),
        read_only=raw.get("read_only"),
        allow_write=raw.get("allow_write"),
        allow_exec=raw.get("allow_exec"),
        allow_sessions=raw.get("allow_sessions"),
        network_mode=str(raw.get("network_mode", "") or ""),
    )

# region WorkspaceMgr
class WorkspaceManager:
    """workspace 路径和文件系统布局管理器."""

    def __init__(self, config: ComputerRuntimeConfig) -> None:
        """
        Args:
            config: 整个 computer 子系统的全局配置对象.
            root_dir: workspace 根目录, 所有 thread workspace 都挂在下面.
            skill_catalog_dir: 统一 skill catalog 的真实宿主路径.
        """
        self.config = config
        self.root_dir = Path(config.root_dir).expanduser()
        self.skill_catalog_dir = Path(config.skill_catalog_dir).expanduser()

    def visible_root(self) -> str:
        return "/workspace"

    def workspace_dir_for_thread(self, thread_id: str) -> Path:
        safe = _safe_thread_id(thread_id)
        return self.root_dir / "threads" / safe / "workspace"

    def attachments_dir_for_thread(self, thread_id: str) -> Path:
        return self.workspace_dir_for_thread(thread_id) / "attachments"

    def scratch_dir_for_thread(self, thread_id: str) -> Path:
        return self.workspace_dir_for_thread(thread_id) / "scratch"

    def skills_dir_for_thread(self, thread_id: str) -> Path:
        return self.workspace_dir_for_thread(thread_id) / "skills"

    def ensure_workspace_layout(self, thread_id: str) -> Path:
        workspace = self.workspace_dir_for_thread(thread_id)
        self.attachments_dir_for_thread(thread_id).mkdir(parents=True, exist_ok=True)
        self.scratch_dir_for_thread(thread_id).mkdir(parents=True, exist_ok=True)
        self.skills_dir_for_thread(thread_id).mkdir(parents=True, exist_ok=True)
        (workspace / ".thread_id").write_text(thread_id, encoding="utf-8")
        return workspace

    def resolve_relative_path(self, thread_id: str, relative_path: str) -> Path:
        base = self.workspace_dir_for_thread(thread_id).resolve()
        requested = (base / relative_path.lstrip("/")).resolve()
        if not _is_subpath(requested, base):
            raise ValueError("path escapes workspace")
        if requested.is_symlink():
            real = requested.resolve()
            if not _is_subpath(real, base):
                raise ValueError("symlink escapes workspace")
        return requested

    def list_workspaces(self) -> list[Path]:
        root = self.root_dir / "threads"
        if not root.exists():
            return []
        return sorted(path / "workspace" for path in root.iterdir() if (path / "workspace").exists())

    @staticmethod
    def thread_id_from_workspace_path(path: Path) -> str:
        marker = path / ".thread_id"
        if marker.exists():
            return marker.read_text(encoding="utf-8").strip()
        return _thread_id_from_path(path)

# region UrlAttaRes
class UrlAttachmentResolver:
    """处理直接 URL 和 file URL 的附件解析器."""

    async def stage(
        self,
        *,
        attachment: EventAttachment,
        event_id: str,
        attachment_index: int,
        target_dir: Path,
        config: ComputerRuntimeConfig,
        gateway: Any | None,
    ) -> AttachmentSnapshot:
        _ = gateway
        source = str(attachment.source or "")
        # 创建快照 记录附件的元信息
        snapshot = AttachmentSnapshot(
            event_id=event_id,
            attachment_index=attachment_index,
            type=attachment.type,
            original_source=source,
            source_kind=_infer_source_kind(source),
            metadata=dict(attachment.metadata),
        )
        parsed = urlparse(source)
        # 只处理 http/https/file 协议
        if parsed.scheme in {"http", "https", "file"}:
            filename = attachment.name or f"attachment-{attachment_index}"
            filename = _sanitize_filename(filename)
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / filename
            last_error = ""
            for _attempt in range(config.attachment_download_retries + 1):
                try:
                    size = await asyncio.wait_for(
                        asyncio.to_thread(
                            _download_attachment,
                            source,
                            target,
                            config.max_attachment_size_bytes,
                        ),
                        timeout=config.attachment_download_timeout_sec,
                    )
                    snapshot.staged_path = str(target)
                    snapshot.size_bytes = size
                    snapshot.download_status = "staged"
                    return snapshot
                except Exception as exc:  # noqa: PERF203
                    last_error = str(exc)
            snapshot.download_status = "failed"
            snapshot.error = last_error or "download failed"
            return snapshot

        snapshot.download_status = "failed"
        snapshot.error = "unsupported attachment source"
        return snapshot


class GatewayAttachmentResolver:
    """先尝试 URL, 不行再尝试 gateway.call_api 二次解析."""

    def __init__(self) -> None:
        self.url_resolver = UrlAttachmentResolver()

    async def stage(
        self,
        *,
        attachment: EventAttachment,
        event_id: str,
        attachment_index: int,
        target_dir: Path,
        config: ComputerRuntimeConfig,
        gateway: Any | None,
    ) -> AttachmentSnapshot:
        direct = await self.url_resolver.stage(
            attachment=attachment,
            event_id=event_id,
            attachment_index=attachment_index,
            target_dir=target_dir,
            config=config,
            gateway=gateway,
        )
        if direct.download_status == "staged":
            return direct
        if gateway is None or not callable(getattr(gateway, "call_api", None)):
            return direct

        source = str(attachment.source or attachment.metadata.get("id") or "")
        if not source:
            return direct
        for action in _attachment_api_candidates(attachment.type):
            try:
                response = await gateway.call_api(action, {"file_id": source})
            except Exception as exc:  # noqa: PERF203
                direct.error = str(exc)
                continue
            if str(response.get("status", "")) != "ok":
                continue
            resolved = _extract_resolved_attachment_source(response.get("data"))
            if not resolved:
                continue
            resolved_attachment = EventAttachment(
                type=attachment.type,
                source=resolved,
                name=attachment.name,
                mime_type=attachment.mime_type,
                metadata={
                    **dict(attachment.metadata),
                    "resolved_via": action,
                },
            )
            staged = await self.url_resolver.stage(
                attachment=resolved_attachment,
                event_id=event_id,
                attachment_index=attachment_index,
                target_dir=target_dir,
                config=config,
                gateway=gateway,
            )
            if staged.download_status == "staged":
                staged.source_kind = "platform_api_resolved"
                return staged
        return direct

# region HostBackend
class HostComputerBackend:
    """本地宿主机 backend."""

    kind = "host"

    def __init__(self, *, stdout_window_bytes: int, stderr_window_bytes: int) -> None:
        self.stdout_window_bytes = stdout_window_bytes
        self.stderr_window_bytes = stderr_window_bytes
        self._session_tasks: dict[str, list[asyncio.Task[None]]] = {}

    async def ensure_workspace(self, *, host_path: Path, visible_root: str) -> None:
        _ = visible_root
        host_path.mkdir(parents=True, exist_ok=True)

    async def list_entries(self, *, host_path: Path, relative_path: str) -> list[WorkspaceFileEntry]:
        path = (host_path / relative_path.lstrip("/")).resolve()
        if not _is_subpath(path, host_path.resolve()):
            raise ValueError("path escapes workspace")
        if not path.exists():
            return []
        if path.is_file():
            stat = path.stat()
            return [
                WorkspaceFileEntry(
                    path=_relative_visible_path(path, host_path),
                    kind="file",
                    size_bytes=stat.st_size,
                    modified_at=int(stat.st_mtime),
                )
            ]
        items: list[WorkspaceFileEntry] = []
        for item in sorted(path.iterdir(), key=lambda entry: entry.name):
            stat = item.stat()
            items.append(
                WorkspaceFileEntry(
                    path=_relative_visible_path(item, host_path),
                    kind="dir" if item.is_dir() else "file",
                    size_bytes=0 if item.is_dir() else stat.st_size,
                    modified_at=int(stat.st_mtime),
                )
            )
        return items

    async def read_text(self, *, host_path: Path, relative_path: str) -> str:
        path = (host_path / relative_path.lstrip("/")).resolve()
        if not _is_subpath(path, host_path.resolve()):
            raise ValueError("path escapes workspace")
        return path.read_text(encoding="utf-8")

    async def write_text(self, *, host_path: Path, relative_path: str, content: str) -> None:
        path = (host_path / relative_path.lstrip("/")).resolve()
        if not _is_subpath(path, host_path.resolve()):
            raise ValueError("path escapes workspace")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    async def grep_text(self, *, host_path: Path, relative_path: str, pattern: str) -> list[dict[str, Any]]:
        root = (host_path / relative_path.lstrip("/")).resolve()
        if not _is_subpath(root, host_path.resolve()):
            raise ValueError("path escapes workspace")
        if not root.exists():
            return []
        compiled = re.compile(pattern)
        results: list[dict[str, Any]] = []
        files = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file())
        for file_path in files:
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if compiled.search(line):
                    results.append(
                        {
                            "path": _relative_visible_path(file_path, host_path),
                            "line": line_no,
                            "content": line,
                        }
                    )
        return results

    async def exec_once(self, *, host_path: Path, command: str, policy: ComputerPolicy) -> CommandExecutionResult:
        if not policy.allow_exec:
            raise PermissionError("exec is disabled by computer policy")
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(host_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return CommandExecutionResult(
            ok=process.returncode == 0,
            exit_code=process.returncode,
            stdout_excerpt=_excerpt_bytes(stdout, self.stdout_window_bytes),
            stderr_excerpt=_excerpt_bytes(stderr, self.stderr_window_bytes),
            stdout_truncated=len(stdout) > self.stdout_window_bytes,
            stderr_truncated=len(stderr) > self.stderr_window_bytes,
        )

    async def open_session(self, *, session: CommandSession, policy: ComputerPolicy) -> None:
        if not policy.allow_sessions:
            raise PermissionError("shell sessions are disabled by computer policy")
        process = await asyncio.create_subprocess_exec(
            "/bin/sh",
            cwd=session.cwd_host_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._attach_process(session, process)

    def _attach_process(
        self,
        session: CommandSession,
        process: asyncio.subprocess.Process,
    ) -> None:
        session.process = process
        self._session_tasks[session.session_id] = [
            asyncio.create_task(
                self._drain_stream(
                    stream=process.stdout,
                    buffer=session.stdout_buffer,
                    size_attr="stdout_size",
                    session=session,
                    window_bytes=self.stdout_window_bytes,
                )
            ),
            asyncio.create_task(
                self._drain_stream(
                    stream=process.stderr,
                    buffer=session.stderr_buffer,
                    size_attr="stderr_size",
                    session=session,
                    window_bytes=self.stderr_window_bytes,
                )
            ),
        ]

    async def write_session(self, session: CommandSession, command: str) -> None:
        if session.process is None or session.process.stdin is None:
            raise RuntimeError("session is not active")
        session.process.stdin.write(command.encode("utf-8"))
        await session.process.stdin.drain()

    async def close_session(self, session: CommandSession) -> None:
        if session.process is None:
            return
        if session.process.stdin is not None:
            session.process.stdin.close()
        try:
            await asyncio.wait_for(session.process.wait(), timeout=2)
        except asyncio.TimeoutError:
            session.process.kill()
            await session.process.wait()
        for task in self._session_tasks.pop(session.session_id, []):
            task.cancel()
        session.process = None

    async def stop_workspace_sandbox(self, *, thread_id: str, host_path: Path) -> None:
        _ = thread_id, host_path
        return None

    async def get_sandbox_status(self, *, thread_id: str, host_path: Path) -> WorkspaceSandboxStatus:
        _ = host_path
        return WorkspaceSandboxStatus(
            thread_id=thread_id,
            backend_kind=self.kind,
            active=False,
            message="host backend has no dedicated sandbox",
        )

    async def _drain_stream(
        self,
        *,
        stream: asyncio.StreamReader | None,
        buffer: deque[str],
        size_attr: str,
        session: CommandSession,
        window_bytes: int,
    ) -> None:
        if stream is None:
            return
        while not stream.at_eof():
            chunk = await stream.readline()
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            buffer.append(text)
            setattr(session, size_attr, getattr(session, size_attr) + len(chunk))
            while getattr(session, size_attr) > window_bytes and buffer:
                removed = buffer.popleft()
                setattr(session, size_attr, getattr(session, size_attr) - len(removed.encode("utf-8")))

# region DockerBackend
class DockerSandboxBackend:
    """Docker-backed sandbox backend.

    当前先使用 docker CLI 实现; 若环境未安装 docker, 运行时明确报错.
    """

    kind = "docker"

    def __init__(self, *, image: str, stdout_window_bytes: int, stderr_window_bytes: int, network_mode: str) -> None:
        self.image = image
        self.stdout_window_bytes = stdout_window_bytes
        self.stderr_window_bytes = stderr_window_bytes
        self.network_mode = network_mode
        self._containers: dict[str, str] = {}
        self._host_delegate = HostComputerBackend(
            stdout_window_bytes=stdout_window_bytes,
            stderr_window_bytes=stderr_window_bytes,
        )

    async def ensure_workspace(self, *, host_path: Path, visible_root: str) -> None:
        _ = visible_root
        host_path.mkdir(parents=True, exist_ok=True)

    async def list_entries(self, *, host_path: Path, relative_path: str) -> list[WorkspaceFileEntry]:
        return await self._host_delegate.list_entries(host_path=host_path, relative_path=relative_path)

    async def read_text(self, *, host_path: Path, relative_path: str) -> str:
        return await self._host_delegate.read_text(host_path=host_path, relative_path=relative_path)

    async def write_text(self, *, host_path: Path, relative_path: str, content: str) -> None:
        return await self._host_delegate.write_text(host_path=host_path, relative_path=relative_path, content=content)

    async def grep_text(self, *, host_path: Path, relative_path: str, pattern: str) -> list[dict[str, Any]]:
        return await self._host_delegate.grep_text(host_path=host_path, relative_path=relative_path, pattern=pattern)

    async def exec_once(self, *, host_path: Path, command: str, policy: ComputerPolicy) -> CommandExecutionResult:
        if not policy.allow_exec:
            raise PermissionError("exec is disabled by computer policy")
        container = await self._ensure_container(thread_id=_thread_id_from_path(host_path), host_path=host_path)
        process = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            container,
            "/bin/sh",
            "-lc",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return CommandExecutionResult(
            ok=process.returncode == 0,
            exit_code=process.returncode,
            stdout_excerpt=_excerpt_bytes(stdout, self.stdout_window_bytes),
            stderr_excerpt=_excerpt_bytes(stderr, self.stderr_window_bytes),
            stdout_truncated=len(stdout) > self.stdout_window_bytes,
            stderr_truncated=len(stderr) > self.stderr_window_bytes,
            metadata={"container_id": container},
        )

    async def open_session(self, *, session: CommandSession, policy: ComputerPolicy) -> None:
        if not policy.allow_sessions:
            raise PermissionError("shell sessions are disabled by computer policy")
        container = await self._ensure_container(
            thread_id=session.thread_id,
            host_path=Path(session.cwd_host_path),
        )
        process = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            "-i",
            container,
            "/bin/sh",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
        )
        self._host_delegate._attach_process(session, process)

    async def write_session(self, session: CommandSession, command: str) -> None:
        return await self._host_delegate.write_session(session, command)

    async def close_session(self, session: CommandSession) -> None:
        return await self._host_delegate.close_session(session)

    async def stop_workspace_sandbox(self, *, thread_id: str, host_path: Path) -> None:
        _ = host_path
        container = self._containers.pop(thread_id, "")
        if not container:
            return
        process = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            container,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()

    async def get_sandbox_status(self, *, thread_id: str, host_path: Path) -> WorkspaceSandboxStatus:
        _ = host_path
        container = self._containers.get(thread_id, "")
        return WorkspaceSandboxStatus(
            thread_id=thread_id,
            backend_kind=self.kind,
            active=bool(container),
            container_id=container,
            message="docker sandbox active" if container else "docker sandbox not started",
        )

    async def _ensure_container(self, *, thread_id: str, host_path: Path) -> str:
        existing = self._containers.get(thread_id)
        if existing:
            return existing
        container = f"acabot-{hashlib.sha256(thread_id.encode('utf-8')).hexdigest()[:16]}"
        process = await asyncio.create_subprocess_exec(
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            container,
            "-w",
            "/workspace",
            "-v",
            f"{host_path}:/workspace",
            "--network",
            self.network_mode,
            self.image,
            "sleep",
            "infinity",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="replace") or "failed to start docker sandbox")
        self._containers[thread_id] = container
        return container

# region RemoteComputerBackend
class RemoteComputerBackend:
    """remote sandbox 占位 backend."""

    kind = "remote"

    async def ensure_workspace(self, *, host_path: Path, visible_root: str) -> None:
        _ = host_path, visible_root
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def list_entries(self, *, host_path: Path, relative_path: str) -> list[WorkspaceFileEntry]:
        _ = host_path, relative_path
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def read_text(self, *, host_path: Path, relative_path: str) -> str:
        _ = host_path, relative_path
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def write_text(self, *, host_path: Path, relative_path: str, content: str) -> None:
        _ = host_path, relative_path, content
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def grep_text(self, *, host_path: Path, relative_path: str, pattern: str) -> list[dict[str, Any]]:
        _ = host_path, relative_path, pattern
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def exec_once(self, *, host_path: Path, command: str, policy: ComputerPolicy) -> CommandExecutionResult:
        _ = host_path, command, policy
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def open_session(self, *, session: CommandSession, policy: ComputerPolicy) -> None:
        _ = session, policy
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def write_session(self, session: CommandSession, command: str) -> None:
        _ = session, command
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def close_session(self, session: CommandSession) -> None:
        _ = session
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def stop_workspace_sandbox(self, *, thread_id: str, host_path: Path) -> None:
        _ = thread_id, host_path
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def get_sandbox_status(self, *, thread_id: str, host_path: Path) -> WorkspaceSandboxStatus:
        _ = host_path
        return WorkspaceSandboxStatus(
            thread_id=thread_id,
            backend_kind=self.kind,
            active=False,
            message="remote computer backend is not implemented",
        )

# region ComputerRuntime
class ComputerRuntime:
    """computer 子系统的统一运行时入口.

    这是基础设施本体:
    - 管理 workspace
    - 选择 backend
    - 处理附件 staging
    - 管理 shell session
    - 给控制面和 tool adapter 复用
    """

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
    ) -> AttachmentStageResult:
        target_root = self.workspace_manager.attachments_dir_for_thread(thread_id) / "inbound" / event_id
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

    async def clear_thread_override(self, *, thread) -> None:
        thread.metadata.pop("computer_override", None)

    @staticmethod
    def _apply_override(policy: ComputerPolicy, override: ComputerRuntimeOverride) -> ComputerPolicy:
        merged = ComputerPolicy(
            backend=override.backend or policy.backend,
            read_only=policy.read_only if override.read_only is None else bool(override.read_only),
            allow_write=policy.allow_write if override.allow_write is None else bool(override.allow_write),
            allow_exec=policy.allow_exec if override.allow_exec is None else bool(override.allow_exec),
            allow_sessions=policy.allow_sessions if override.allow_sessions is None else bool(override.allow_sessions),
            auto_stage_attachments=policy.auto_stage_attachments,
            network_mode=override.network_mode or policy.network_mode,
        )
        return merged

    def _require_session(self, thread_id: str, session_id: str) -> CommandSession:
        session = self._sessions.get(thread_id, {}).get(session_id)
        if session is None:
            raise KeyError("unknown session_id")
        return session

    def _backend_for_thread(self, thread_id: str) -> str:
        sessions = self._sessions.get(thread_id, {})
        if sessions:
            return next(iter(sessions.values())).backend_kind
        return "host"

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
        from .models import RunStep

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



def _safe_thread_id(thread_id: str) -> str:
    """将 thread ID 转换为安全的标识符字符串
    
    将非 字母数字,点号,下划线,连字符的字符替换为下划线, 并去除首尾的下划线.
    如果结果为空,则返回默认的 "thread".
    Example:
        >>> _safe_thread_id("thread-123@abc")
        'thread-123_abc'
        >>> _safe_thread_id("@@@")
        'thread'
    """
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", thread_id).strip("_") or "thread"


def _sanitize_filename(name: str) -> str:
    """将字符串清理为安全的文件名.
    
    将非 字母数字,点号,下划线,连字符 的字符替换为下划线, 并去除首尾的下划线.
    如果结果为空，则返回默认的 "attachment".
    Example:
        >>> _sanitize_filename("my file<>:.txt")
        'my_file_.txt'
        >>> _sanitize_filename("!!!")
        'attachment'
    """
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("_") or "attachment"


def _is_subpath(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _relative_visible_path(path: Path, workspace_root: Path) -> str:
    return "/" + str(path.resolve().relative_to(workspace_root.resolve()))


def _infer_source_kind(source: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        return "direct_url"
    if parsed.scheme == "file":
        return "platform_api_resolved"
    if source:
        return "platform_file_id"
    return "unknown"


def _attachment_api_candidates(attachment_type: str) -> list[str]:
    mapping = {
        "image": ["get_image", "get_file", "get_msg"],
        "file": ["get_file", "get_group_file_url"],
        "audio": ["get_record", "get_file"],
        "video": ["get_video", "get_file"],
    }
    return list(mapping.get(attachment_type, ["get_file"]))


def _extract_resolved_attachment_source(data: Any) -> str:
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return ""
    for key in ("url", "download_url", "file", "path", "src"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    inner_file = data.get("file")
    if isinstance(inner_file, dict):
        for key in ("url", "download_url", "path"):
            value = inner_file.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _download_attachment(source: str, target: Path, max_size_bytes: int) -> int:
    request = Request(source, headers={"User-Agent": "AcaBot/1.0"})
    size = 0
    with urlopen(request) as resp, target.open("wb") as handle:
        while True:
            chunk = resp.read(1024 * 64)
            if not chunk:
                break
            size += len(chunk)
            if size > max_size_bytes:
                raise RuntimeError("attachment exceeds max size")
            handle.write(chunk)
    return size


def _excerpt_bytes(raw: bytes, limit: int) -> str:
    if len(raw) <= limit:
        return raw.decode("utf-8", errors="replace")
    head = raw[: limit // 2].decode("utf-8", errors="replace")
    tail = raw[-(limit // 2) :].decode("utf-8", errors="replace")
    return f"{head}\n...[truncated]...\n{tail}"


def _thread_id_from_path(path: Path) -> str:
    if path.name == "workspace":
        return path.parent.name
    return path.name
