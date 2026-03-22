"""runtime.computer.backends 定义 host / docker / remote backend.

这个模块负责把 `ComputerRuntime` 已经准备好的宿主机目录和执行请求真正交给 backend 执行.

- `HostComputerBackend` 直接在宿主机上工作
- `DockerSandboxBackend` 把宿主机 workspace 挂进容器后执行
- `RemoteComputerBackend` 目前占位实现

这里不负责 world path 解析, 也不负责 session-config 决策.
那些事情在 `runtime.computer.world` 和 `runtime.computer.runtime` 里处理.
"""

from __future__ import annotations

import asyncio
from collections import deque
import hashlib
from pathlib import Path

from .contracts import (
    CommandExecutionResult,
    CommandSession,
    ComputerBackendNotImplemented,
    ComputerPolicy,
    WorkspaceFileEntry,
    WorkspaceSandboxStatus,
)
from .workspace import relative_visible_path, thread_id_from_path


# region host backend
class HostComputerBackend:
    """本地宿主机 backend.

    Attributes:
        stdout_window_bytes (int): stdout 保留窗口大小.
        stderr_window_bytes (int): stderr 保留窗口大小.
        _session_tasks (dict[str, list[asyncio.Task[None]]]): 每个 session 的后台读取任务.
    """

    kind = "host"

    def __init__(self, *, stdout_window_bytes: int, stderr_window_bytes: int) -> None:
        """初始化宿主机 backend.

        Args:
            stdout_window_bytes (int): stdout 保留窗口大小.
            stderr_window_bytes (int): stderr 保留窗口大小.
        """

        self.stdout_window_bytes = stdout_window_bytes
        self.stderr_window_bytes = stderr_window_bytes
        self._session_tasks: dict[str, list[asyncio.Task[None]]] = {}

    async def ensure_workspace(self, *, host_path: Path, visible_root: str) -> None:
        """确保 backend 需要的 workspace 根目录存在.

        Args:
            host_path (Path): 当前 workspace 的宿主机根目录.
            visible_root (str): 当前 shell 看到的工作根路径.
        """

        _ = visible_root
        host_path.mkdir(parents=True, exist_ok=True)

    async def list_entries(self, *, path: Path) -> list[WorkspaceFileEntry]:
        """列出指定路径下的文件和目录.

        系统需要一个不依赖 shell、可结构化返回结果、可跨 host/docker/remote 复用的 ls

        Args:
            path (Path): 上层已经从 world path 解析出来的真实宿主机目标路径

        Returns:
            list[WorkspaceFileEntry]: 当前路径下的目录项.
        """

        path = path.resolve()
        if not path.exists():
            return []
        visible_root = path
        if path.is_file():
            stat = path.stat()
            return [
                WorkspaceFileEntry(
                    path=relative_visible_path(path, visible_root),
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
                    path=relative_visible_path(item, visible_root),
                    kind="dir" if item.is_dir() else "file",
                    size_bytes=0 if item.is_dir() else stat.st_size,
                    modified_at=int(stat.st_mtime),
                )
            )
        return items

    async def read_text(self, *, path: Path) -> str:
        """读取一个 UTF-8 文本文件.

        Args:
            path (Path): 当前 backend 允许访问的宿主机文件路径.

        Returns:
            str: 文件内容.
        """

        return path.resolve().read_text(encoding="utf-8")

    async def read_bytes(self, *, path: Path) -> bytes:
        """读取一个文件的原始字节.

        Args:
            path (Path): 当前 backend 允许访问的宿主机文件路径.

        Returns:
            bytes: 文件原始字节.
        """

        return path.resolve().read_bytes()

    async def write_text(self, *, path: Path, content: str) -> None:
        """写入一个 UTF-8 文本文件.

        Args:
            path (Path): 当前 backend 允许访问的宿主机文件路径.
            content (str): 要写入的文本.
        """

        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


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
            command (str): 要执行的 shell 命令.
            policy (ComputerPolicy): 当前有效 computer policy.
            timeout (int | None): 可选超时秒数.

        Returns:
            CommandExecutionResult: 执行结果.
        """

        if not policy.allow_exec:
            raise PermissionError("exec is disabled by computer policy")
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(host_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            if timeout is None:
                stdout, stderr = await process.communicate()
            else:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            message = f"Command timed out after {timeout} seconds"
            stderr_text = stderr.decode("utf-8", errors="replace")
            merged_stderr = stderr_text if not stderr_text else f"{stderr_text}\n{message}"
            return CommandExecutionResult(
                ok=False,
                exit_code=None,
                stdout_excerpt=excerpt_bytes(stdout, self.stdout_window_bytes),
                stderr_excerpt=excerpt_bytes(merged_stderr.encode("utf-8"), self.stderr_window_bytes),
                stdout_truncated=len(stdout) > self.stdout_window_bytes,
                stderr_truncated=len(merged_stderr.encode("utf-8")) > self.stderr_window_bytes,
                metadata={"timed_out": True, "timeout": timeout},
            )
        return CommandExecutionResult(
            ok=process.returncode == 0,
            exit_code=process.returncode,
            stdout_excerpt=excerpt_bytes(stdout, self.stdout_window_bytes),
            stderr_excerpt=excerpt_bytes(stderr, self.stderr_window_bytes),
            stdout_truncated=len(stdout) > self.stdout_window_bytes,
            stderr_truncated=len(stderr) > self.stderr_window_bytes,
        )

    async def open_session(self, *, session: CommandSession, policy: ComputerPolicy) -> None:
        """打开一个持久 shell session.

        Args:
            session (CommandSession): 当前 session 对象.
            policy (ComputerPolicy): 当前有效 computer policy.
        """

        if not policy.allow_sessions:
            raise PermissionError("shell sessions are disabled by computer policy")
        process = await asyncio.create_subprocess_exec(
            "/bin/sh",
            cwd=session.cwd_host_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.attach_process(session, process)

    def attach_process(
        self,
        session: CommandSession,
        process: asyncio.subprocess.Process,
    ) -> None:
        """把已经启动好的进程挂到 session 上并开始后台读取输出.

        Args:
            session (CommandSession): 当前 session 对象.
            process (asyncio.subprocess.Process): 已经启动好的子进程.
        """

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
        """向现有 session 写入输入.

        Args:
            session (CommandSession): 目标 session.
            command (str): 要写入的文本.
        """

        if session.process is None or session.process.stdin is None:
            raise RuntimeError("session is not active")
        session.process.stdin.write(command.encode("utf-8"))
        await session.process.stdin.drain()

    async def close_session(self, session: CommandSession) -> None:
        """关闭一个已存在的 shell session.

        Args:
            session (CommandSession): 目标 session.
        """

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
        """停止当前 workspace 对应的 sandbox.

        宿主机 backend 没有独立 sandbox, 所以这里只是空操作.

        Args:
            thread_id (str): 当前 thread ID.
            host_path (Path): 当前 workspace 根目录.
        """

        _ = thread_id, host_path
        return None

    async def get_sandbox_status(self, *, thread_id: str, host_path: Path) -> WorkspaceSandboxStatus:
        """返回当前 workspace 的 sandbox 状态.

        Args:
            thread_id (str): 当前 thread ID.
            host_path (Path): 当前 workspace 根目录.

        Returns:
            WorkspaceSandboxStatus: 当前 sandbox 状态摘要.
        """

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
        """持续读取进程输出, 并按窗口大小截断缓存.

        Args:
            stream (asyncio.StreamReader | None): 待读取输出流.
            buffer (deque[str]): 文本缓冲区.
            size_attr (str): `CommandSession` 上记录字节数的字段名.
            session (CommandSession): 当前 session 对象.
            window_bytes (int): 最多保留多少字节.
        """

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


# endregion


# region docker backend
class DockerSandboxBackend:
    """Docker-backed sandbox backend.

    Attributes:
        image (str): 当前使用的 docker 镜像.
        stdout_window_bytes (int): stdout 保留窗口大小.
        stderr_window_bytes (int): stderr 保留窗口大小.
        network_mode (str): docker 网络模式.
        _containers (dict[str, str]): `thread_id -> container_id` 映射.
        _host_delegate (HostComputerBackend): 复用的宿主机文件和 session helper.
    """

    kind = "docker"

    def __init__(self, *, image: str, stdout_window_bytes: int, stderr_window_bytes: int, network_mode: str) -> None:
        """初始化 docker backend.

        Args:
            image (str): 当前使用的 docker 镜像.
            stdout_window_bytes (int): stdout 保留窗口大小.
            stderr_window_bytes (int): stderr 保留窗口大小.
            network_mode (str): docker 网络模式.
        """

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
        """确保当前 workspace 根目录存在.

        Args:
            host_path (Path): 当前 workspace 根目录.
            visible_root (str): 当前执行视图里的工作根路径.
        """

        _ = visible_root
        host_path.mkdir(parents=True, exist_ok=True)

    async def list_entries(self, *, path: Path) -> list[WorkspaceFileEntry]:
        """列出目录项.

        Args:
            path (Path): 当前 workspace 内的宿主机路径.

        Returns:
            list[WorkspaceFileEntry]: 当前路径下的目录项.
        """

        return await self._host_delegate.list_entries(path=path)

    async def read_text(self, *, path: Path) -> str:
        """读取一个文本文件.

        Args:
            path (Path): 当前 workspace 内的宿主机文件路径.

        Returns:
            str: 文件内容.
        """

        return await self._host_delegate.read_text(path=path)

    async def read_bytes(self, *, path: Path) -> bytes:
        """读取一个文件的原始字节.

        Args:
            path (Path): 当前 workspace 内的宿主机文件路径.

        Returns:
            bytes: 文件原始字节.
        """

        return await self._host_delegate.read_bytes(path=path)

    async def write_text(self, *, path: Path, content: str) -> None:
        """写入一个文本文件.

        Args:
            path (Path): 当前 workspace 内的宿主机文件路径.
            content (str): 要写入的文本.
        """

        return await self._host_delegate.write_text(path=path, content=content)

    async def exec_once(
        self,
        *,
        host_path: Path,
        command: str,
        policy: ComputerPolicy,
        timeout: int | None = None,
    ) -> CommandExecutionResult:
        """在 docker 容器里执行一次性命令.

        Args:
            host_path (Path): 当前 workspace 宿主机目录.
            command (str): 要执行的命令.
            policy (ComputerPolicy): 当前有效 computer policy.
            timeout (int | None): 可选超时秒数.

        Returns:
            CommandExecutionResult: 执行结果.
        """

        if not policy.allow_exec:
            raise PermissionError("exec is disabled by computer policy")
        container = await self._ensure_container(thread_id=thread_id_from_path(host_path), host_path=host_path)
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
        try:
            if timeout is None:
                stdout, stderr = await process.communicate()
            else:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            message = f"Command timed out after {timeout} seconds"
            stderr_text = stderr.decode("utf-8", errors="replace")
            merged_stderr = stderr_text if not stderr_text else f"{stderr_text}\n{message}"
            return CommandExecutionResult(
                ok=False,
                exit_code=None,
                stdout_excerpt=excerpt_bytes(stdout, self.stdout_window_bytes),
                stderr_excerpt=excerpt_bytes(merged_stderr.encode("utf-8"), self.stderr_window_bytes),
                stdout_truncated=len(stdout) > self.stdout_window_bytes,
                stderr_truncated=len(merged_stderr.encode("utf-8")) > self.stderr_window_bytes,
                metadata={"container_id": container, "timed_out": True, "timeout": timeout},
            )
        return CommandExecutionResult(
            ok=process.returncode == 0,
            exit_code=process.returncode,
            stdout_excerpt=excerpt_bytes(stdout, self.stdout_window_bytes),
            stderr_excerpt=excerpt_bytes(stderr, self.stderr_window_bytes),
            stdout_truncated=len(stdout) > self.stdout_window_bytes,
            stderr_truncated=len(stderr) > self.stderr_window_bytes,
            metadata={"container_id": container},
        )

    async def open_session(self, *, session: CommandSession, policy: ComputerPolicy) -> None:
        """在 docker 容器里打开一个持久 shell session.

        Args:
            session (CommandSession): 当前 session 对象.
            policy (ComputerPolicy): 当前有效 computer policy.
        """

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
        self._host_delegate.attach_process(session, process)

    async def write_session(self, session: CommandSession, command: str) -> None:
        """向 docker session 写入输入.

        Args:
            session (CommandSession): 目标 session.
            command (str): 要写入的文本.
        """

        return await self._host_delegate.write_session(session, command)

    async def close_session(self, session: CommandSession) -> None:
        """关闭 docker session.

        Args:
            session (CommandSession): 目标 session.
        """

        return await self._host_delegate.close_session(session)

    async def stop_workspace_sandbox(self, *, thread_id: str, host_path: Path) -> None:
        """停止当前 thread 对应的 docker sandbox.

        Args:
            thread_id (str): 当前 thread ID.
            host_path (Path): 当前 workspace 根目录.
        """

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
        """返回当前 docker sandbox 状态.

        Args:
            thread_id (str): 当前 thread ID.
            host_path (Path): 当前 workspace 根目录.

        Returns:
            WorkspaceSandboxStatus: 当前 sandbox 状态摘要.
        """

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
        """确保指定 thread 对应的 docker 容器存在.

        Args:
            thread_id (str): 当前 thread ID.
            host_path (Path): 当前 workspace 根目录.

        Returns:
            str: 当前 thread 对应的容器名.
        """

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


# endregion


# region remote backend
class RemoteComputerBackend:
    """remote sandbox 占位 backend."""

    kind = "remote"

    async def ensure_workspace(self, *, host_path: Path, visible_root: str) -> None:
        """提示 remote backend 还未实现.

        Args:
            host_path (Path): 当前 workspace 根目录.
            visible_root (str): 当前执行视图里的工作根路径.
        """

        _ = host_path, visible_root
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def list_entries(self, *, path: Path) -> list[WorkspaceFileEntry]:
        """提示 remote backend 还未实现.

        Args:
            path (Path): 当前 workspace 内的宿主机路径.

        Returns:
            list[WorkspaceFileEntry]: 当前不会返回结果, 会直接抛异常.
        """

        _ = path
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def read_text(self, *, path: Path) -> str:
        """提示 remote backend 还未实现.

        Args:
            path (Path): 当前 workspace 内的宿主机文件路径.

        Returns:
            str: 当前不会返回结果, 会直接抛异常.
        """

        _ = path
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def read_bytes(self, *, path: Path) -> bytes:
        """提示 remote backend 还未实现.

        Args:
            path (Path): 当前 workspace 内的宿主机文件路径.

        Returns:
            bytes: 当前不会返回结果, 会直接抛异常.
        """

        _ = path
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def write_text(self, *, path: Path, content: str) -> None:
        """提示 remote backend 还未实现.

        Args:
            path (Path): 当前 workspace 内的宿主机文件路径.
            content (str): 要写入的文本.
        """

        _ = path, content
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def exec_once(
        self,
        *,
        host_path: Path,
        command: str,
        policy: ComputerPolicy,
        timeout: int | None = None,
    ) -> CommandExecutionResult:
        """提示 remote backend 还未实现.

        Args:
            host_path (Path): 当前 workspace 根目录.
            command (str): 要执行的命令.
            policy (ComputerPolicy): 当前有效 computer policy.
            timeout (int | None): 可选超时秒数.

        Returns:
            CommandExecutionResult: 当前不会返回结果, 会直接抛异常.
        """

        _ = host_path, command, policy, timeout
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def open_session(self, *, session: CommandSession, policy: ComputerPolicy) -> None:
        """提示 remote backend 还未实现.

        Args:
            session (CommandSession): 当前 session 对象.
            policy (ComputerPolicy): 当前有效 computer policy.
        """

        _ = session, policy
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def write_session(self, session: CommandSession, command: str) -> None:
        """提示 remote backend 还未实现.

        Args:
            session (CommandSession): 目标 session.
            command (str): 要写入的文本.
        """

        _ = session, command
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def close_session(self, session: CommandSession) -> None:
        """提示 remote backend 还未实现.

        Args:
            session (CommandSession): 目标 session.
        """

        _ = session
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def stop_workspace_sandbox(self, *, thread_id: str, host_path: Path) -> None:
        """提示 remote backend 还未实现.

        Args:
            thread_id (str): 当前 thread ID.
            host_path (Path): 当前 workspace 根目录.
        """

        _ = thread_id, host_path
        raise ComputerBackendNotImplemented("remote computer backend is not implemented")

    async def get_sandbox_status(self, *, thread_id: str, host_path: Path) -> WorkspaceSandboxStatus:
        """返回 remote backend 的占位状态.

        Args:
            thread_id (str): 当前 thread ID.
            host_path (Path): 当前 workspace 根目录.

        Returns:
            WorkspaceSandboxStatus: 占位状态对象.
        """

        _ = host_path
        return WorkspaceSandboxStatus(
            thread_id=thread_id,
            backend_kind=self.kind,
            active=False,
            message="remote computer backend is not implemented",
        )


# endregion


# region helper
def excerpt_bytes(raw: bytes, limit: int) -> str:
    """把大块字节内容截断成可展示文本.

    Args:
        raw (bytes): 原始字节内容.
        limit (int): 最多保留多少字节.

    Returns:
        str: 适合展示的截断文本.
    """

    if len(raw) <= limit:
        return raw.decode("utf-8", errors="replace")
    head = raw[: limit // 2].decode("utf-8", errors="replace")
    tail = raw[-(limit // 2) :].decode("utf-8", errors="replace")
    return f"{head}\n...[truncated]...\n{tail}"


# endregion


__all__ = [
    "DockerSandboxBackend",
    "HostComputerBackend",
    "RemoteComputerBackend",
]


# endregion


# region helper
def excerpt_bytes(raw: bytes, limit: int) -> str:
    """把大块字节内容截断成可展示文本.

    Args:
        raw (bytes): 原始字节内容.
        limit (int): 最多保留多少字节.

    Returns:
        str: 适合展示的截断文本.
    """

    if len(raw) <= limit:
        return raw.decode("utf-8", errors="replace")
    head = raw[: limit // 2].decode("utf-8", errors="replace")
    tail = raw[-(limit // 2) :].decode("utf-8", errors="replace")
    return f"{head}\n...[truncated]...\n{tail}"


# endregion


__all__ = [
    "DockerSandboxBackend",
    "HostComputerBackend",
    "RemoteComputerBackend",
]
