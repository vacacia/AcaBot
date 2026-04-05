"""runtime.computer.contracts 定义 computer 子系统公开契约."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from acabot.types import EventAttachment
from ..contracts import ComputerPolicyDecision


ComputerBackendKind = str
ComputerNetworkMode = str
AttachmentSourceKind = str
AttachmentDownloadStatus = str


class ComputerBackendNotImplemented(RuntimeError):
    """选择了当前版本未实现的 backend."""


@dataclass(slots=True)
class ComputerPolicy:
    """Agent 级 computer policy.

    Attributes:
        backend (str): 当前 run 使用的 backend.
        allow_exec (bool): 是否允许一次性 shell 命令.
        allow_sessions (bool): 是否允许持久 shell session.
        auto_stage_attachments (bool): 是否自动把附件拉进 Work World.
        network_mode (str): backend 网络模式.
    """

    backend: ComputerBackendKind = "host"
    allow_exec: bool = True
    allow_sessions: bool = True
    auto_stage_attachments: bool = True
    network_mode: ComputerNetworkMode = "enabled"


@dataclass(slots=True)
class WorldRootPolicy:
    """单个 Work World root 的可见性定义.

    Attributes:
        root_kind (str): root 名字, 例如 `workspace`.
        visible (bool): 当前 actor 是否看得见这个 root.
    """

    root_kind: str
    visible: bool


@dataclass(slots=True)
class ResolvedWorldPath:
    """一次 world path 解析结果.

    Attributes:
        world_path (str): 模型侧使用的 world path.
        root_kind (str): 命中的 root 名字.
        relative_path (str): root 内相对路径.
        host_path (str): 实际宿主机路径.
        execution_path (str): shell 看到的执行路径. 当前 shell 不可见时为空字符串.
        visible (bool): 当前路径是否可见.
    """

    world_path: str
    root_kind: str
    relative_path: str
    host_path: str
    execution_path: str
    visible: bool


@dataclass(slots=True)
class ExecutionView:
    """shell 侧看到的执行视图摘要.

    Attributes:
        workspace_path (str): shell 里 workspace 对应的真实路径.
        skills_path (str): shell 里 skills 对应的真实路径. 当前 shell 不可见时为空字符串.
        self_path (str): shell 里 self 对应的真实路径. 当前 shell 不可见时为空字符串.
        backend (str): 当前使用的 backend.
    """

    workspace_path: str
    skills_path: str
    self_path: str
    backend: str


class WorldView(Protocol):
    """Work World 视图协议."""

    thread_id: str
    actor_kind: str
    agent_id: str
    root_policies: dict[str, WorldRootPolicy]
    workspace_root_host_path: str
    skills_root_host_path: str
    self_root_host_path: str
    visible_skill_names: list[str]
    execution_view: ExecutionView

    def resolve(self, world_path: str) -> ResolvedWorldPath:
        """把 world path 解析成正式路径对象."""

        ...


@dataclass(slots=True)
class WorldInputBundle:
    """构造 Work World 所需的稳定输入.

    Attributes:
        thread_id (str): 当前 thread ID.
        agent_id (str): 当前 agent ID.
        actor_kind (str): 当前 actor 的 world 身份.
        self_scope_id (str): `/self` 对应的宿主机 scope 标识.
        visible_skill_names (list[str] | None): 当前 actor 真正可见的 skill 名.
            传入空列表表示“明确没有可见 skill”, 传入 `None` 表示回退到 policy.
        computer_policy (ComputerPolicyDecision): 当前 run 的 computer 决策结果.
    """

    thread_id: str
    agent_id: str
    actor_kind: str
    self_scope_id: str
    visible_skill_names: list[str] | None = None
    computer_policy: ComputerPolicyDecision = field(default_factory=ComputerPolicyDecision)


@dataclass(slots=True)
class WorkspaceState:
    """当前 run 可见的 computer/workspace 状态摘要.

    Attributes:
        thread_id (str): 当前 thread ID.
        agent_id (str): 当前 agent ID.
        backend_kind (str): 当前 backend 名字.
        workspace_host_path (str): `/workspace` 对应的宿主机路径.
        workspace_visible_root (str): 模型侧看到的 workspace 根路径.
        available_tools (list[str]): 当前 run 实际可见的 computer 工具列表.
        attachment_count (int): 当前 run 已 stage 的附件数量.
        mirrored_skill_names (list[str]): 当前 thread 已物化到宿主机的 skill 列表.
        active_session_ids (list[str]): 当前 thread 活跃 shell session 列表.
    """

    thread_id: str
    agent_id: str
    backend_kind: str
    workspace_host_path: str
    workspace_visible_root: str
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
class WorldPathReadResult:
    """一次 world path 读取后返回给前台工具的结果.

    Attributes:
        world_path (str): 本次读取的 world path.
        text (str): 文本文件时返回的文字内容. 图片文件时留空.
        content (str | list[dict[str, Any]]): 真正发回给模型看的内容.
        mime_type (str): 当前文件识别出来的 MIME 类型. 文本文件时为空.
    """

    world_path: str
    text: str
    content: str | list[dict[str, Any]]
    mime_type: str = ""


@dataclass(slots=True)
class WorldPathWriteResult:
    """一次 world path 文本写入后返回给前台工具的结果.

    Attributes:
        world_path (str): 本次写入的 world path.
        size_bytes (int): 本次写入的 UTF-8 字节数.
    """

    world_path: str
    size_bytes: int


@dataclass(slots=True)
class WorldPathEditResult:
    """一次 world path 文字替换后返回给前台工具的结果.

    Attributes:
        world_path (str): 本次编辑的 world path.
        diff (str): 这次编辑的 diff 文本.
        first_changed_line (int): 第一处改动所在的行号, 从 1 开始.
    """

    world_path: str
    diff: str
    first_changed_line: int


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
    path_aliases: dict[str, str] = field(default_factory=dict)
    process: asyncio.subprocess.Process | None = field(default=None, repr=False)
    stdout_buffer: deque[str] = field(default_factory=deque, repr=False)
    stderr_buffer: deque[str] = field(default_factory=deque, repr=False)
    stdout_size: int = 0
    stderr_size: int = 0


@dataclass(slots=True)
class ComputerRuntimeConfig:
    """computer 子系统的全局运行配置.

    Attributes:
        root_dir (str): computer 宿主机根目录.
        host_skills_catalog_root_path (str): computer 内部使用的宿主机 skills catalog 根路径.
        max_attachment_size_bytes (int): 单个附件最大尺寸.
        max_total_attachment_bytes_per_run (int): 单次 run 附件总大小上限.
        attachment_download_timeout_sec (int): 附件下载超时.
        attachment_download_retries (int): 附件下载重试次数.
        exec_stdout_window_bytes (int): exec stdout 窗口大小.
        exec_stderr_window_bytes (int): exec stderr 窗口大小.
        docker_image (str): docker backend 镜像.
        docker_network_mode (str): docker backend 网络模式.
    """

    root_dir: str
    host_skills_catalog_root_path: str
    max_attachment_size_bytes: int = 64 * 1024 * 1024
    max_total_attachment_bytes_per_run: int = 256 * 1024 * 1024
    attachment_download_timeout_sec: int = 30
    attachment_download_retries: int = 2
    exec_stdout_window_bytes: int = 256 * 1024
    exec_stderr_window_bytes: int = 256 * 1024
    docker_image: str = "python:3.12-slim"
    docker_network_mode: str = "bridge"


class ComputerBackend(Protocol):
    """computer backend 协议."""

    kind: str

    async def ensure_workspace(self, *, host_path: Path, visible_root: str) -> None:
        """确保当前 workspace 的 backend 承载已经准备好.

        Args:
            host_path (Path): 当前 workspace 的宿主机根目录.
            visible_root (str): 当前执行视图里的工作根路径.
        """

        ...

    async def list_entries(self, *, path: Path) -> list[WorkspaceFileEntry]:
        """列出指定路径下的目录项.

        Args:
            path (Path): 当前 backend 允许访问的宿主机路径.

        Returns:
            list[WorkspaceFileEntry]: 当前路径下的目录项.
        """

        ...

    async def read_text(self, *, path: Path) -> str:
        """读取一个 UTF-8 文本文件.

        Args:
            path (Path): 当前 backend 允许访问的宿主机文件路径.

        Returns:
            str: 文件文本内容.
        """

        ...

    async def read_bytes(self, *, path: Path) -> bytes:
        """读取一个文件的原始字节.

        Args:
            path (Path): 当前 backend 允许访问的宿主机文件路径.

        Returns:
            bytes: 文件的原始字节.
        """

        ...

    async def write_text(self, *, path: Path, content: str) -> None:
        """写入一个 UTF-8 文本文件.

        Args:
            path (Path): 当前 backend 允许访问的宿主机文件路径.
            content (str): 要写入的文本.
        """

        ...

    async def exec_once(
        self,
        *,
        host_path: Path,
        command: str,
        policy: ComputerPolicy,
        timeout: int | None = None,
    ) -> CommandExecutionResult:
        """执行一次性 shell 命令.

        Args:
            host_path (Path): 当前命令的工作目录.
            command (str): 要执行的命令.
            policy (ComputerPolicy): 当前有效 computer policy.
            timeout (int | None): 可选超时秒数.

        Returns:
            CommandExecutionResult: 执行结果.
        """

        ...

    async def open_session(self, *, session: CommandSession, policy: ComputerPolicy) -> None:
        """打开一个持久 shell session.

        Args:
            session (CommandSession): 当前 session 对象.
            policy (ComputerPolicy): 当前有效 computer policy.
        """

        ...

    async def write_session(self, session: CommandSession, command: str) -> None:
        """向现有 shell session 写入输入.

        Args:
            session (CommandSession): 目标 session.
            command (str): 要写入的文本.
        """

        ...

    async def close_session(self, session: CommandSession) -> None:
        """关闭一个已存在的 shell session.

        Args:
            session (CommandSession): 目标 session.
        """

        ...

    async def stop_workspace_sandbox(self, *, thread_id: str, host_path: Path) -> None:
        """停止当前 workspace 对应的 sandbox.

        Args:
            thread_id (str): 当前 thread ID.
            host_path (Path): 当前 workspace 根目录.
        """

        ...

    async def get_sandbox_status(self, *, thread_id: str, host_path: Path) -> WorkspaceSandboxStatus:
        """读取当前 workspace 对应的 sandbox 状态.

        Args:
            thread_id (str): 当前 thread ID.
            host_path (Path): 当前 workspace 根目录.

        Returns:
            WorkspaceSandboxStatus: 当前 sandbox 状态摘要.
        """

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
        """把一个附件引用落地成宿主机文件.

        Args:
            attachment (EventAttachment): 当前附件对象.
            event_id (str): 当前事件 ID.
            attachment_index (int): 当前附件在事件里的顺序.
            target_dir (Path): 附件最终写入目录.
            config (ComputerRuntimeConfig): computer 运行配置.
            gateway (Any | None): 当前 gateway, 需要时可用于二次解析.

        Returns:
            AttachmentSnapshot: 当前附件的落地结果.
        """

        ...


def parse_computer_policy(
    raw: object,
    *,
    defaults: ComputerPolicy | None = None,
) -> ComputerPolicy:
    """把原始配置归一化成 `ComputerPolicy`.

    Args:
        raw (object): 原始配置值. 允许为空或 mapping.
        defaults (ComputerPolicy | None): 为空字段使用的兜底 policy.

    Returns:
        ComputerPolicy: 归一化后的 computer policy.

    Raises:
        ValueError: `raw` 既不是空值也不是 mapping 时抛出.
    """

    base = defaults or ComputerPolicy()
    if raw is None or raw == "":
        return ComputerPolicy(
            backend=base.backend,
            allow_exec=base.allow_exec,
            allow_sessions=base.allow_sessions,
            auto_stage_attachments=base.auto_stage_attachments,
            network_mode=base.network_mode,
        )
    if not isinstance(raw, dict):
        raise ValueError("computer policy must be a mapping")
    return ComputerPolicy(
        backend=str(raw.get("backend", base.backend) or base.backend),
        allow_exec=bool(raw.get("allow_exec", base.allow_exec)),
        allow_sessions=bool(raw.get("allow_sessions", base.allow_sessions)),
        auto_stage_attachments=bool(
            raw.get("auto_stage_attachments", base.auto_stage_attachments)
        ),
        network_mode=str(raw.get("network_mode", base.network_mode) or base.network_mode),
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
    "ExecutionView",
    "ResolvedWorldPath",
    "WorldInputBundle",
    "WorldPathEditResult",
    "WorldPathReadResult",
    "WorldPathWriteResult",
    "WorldRootPolicy",
    "WorldView",
    "WorkspaceFileEntry",
    "WorkspaceSandboxStatus",
    "WorkspaceState",
    "parse_computer_policy",
]
