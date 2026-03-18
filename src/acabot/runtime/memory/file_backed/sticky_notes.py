"""runtime.memory.file_backed.sticky_notes 提供 sticky note 文件真源服务.

组件关系:

    RuntimeBootstrap
        |
        v
   StickyNotesSource
        |
        v
 .acabot-runtime/sticky-notes/<scope>/<scope_key>/<note_key>/

这一层负责:
- sticky note 的 scope 和 key 约束
- readonly / editable 双区读写
- 目录遍历和安全校验
"""

from __future__ import annotations

from dataclasses import dataclass
import shutil
from pathlib import Path
from typing import Any


def _path_mtime(path: Path) -> int:
    """读取路径的修改时间戳.

    Args:
        path: 目标路径.

    Returns:
        秒级时间戳, 读取失败时返回 0.
    """

    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


# region sticky notes source
@dataclass(slots=True)
class StickyNotesSource:
    """sticky note 文件真源服务.

    Attributes:
        root_dir (Path): sticky note 根目录.
    """

    root_dir: Path

    PRODUCT_SCOPES: tuple[str, ...] = ("user", "channel")

    def __post_init__(self) -> None:
        """初始化 sticky notes 目录结构."""

        self.root_dir = Path(self.root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        for scope in self.PRODUCT_SCOPES:
            (self.root_dir / scope).mkdir(parents=True, exist_ok=True)

    def list_scopes(self) -> list[dict[str, Any]]:
        """列出当前可浏览的 sticky note scope 列表.

        Returns:
            scope 列表.
        """

        items: list[dict[str, Any]] = []
        for scope in self.PRODUCT_SCOPES:
            scope_dir = self.root_dir / scope
            if not scope_dir.exists():
                continue
            for child in sorted(scope_dir.iterdir(), key=lambda item: item.name):
                if not child.is_dir():
                    continue
                note_count = len([item for item in child.iterdir() if item.is_dir()])
                items.append(
                    {
                        "scope": scope,
                        "scope_key": child.name,
                        "note_count": note_count,
                        "updated_at": _path_mtime(child),
                    }
                )
        return items

    def list_notes(self, *, scope: str, scope_key: str) -> list[dict[str, Any]]:
        """列出 scope 下的 note 列表.

        Args:
            scope: scope 名称.
            scope_key: scope 键.

        Returns:
            note 列表.
        """

        scope_root = self._scope_root(scope=scope, scope_key=scope_key)
        if not scope_root.exists():
            return []
        items: list[dict[str, Any]] = []
        for note_dir in sorted(scope_root.iterdir(), key=lambda item: item.name):
            if not note_dir.is_dir():
                continue
            readonly_file = note_dir / "readonly.md"
            editable_file = note_dir / "editable.md"
            updated_at = max(_path_mtime(readonly_file), _path_mtime(editable_file))
            items.append(
                {
                    "key": note_dir.name,
                    "has_readonly": readonly_file.exists(),
                    "has_editable": editable_file.exists(),
                    "updated_at": updated_at,
                }
            )
        return items

    def read_pair(self, *, scope: str, scope_key: str, key: str) -> dict[str, Any]:
        """读取 note 的 readonly / editable 双区内容.

        Args:
            scope: scope 名称.
            scope_key: scope 键.
            key: note 键.

        Returns:
            双区内容对象.
        """

        note_root = self._note_root(scope=scope, scope_key=scope_key, key=key)
        if not note_root.exists() or not note_root.is_dir():
            raise FileNotFoundError(f"sticky note not found: {scope}/{scope_key}/{key}")
        readonly_file = note_root / "readonly.md"
        editable_file = note_root / "editable.md"
        readonly_content = readonly_file.read_text(encoding="utf-8") if readonly_file.exists() else ""
        editable_content = editable_file.read_text(encoding="utf-8") if editable_file.exists() else ""
        return {
            "scope": scope,
            "scope_key": scope_key,
            "key": key,
            "readonly": {
                "content": readonly_content,
                "updated_at": _path_mtime(readonly_file),
            },
            "editable": {
                "content": editable_content,
                "updated_at": _path_mtime(editable_file),
            },
            "updated_at": max(_path_mtime(readonly_file), _path_mtime(editable_file)),
        }

    def create_note(
        self,
        *,
        scope: str,
        scope_key: str,
        key: str,
        readonly_content: str = "",
        editable_content: str = "",
    ) -> dict[str, Any]:
        """创建一个 sticky note.

        Args:
            scope: scope 名称.
            scope_key: scope 键.
            key: note 键.
            readonly_content: 只读区初始内容.
            editable_content: 可编辑区初始内容.

        Returns:
            创建后的双区对象.
        """

        note_root = self._note_root(scope=scope, scope_key=scope_key, key=key)
        if note_root.exists():
            raise ValueError(f"sticky note already exists: {scope}/{scope_key}/{key}")
        note_root.mkdir(parents=True, exist_ok=False)
        (note_root / "readonly.md").write_text(str(readonly_content), encoding="utf-8")
        (note_root / "editable.md").write_text(str(editable_content), encoding="utf-8")
        return self.read_pair(scope=scope, scope_key=scope_key, key=key)

    def write_readonly(
        self,
        *,
        scope: str,
        scope_key: str,
        key: str,
        content: str,
    ) -> dict[str, Any]:
        """写入 note 的只读区.

        Args:
            scope: scope 名称.
            scope_key: scope 键.
            key: note 键.
            content: 新内容.

        Returns:
            写入后的双区对象.
        """

        note_root = self._ensure_note_root(scope=scope, scope_key=scope_key, key=key)
        (note_root / "readonly.md").write_text(str(content), encoding="utf-8")
        return self.read_pair(scope=scope, scope_key=scope_key, key=key)

    def write_editable(
        self,
        *,
        scope: str,
        scope_key: str,
        key: str,
        content: str,
    ) -> dict[str, Any]:
        """写入 note 的可编辑区.

        Args:
            scope: scope 名称.
            scope_key: scope 键.
            key: note 键.
            content: 新内容.

        Returns:
            写入后的双区对象.
        """

        note_root = self._ensure_note_root(scope=scope, scope_key=scope_key, key=key)
        (note_root / "editable.md").write_text(str(content), encoding="utf-8")
        return self.read_pair(scope=scope, scope_key=scope_key, key=key)

    def delete_note(self, *, scope: str, scope_key: str, key: str) -> bool:
        """删除一个 sticky note.

        Args:
            scope: scope 名称.
            scope_key: scope 键.
            key: note 键.

        Returns:
            删除是否成功.
        """

        note_root = self._note_root(scope=scope, scope_key=scope_key, key=key)
        if not note_root.exists():
            return False
        shutil.rmtree(note_root)
        return True

    # region helpers
    def _scope_root(self, *, scope: str, scope_key: str) -> Path:
        """返回 scope 对应目录.

        Args:
            scope: scope 名称.
            scope_key: scope 键.

        Returns:
            scope 根目录路径.
        """

        normalized_scope = self._normalize_scope(scope)
        normalized_scope_key = self._normalize_segment(scope_key, field_name="scope_key")
        path = (self.root_dir / normalized_scope / normalized_scope_key).resolve()
        try:
            path.relative_to(self.root_dir)
        except ValueError as exc:
            raise ValueError("invalid sticky note scope path") from exc
        return path

    def _note_root(self, *, scope: str, scope_key: str, key: str) -> Path:
        """返回 note 目录路径.

        Args:
            scope: scope 名称.
            scope_key: scope 键.
            key: note 键.

        Returns:
            note 根目录路径.
        """

        normalized_key = self._normalize_segment(key, field_name="key")
        return self._scope_root(scope=scope, scope_key=scope_key) / normalized_key

    def _ensure_note_root(self, *, scope: str, scope_key: str, key: str) -> Path:
        """确保 note 目录存在.

        Args:
            scope: scope 名称.
            scope_key: scope 键.
            key: note 键.

        Returns:
            note 根目录路径.
        """

        note_root = self._note_root(scope=scope, scope_key=scope_key, key=key)
        note_root.mkdir(parents=True, exist_ok=True)
        return note_root

    def _normalize_scope(self, scope: str) -> str:
        """校验并规范化 scope.

        Args:
            scope: 原始 scope.

        Returns:
            规范化 scope.
        """

        text = str(scope or "").strip()
        if text not in self.PRODUCT_SCOPES:
            raise ValueError(f"unsupported sticky note scope: {scope}")
        return text

    @staticmethod
    def _normalize_segment(value: str, *, field_name: str) -> str:
        """校验并规范化路径段.

        Args:
            value: 原始字段值.
            field_name: 字段名.

        Returns:
            规范化后的字段值.
        """

        text = str(value or "").strip()
        if not text:
            raise ValueError(f"sticky note {field_name} cannot be empty")
        if "/" in text or "\\" in text:
            raise ValueError(f"invalid sticky note {field_name}")
        if text in {".", ".."}:
            raise ValueError(f"invalid sticky note {field_name}")
        return text

    # endregion


# endregion
