"""runtime.soul.source 提供 `/self` 文件真源服务.

组件关系:

    RuntimeBootstrap
        |
        v
      SoulSource
        |
        v
    runtime_data/soul/*

这一层负责 `/self` 文件的受控读写:
- 初始化 `today.md + daily/`
- 文件名与路径安全校验
- 提供 today append helper
- 为 runtime / MemoryBroker 渲染最近 self 上下文
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _now_timestamp(path: Path) -> int:
    """读取文件修改时间戳."""

    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


@dataclass(slots=True)
class SoulSource:
    """`/self` 文件真源服务."""

    root_dir: Path

    TODAY_FILE = "today.md"
    DAILY_DIR = "daily"

    def __post_init__(self) -> None:
        """初始化 `/self` 目录结构."""

        self.root_dir = Path(self.root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_self_layout()

    def list_files(self) -> list[dict[str, Any]]:
        """列出 `/self` 下可见的文件.

        `today.md` 永远排第一位, 然后是根目录其他文件, 最后是最近的 daily 文件.
        """

        items = [
            self._to_item(
                path=self.root_dir / self.TODAY_FILE,
                name=self.TODAY_FILE,
                is_core=True,
            )
        ]
        for path in sorted(self.root_dir.iterdir(), key=lambda item: item.name):
            if not path.is_file():
                continue
            if path.name == self.TODAY_FILE:
                continue
            items.append(self._to_item(path=path, name=path.name, is_core=False))
        for path in self._recent_daily_files():
            items.append(
                self._to_item(
                    path=path,
                    name=f"{self.DAILY_DIR}/{path.name}",
                    is_core=False,
                )
            )
        return items

    def read_file(self, name: str) -> dict[str, Any]:
        """读取一个 `/self` 文件."""

        path = self._resolve_name(name)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"self file not found: {name}")
        content = path.read_text(encoding="utf-8")
        relative_name = self._relative_name(path)
        return {
            "name": relative_name,
            "is_core": relative_name == self.TODAY_FILE,
            "content": content,
            "size": len(content.encode("utf-8")),
            "updated_at": _now_timestamp(path),
        }

    def write_file(self, name: str, content: str) -> dict[str, Any]:
        """写入一个 `/self` 文件."""

        path = self._resolve_name(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")
        return self.read_file(self._relative_name(path))

    def create_file(self, name: str, content: str = "") -> dict[str, Any]:
        """创建一个新的 `/self` 文件."""

        path = self._resolve_name(name)
        if path.exists():
            raise ValueError(f"self file already exists: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")
        return self.read_file(self._relative_name(path))

    def append_today_entry(self, line: str) -> dict[str, Any]:
        """向 `today.md` 追加一条极简连续性记录."""

        normalized = str(line or "").strip()
        if not normalized:
            raise ValueError("today entry cannot be empty")
        path = self.root_dir / self.TODAY_FILE
        existing = path.read_text(encoding="utf-8").rstrip()
        content = f"{existing}\n{normalized}\n" if existing else f"{normalized}\n"
        path.write_text(content, encoding="utf-8")
        return self.read_file(self.TODAY_FILE)

    def build_recent_context_text(self, *, max_daily_files: int = 2) -> str:
        """渲染最近 `/self` 上下文, 给 runtime 注入或 MemoryBroker 检索使用."""

        sections = [self._render_relative_file(self.TODAY_FILE)]
        for path in self._recent_daily_files(limit=max_daily_files):
            sections.append(self._render_relative_file(f"{self.DAILY_DIR}/{path.name}"))
        return "\n\n".join(section for section in sections if section).strip()

    def _ensure_self_layout(self) -> None:
        """确保 `/self` 的最小目录结构存在."""

        today_path = self.root_dir / self.TODAY_FILE
        if not today_path.exists():
            today_path.write_text("", encoding="utf-8")
        (self.root_dir / self.DAILY_DIR).mkdir(parents=True, exist_ok=True)

    def _recent_daily_files(self, *, limit: int | None = None) -> list[Path]:
        """返回最近的 daily 文件列表."""

        daily_dir = self.root_dir / self.DAILY_DIR
        files = sorted(
            [path for path in daily_dir.glob("*.md") if path.is_file()],
            key=lambda item: item.name,
            reverse=True,
        )
        if limit is None:
            return files
        return files[: max(limit, 0)]

    def _render_relative_file(self, name: str) -> str:
        """把指定相对文件渲染成上下文片段."""

        try:
            payload = self.read_file(name)
        except FileNotFoundError:
            return ""
        content = str(payload.get("content", "") or "").strip()
        if not content:
            return ""
        return f"[{name}]\n{content}"

    def _resolve_name(self, name: str) -> Path:
        """把相对文件名解析成受控路径."""

        normalized = str(name or "").strip().replace("\\", "/")
        if not normalized:
            raise ValueError("self file name cannot be empty")
        parts = [part for part in normalized.split("/") if part]
        if not parts:
            raise ValueError("self file name cannot be empty")
        for part in parts:
            if part in {".", ".."} or part.startswith("."):
                raise ValueError("invalid self file path")
        path = self.root_dir.joinpath(*parts).resolve()
        try:
            path.relative_to(self.root_dir)
        except ValueError as exc:
            raise ValueError("invalid self file path") from exc
        return path

    def _relative_name(self, path: Path) -> str:
        """返回文件相对 `/self` 根目录的名字."""

        return path.resolve().relative_to(self.root_dir).as_posix()

    @staticmethod
    def _to_item(*, path: Path, name: str, is_core: bool) -> dict[str, Any]:
        """构造文件列表项."""

        size = 0
        updated_at = 0
        if path.exists() and path.is_file():
            try:
                size = len(path.read_bytes())
            except OSError:
                size = 0
            updated_at = _now_timestamp(path)
        return {
            "name": name,
            "is_core": is_core,
            "exists": path.exists(),
            "size": size,
            "updated_at": updated_at,
        }
