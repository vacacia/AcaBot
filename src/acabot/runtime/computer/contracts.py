"""runtime.computer.contracts 定义 computer 子系统公开契约."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from acabot.types import EventAttachment


ComputerBackendKind = str
ComputerNetworkMode = str
AttachmentSourceKind = str
AttachmentDownloadStatus = str


class ComputerBackendNotImplemented(RuntimeError):
    """选择了当前版本未实现的 backend."""


@dataclass(slots=True)
class ComputerPolicy:
    """Agent 级 computer policy."""

    backend: ComputerBackendKind = "host"
    read_only: bool = False
    allow_write: bool = True
    allow_exec: bool = True
    allow_sessions: bool = True
    auto_stage_attachments: bool = True
    network_mode: ComputerNetworkMode = "enabled"


@dataclass(slots=True)
class ComputerRuntimeOverride:
    """thread metadata 中的运行时 computer override."""

    backend: str = ""
    read_only: bool | None = None
    allow_write: bool | None = None
    allow_exec: bool | None = None
    allow_sessions: bool | None = None
    network_mode: str = ""


@dataclass(slots=True)
class WorkspaceState:
    """当前 run 可见的 computer/workspace 状态摘要."""

    thread_id: str
    agent_id: str
    backend_kind: str
    workspace_host_path: str
    workspace_visible_root: str
    read_only: bool
    available_tools: list[str] = field(default_factory=list)
    attachment_count: int = 0
    mirrored_skill_names: list[str] = field(default_factory=list)
    active_session_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkspaceSandboxStatus:
    """当前 thread workspace 对应 sandbox 的状态."""

    thread_id: str
    backend_kind: str
    active: bool
    session_count: int = 0
    container_id: str = ""
    message: str = ""


@dataclass(slots=True)
class WorkspaceFileEntry:
    """workspace 里的一条文件或目录记录."""

    path: str
    kind: str
    size_bytes: int = 0
    modified_at: int = 0


@dataclass(slots=True)
class AttachmentSnapshot:
    """已经索引或落地的 inbound attachment 状态快照."""

    event_id: str
    attachment_index: int
    type: str
    original_source: str
    source_kind: AttachmentSourceKind
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
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CommandSession:
    """一个 thread 级 shell session."""

    session_id: str
    thread_id: str
    backend_kind: str
    cwd_visible: str
    cwd_host_path: str
    created_at: int
    process: asyncio.subprocess.Process | None = field(default=None, repr=False)
    stdout_buffer: deque[str] = field(default_factory=deque, repr=False)
    stderr_buffer: deque[str] = field(default_factory=deque, repr=False)
    stdout_size: int = 0
    stderr_size: int = 0


@dataclass(slots=True)
class ComputerRuntimeConfig:
    """computer 子系统的全局运行配置."""

    root_dir: str
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


class ComputerBackend(Protocol):
    """computer backend 协议."""

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


class AttachmentResolver(Protocol):
    """附件 staging 解析协议."""

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


__all__ = [
    "AttachmentResolver",
    "AttachmentSnapshot",
    "AttachmentStageResult",
    "CommandExecutionResult",
    "CommandSession",
    "ComputerBackend",
    "ComputerBackendKind",
    "ComputerBackendNotImplemented",
    "ComputerNetworkMode",
    "ComputerPolicy",
    "ComputerRuntimeConfig",
    "ComputerRuntimeOverride",
    "WorkspaceFileEntry",
    "WorkspaceSandboxStatus",
    "WorkspaceState",
    "parse_computer_override",
    "parse_computer_policy",
]
