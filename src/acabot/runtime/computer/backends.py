"""runtime.computer.backends 定义 host/docker/remote backend."""

from __future__ import annotations

import asyncio
from collections import deque
import hashlib
from pathlib import Path
import re
from typing import Any

from .contracts import (
    CommandExecutionResult,
    CommandSession,
    ComputerBackendNotImplemented,
    ComputerPolicy,
    WorkspaceFileEntry,
    WorkspaceSandboxStatus,
)
from .workspace import is_subpath, relative_visible_path, thread_id_from_path


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
        if not is_subpath(path, host_path.resolve()):
            raise ValueError("path escapes workspace")
        if not path.exists():
            return []
        if path.is_file():
            stat = path.stat()
            return [
                WorkspaceFileEntry(
                    path=relative_visible_path(path, host_path),
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
                    path=relative_visible_path(item, host_path),
                    kind="dir" if item.is_dir() else "file",
                    size_bytes=0 if item.is_dir() else stat.st_size,
                    modified_at=int(stat.st_mtime),
                )
            )
        return items

    async def read_text(self, *, host_path: Path, relative_path: str) -> str:
        path = (host_path / relative_path.lstrip("/")).resolve()
        if not is_subpath(path, host_path.resolve()):
            raise ValueError("path escapes workspace")
        return path.read_text(encoding="utf-8")

    async def write_text(self, *, host_path: Path, relative_path: str, content: str) -> None:
        path = (host_path / relative_path.lstrip("/")).resolve()
        if not is_subpath(path, host_path.resolve()):
            raise ValueError("path escapes workspace")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    async def grep_text(self, *, host_path: Path, relative_path: str, pattern: str) -> list[dict[str, Any]]:
        root = (host_path / relative_path.lstrip("/")).resolve()
        if not is_subpath(root, host_path.resolve()):
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
                            "path": relative_visible_path(file_path, host_path),
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
            stdout_excerpt=excerpt_bytes(stdout, self.stdout_window_bytes),
            stderr_excerpt=excerpt_bytes(stderr, self.stderr_window_bytes),
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
        self.attach_process(session, process)

    def attach_process(
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


class DockerSandboxBackend:
    """Docker-backed sandbox backend."""

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
        stdout, stderr = await process.communicate()
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


def excerpt_bytes(raw: bytes, limit: int) -> str:
    if len(raw) <= limit:
        return raw.decode("utf-8", errors="replace")
    head = raw[: limit // 2].decode("utf-8", errors="replace")
    tail = raw[-(limit // 2) :].decode("utf-8", errors="replace")
    return f"{head}\n...[truncated]...\n{tail}"


__all__ = [
    "DockerSandboxBackend",
    "HostComputerBackend",
    "RemoteComputerBackend",
]
