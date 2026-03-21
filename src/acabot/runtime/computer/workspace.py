"""runtime.computer.workspace 管理 Work World 使用的宿主机目录布局.

这个模块专门回答一件事:

- `/workspace`、`/skills`、`/self` 在宿主机上分别落到哪里

它不负责决定当前 actor 能不能看见这些 root, 也不负责做 shell 执行.
那些事情由 `runtime.computer.world` 和 `runtime.computer.runtime` 负责.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
from urllib.parse import quote, unquote

from .contracts import ComputerRuntimeConfig


# region manager
class WorkspaceManager:
    """Work World 宿主机目录布局管理器.

    Attributes:
        config (ComputerRuntimeConfig): computer 子系统配置.
        root_dir (Path): computer 宿主机根目录.
        skill_catalog_dir (Path): skill catalog 真源目录.
    """

    def __init__(self, config: ComputerRuntimeConfig) -> None:
        """初始化目录管理器.

        Args:
            config (ComputerRuntimeConfig): computer 子系统配置.
        """

        self.config = config
        self.root_dir = Path(config.root_dir).expanduser()
        self.skill_catalog_dir = Path(config.skill_catalog_dir).expanduser()

    def visible_root(self) -> str:
        """返回旧接口仍在使用的默认可见根.

        Returns:
            str: 当前默认可见根. 现阶段仍然返回 `/workspace`.
        """

        return "/workspace"

    def workspace_dir_for_thread(self, thread_id: str) -> Path:
        """返回指定 thread 的宿主机 workspace 根目录.

        Args:
            thread_id (str): 目标 thread ID.

        Returns:
            Path: 当前 thread 的 workspace 根目录.
        """

        safe = safe_thread_id(thread_id)
        return self.root_dir / "threads" / safe / "workspace"

    def attachments_dir_for_thread(self, thread_id: str) -> Path:
        """返回指定 thread 的附件目录.

        Args:
            thread_id (str): 目标 thread ID.

        Returns:
            Path: 当前 thread 的附件目录.
        """

        return self.workspace_dir_for_thread(thread_id) / "attachments"

    def scratch_dir_for_thread(self, thread_id: str) -> Path:
        """返回指定 thread 的 scratch 目录.

        Args:
            thread_id (str): 目标 thread ID.

        Returns:
            Path: 当前 thread 的 scratch 目录.
        """

        return self.workspace_dir_for_thread(thread_id) / "scratch"

    def skills_dir_for_thread(self, thread_id: str) -> Path:
        """返回指定 thread 的 skills 视图目录.

        Args:
            thread_id (str): 目标 thread ID.

        Returns:
            Path: 当前 thread 的 skills 视图目录.
        """

        return self.workspace_dir_for_thread(thread_id) / "skills"

    def skills_view_dir_for_key(self, thread_id: str, view_key: str) -> Path:
        """返回指定 thread 下某个 skills 视图的目录.

        Args:
            thread_id (str): 目标 thread ID.
            view_key (str): 当前 skills 视图的稳定键.

        Returns:
            Path: 当前 skills 视图目录.
        """

        safe_thread = safe_thread_id(thread_id)
        safe_view = safe_thread_id(view_key)
        return self.root_dir / "threads" / safe_thread / "skill_views" / safe_view

    def self_dir_for_scope(self, self_scope_id: str) -> Path:
        """返回指定 self scope 的宿主机目录.

        Args:
            self_scope_id (str): `/self` 对应的持久 scope 标识.

        Returns:
            Path: 当前 scope 的 `/self` 宿主机目录.
        """

        safe = safe_thread_id(self_scope_id)
        return self.root_dir / "self" / safe

    def ensure_workspace_layout(self, thread_id: str) -> Path:
        """确保指定 thread 的 workspace 基础目录存在.

        Args:
            thread_id (str): 目标 thread ID.

        Returns:
            Path: 当前 thread 的 workspace 根目录.
        """

        workspace = self.workspace_dir_for_thread(thread_id)
        workspace.mkdir(parents=True, exist_ok=True)
        self.attachments_dir_for_thread(thread_id).mkdir(parents=True, exist_ok=True)
        self.scratch_dir_for_thread(thread_id).mkdir(parents=True, exist_ok=True)
        self.skills_dir_for_thread(thread_id).mkdir(parents=True, exist_ok=True)
        (workspace / ".thread_id").write_text(thread_id, encoding="utf-8")
        return workspace

    def ensure_skills_layout(self, thread_id: str) -> Path:
        """确保指定 thread 的共享 skills 目录存在.

        Args:
            thread_id (str): 目标 thread ID.

        Returns:
            Path: 当前 thread 的共享 skills 目录.
        """

        skills_dir = self.skills_dir_for_thread(thread_id)
        skills_dir.mkdir(parents=True, exist_ok=True)
        return skills_dir

    def ensure_skills_view(self, thread_id: str, view_key: str, visible_skill_names: list[str]) -> Path:
        """确保某个 actor 的 skills 视图目录存在并且只暴露指定 skills.

        Args:
            thread_id (str): 目标 thread ID.
            view_key (str): 当前 skills 视图的稳定键.
            visible_skill_names (list[str]): 当前 actor 真正可见的 skill 名列表.

        Returns:
            Path: 当前 actor 的 skills 视图目录.
        """

        source_root = self.ensure_skills_layout(thread_id)
        view_root = self.skills_view_dir_for_key(thread_id, view_key)
        view_root.mkdir(parents=True, exist_ok=True)
        allowed = set(visible_skill_names)

        for child in list(view_root.iterdir()):
            if child.name in allowed:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()

        for skill_name in sorted(allowed):
            source = source_root / skill_name
            target = view_root / skill_name
            if target.exists() or target.is_symlink():
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            if not source.exists():
                continue
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        return view_root

    def ensure_self_layout(self, self_scope_id: str) -> Path:
        """确保指定 self scope 的目录存在.

        Args:
            self_scope_id (str): `/self` 对应的持久 scope 标识.

        Returns:
            Path: 当前 scope 的 `/self` 宿主机目录.
        """

        self_dir = self.self_dir_for_scope(self_scope_id)
        self_dir.mkdir(parents=True, exist_ok=True)
        return self_dir

    def resolve_relative_path(self, thread_id: str, relative_path: str) -> Path:
        """在当前 thread workspace 内解析相对路径.

        Args:
            thread_id (str): 目标 thread ID.
            relative_path (str): workspace 内相对路径.

        Returns:
            Path: 解析后的宿主机路径.

        Raises:
            ValueError: 路径越界时抛出.
        """

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
        """列出当前存在的全部 thread workspaces.

        Returns:
            list[Path]: 所有存在的 workspace 根目录.
        """

        root = self.root_dir / "threads"
        if not root.exists():
            return []
        return sorted(path / "workspace" for path in root.iterdir() if (path / "workspace").exists())

    @staticmethod
    def thread_id_from_workspace_path(path: Path) -> str:
        """从 workspace 路径反推 thread_id.

        Args:
            path (Path): workspace 路径.

        Returns:
            str: 解析出的 thread_id.
        """

        marker = path / ".thread_id"
        if marker.exists():
            return marker.read_text(encoding="utf-8").strip()
        return thread_id_from_path(path)


# endregion


# region helpers

def safe_thread_id(thread_id: str) -> str:
    """把任意 thread / scope 标识转成无碰撞的安全目录名.

    这里不再用“非法字符全部替换成下划线”的做法, 因为那样会让不同 ID
    落到同一个目录名上. 现在直接做 URL 编码, 保留稳定性和可区分性.

    Args:
        thread_id (str): 原始 thread 或 scope 标识.

    Returns:
        str: 安全目录名.
    """

    raw = str(thread_id or "").strip()
    if not raw:
        return "thread"
    return quote(raw, safe="._-")



def sanitize_filename(name: str) -> str:
    """把任意文件名转成安全文件名.

    Args:
        name (str): 原始文件名.

    Returns:
        str: 安全文件名.
    """

    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("_") or "attachment"



def is_subpath(path: Path, root: Path) -> bool:
    """判断某个路径是否位于指定根目录之下.

    Args:
        path (Path): 待判断路径.
        root (Path): 根目录.

    Returns:
        bool: 位于根目录内返回 `True`.
    """

    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False



def relative_visible_path(path: Path, workspace_root: Path) -> str:
    """把宿主机路径转成当前 workspace 内的可见路径.

    Args:
        path (Path): 宿主机路径.
        workspace_root (Path): 当前 workspace 根目录.

    Returns:
        str: 以 `/` 开头的可见路径.
    """

    relative = str(path.resolve().relative_to(workspace_root.resolve()))
    if relative == ".":
        return "/"
    return "/" + relative



def thread_id_from_path(path: Path) -> str:
    """从目录结构反推 thread_id.

    Args:
        path (Path): 线程相关目录路径.

    Returns:
        str: 解析出的 thread_id.
    """

    if path.name == "workspace":
        return unquote(path.parent.name)
    return unquote(path.name)


# endregion


__all__ = [
    "WorkspaceManager",
    "is_subpath",
    "relative_visible_path",
    "safe_thread_id",
    "sanitize_filename",
    "thread_id_from_path",
]
