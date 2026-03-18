"""runtime.soul.source 提供 soul 文件真源服务.

组件关系:

    RuntimeBootstrap
        |
        v
      SoulSource
        |
        v
    .acabot-runtime/soul/*

这一层负责 soul 文件的受控读写:
- 固定主文件管理
- 文件名与路径安全校验
- `state.yaml` 基础格式校验
- 给 prompt 装配提供稳定文本
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import textwrap
from typing import Any

import yaml


def _now_timestamp(path: Path) -> int:
    """读取文件修改时间戳.

    Args:
        path: 目标路径.

    Returns:
        秒级时间戳, 读取失败时返回 0.
    """

    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


# region soul source
@dataclass(slots=True)
class SoulSource:
    """soul 文件真源服务.

    Attributes:
        root_dir (Path): soul 文件根目录.
    """

    root_dir: Path

    CORE_FILES: tuple[str, ...] = ("identity.md", "soul.md", "state.yaml", "task.md")

    def __post_init__(self) -> None:
        """初始化 soul 目录并补齐主文件."""

        self.root_dir = Path(self.root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_core_files()

    def list_files(self) -> list[dict[str, Any]]:
        """列出 soul 目录下的可编辑文件.

        Returns:
            文件列表, 主文件优先.
        """

        items: list[dict[str, Any]] = []
        for name in self.CORE_FILES:
            path = self.root_dir / name
            items.append(self._to_item(path=path, name=name, is_core=True))
        for path in sorted(self.root_dir.iterdir(), key=lambda item: item.name):
            if not path.is_file():
                continue
            if path.name in self.CORE_FILES:
                continue
            items.append(self._to_item(path=path, name=path.name, is_core=False))
        return items

    def read_file(self, name: str) -> dict[str, Any]:
        """读取一个 soul 文件.

        Args:
            name: 文件名.

        Returns:
            文件元数据和正文.
        """

        path = self._resolve_name(name)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"soul file not found: {name}")
        content = path.read_text(encoding="utf-8")
        return {
            "name": path.name,
            "is_core": path.name in self.CORE_FILES,
            "content": content,
            "size": len(content.encode("utf-8")),
            "updated_at": _now_timestamp(path),
        }

    def write_file(self, name: str, content: str) -> dict[str, Any]:
        """写入一个 soul 文件.

        Args:
            name: 文件名.
            content: 新内容.

        Returns:
            写入后的文件信息.
        """

        path = self._resolve_name(name)
        normalized_content = str(content)
        if path.name == "state.yaml":
            self._validate_state_yaml(normalized_content)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(normalized_content, encoding="utf-8")
        return self.read_file(path.name)

    def create_file(self, name: str, content: str = "") -> dict[str, Any]:
        """创建一个新的 soul 附加文件.

        Args:
            name: 文件名.
            content: 初始内容.

        Returns:
            新文件信息.
        """

        path = self._resolve_name(name)
        if path.exists():
            raise ValueError(f"soul file already exists: {name}")
        if path.name == "state.yaml":
            self._validate_state_yaml(str(content))
        path.write_text(str(content), encoding="utf-8")
        return self.read_file(path.name)

    def build_prompt_text(self) -> str:
        """生成用于运行时装配的 soul 文本.

        Returns:
            稳定的 soul prompt 文本.
        """

        sections: list[str] = []
        for name in self.CORE_FILES:
            payload = self.read_file(name)
            raw_content = str(payload.get("content", "") or "")
            content = raw_content.strip() or "(empty)"
            sections.append(f"[{name}]\n{content}")
        return "\n\n".join(sections).strip()

    # region helpers
    def _ensure_core_files(self) -> None:
        """确保 soul 主文件存在."""

        defaults = {
            "identity.md": self._default_identity_text(),
            "soul.md": self._default_soul_text(),
            "state.yaml": self._default_state_text(),
            "task.md": self._default_task_text(),
        }
        for name in self.CORE_FILES:
            path = self.root_dir / name
            if path.exists():
                continue
            path.write_text(defaults.get(name, ""), encoding="utf-8")

    @staticmethod
    def _default_identity_text() -> str:
        """返回 `identity.md` 的默认内容.

        Returns:
            用于初始化 `identity.md` 的模板文本.
        """

        return textwrap.dedent(
            """
            # 我是谁

            - 名字:
            - 身份:
            - 长期角色:
            - 对外自称:

            # 我负责什么

            - 长期职责:
            - 不负责什么:
            """
        ).strip() + "\n"

    @staticmethod
    def _default_soul_text() -> str:
        """返回 `soul.md` 的默认内容.

        Returns:
            用于初始化 `soul.md` 的模板文本.
        """

        return textwrap.dedent(
            """
            # 我的气质

            - 说话风格:
            - 做事风格:
            - 价值倾向:

            # 我的边界

            - 应该坚持什么:
            - 应该避免什么:
            """
        ).strip() + "\n"

    @staticmethod
    def _default_state_text() -> str:
        """返回 `state.yaml` 的默认内容.

        Returns:
            用于初始化 `state.yaml` 的 YAML 模板.
        """

        return textwrap.dedent(
            """
            mood: ""
            focus: []
            commitments: []
            notes: []
            """
        ).lstrip()

    @staticmethod
    def _default_task_text() -> str:
        """返回 `task.md` 的默认内容.

        Returns:
            用于初始化 `task.md` 的模板文本.
        """

        return textwrap.dedent(
            """
            # 正在做

            - 当前任务:
            - 当前目标:

            # 接下来要做

            - 下一步:
            - 等待确认:
            """
        ).strip() + "\n"

    def _resolve_name(self, name: str) -> Path:
        """把文件名解析成受控路径.

        Args:
            name: 原始文件名.

        Returns:
            受控文件路径.
        """

        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("soul file name cannot be empty")
        if "/" in normalized or "\\" in normalized:
            raise ValueError("invalid soul file name")
        if normalized in {".", ".."} or normalized.startswith("."):
            raise ValueError("invalid soul file name")
        path = (self.root_dir / normalized).resolve()
        try:
            path.relative_to(self.root_dir)
        except ValueError as exc:
            raise ValueError("invalid soul file path") from exc
        return path

    @staticmethod
    def _validate_state_yaml(content: str) -> None:
        """校验 `state.yaml` 是否可解析.

        Args:
            content: 待校验文本.
        """

        try:
            yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise ValueError(f"state.yaml must be valid yaml: {exc}") from exc

    @staticmethod
    def _to_item(*, path: Path, name: str, is_core: bool) -> dict[str, Any]:
        """构造文件列表项.

        Args:
            path: 文件路径.
            name: 文件名.
            is_core: 是否主文件.

        Returns:
            可供接口返回的文件元信息.
        """

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

    # endregion


# endregion
