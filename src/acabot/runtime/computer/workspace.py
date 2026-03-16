"""runtime.computer.workspace 管理 workspace 布局和路径约束."""

from __future__ import annotations

from pathlib import Path
import re

from .contracts import ComputerRuntimeConfig


class WorkspaceManager:
    """workspace 路径和文件系统布局管理器."""

    def __init__(self, config: ComputerRuntimeConfig) -> None:
        self.config = config
        self.root_dir = Path(config.root_dir).expanduser()
        self.skill_catalog_dir = Path(config.skill_catalog_dir).expanduser()

    def visible_root(self) -> str:
        return "/workspace"

    def workspace_dir_for_thread(self, thread_id: str) -> Path:
        safe = safe_thread_id(thread_id)
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
        if not is_subpath(requested, base):
            raise ValueError("path escapes workspace")
        if requested.is_symlink():
            real = requested.resolve()
            if not is_subpath(real, base):
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
        return thread_id_from_path(path)


def safe_thread_id(thread_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", thread_id).strip("_") or "thread"


def sanitize_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("_") or "attachment"


def is_subpath(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def relative_visible_path(path: Path, workspace_root: Path) -> str:
    return "/" + str(path.resolve().relative_to(workspace_root.resolve()))


def thread_id_from_path(path: Path) -> str:
    if path.name == "workspace":
        return path.parent.name
    return path.name


__all__ = [
    "WorkspaceManager",
    "is_subpath",
    "relative_visible_path",
    "safe_thread_id",
    "sanitize_filename",
    "thread_id_from_path",
]
