"""runtime.subagents.loader 提供 filesystem subagent package loader.

这个 loader 负责两件事:

- 从一个或多个 subagent 根目录里递归发现 `SUBAGENT.md`
- 把所有发现到的 subagent metadata 原样交给 catalog

它不负责按同名去重, 也不负责决定 project 和 user 谁生效.
这些事情交给 `runtime.subagents.catalog`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .package import (
    SubagentPackageDocument,
    SubagentPackageFormatError,
    SubagentPackageManifest,
    parse_subagent_package,
)

logger = logging.getLogger("acabot.runtime.subagent_loader")


@dataclass(slots=True)
class SubagentDiscoveryRoot:
    """一个要扫描的 subagent 根目录.

    Attributes:
        host_root_path (str): subagent 根目录的宿主机绝对路径.
        scope (str): 这个根目录下 subagent 的来源范围.
    """

    host_root_path: str
    scope: str = "project"

    @property
    def path(self) -> Path:
        """返回当前根目录的 Path 对象."""

        return Path(self.host_root_path).expanduser().resolve()


class FileSystemSubagentPackageLoader:
    """从一个或多个 filesystem subagent 根目录读取 subagent package."""

    def __init__(
        self,
        root_dir: str | Path | SubagentDiscoveryRoot | Iterable[str | Path | SubagentDiscoveryRoot],
    ) -> None:
        """保存 subagent 根目录列表.

        Args:
            root_dir: 单个根目录, 或按顺序排列的多个根目录.
        """

        self.roots = self._normalize_roots(root_dir)
        self.root_dir = self.roots[0].path if self.roots else Path(".").expanduser().resolve()
        self.root_dirs = [item.path for item in self.roots]
        self._manifests: list[SubagentPackageManifest] = []

    def discover(self) -> list[SubagentPackageManifest]:
        """递归发现全部有效 subagent package.

        Returns:
            list[SubagentPackageManifest]: 按名字、scope、路径排序后的完整 subagent 列表.
        """

        manifests: list[SubagentPackageManifest] = []
        for root in self.roots:
            if not root.path.exists():
                continue
            for subagent_dir in self._iter_subagent_dirs(root.path):
                subagent_name = self._subagent_name_for_dir(root.path, subagent_dir)
                try:
                    document = self._read_document_from_dir(
                        subagent_name=subagent_name,
                        scope=root.scope,
                        subagent_dir=subagent_dir,
                    )
                except SubagentPackageFormatError as exc:
                    logger.warning("Skipping invalid subagent package '%s': %s", subagent_name, exc)
                    continue
                manifests.append(document.manifest)
        manifests.sort(
            key=lambda item: (item.subagent_name, self._scope_rank(item.scope), item.host_subagent_file_path)
        )
        self._manifests = manifests
        return list(self._manifests)

    def read_manifest(self, subagent_name: str) -> SubagentPackageManifest:
        """读取单个 subagent 的 manifest."""

        return self.read_document(subagent_name).manifest

    def read_document(self, subagent_name: str) -> SubagentPackageDocument:
        """读取单个 subagent 的完整文档."""

        manifest = self._resolve_single_manifest(subagent_name)
        return self.read_document_for_manifest(manifest)

    def read_document_for_manifest(self, manifest: SubagentPackageManifest) -> SubagentPackageDocument:
        """按 manifest 直接读取 subagent 文档."""

        return parse_subagent_package(
            subagent_name=manifest.subagent_name,
            scope=manifest.scope,
            root_dir=Path(manifest.host_subagent_file_path).resolve().parent,
        )

    def _resolve_single_manifest(self, subagent_name: str) -> SubagentPackageManifest:
        """按名字选出一个单条 manifest."""

        candidates = [item for item in self.discover() if item.subagent_name == subagent_name]
        if candidates:
            candidates.sort(key=lambda item: (self._scope_rank(item.scope), item.host_subagent_file_path))
            return candidates[0]
        subagent_dir, scope = self._find_candidate_subagent_dir(subagent_name)
        if subagent_dir is None:
            raise KeyError(subagent_name)
        return self._read_document_from_dir(
            subagent_name=subagent_name,
            scope=scope,
            subagent_dir=subagent_dir,
        ).manifest

    @staticmethod
    def _normalize_roots(
        root_dir: str | Path | SubagentDiscoveryRoot | Iterable[str | Path | SubagentDiscoveryRoot],
    ) -> list[SubagentDiscoveryRoot]:
        """把输入根目录收成去重后的扫描根列表."""

        if isinstance(root_dir, (str, Path, SubagentDiscoveryRoot)):
            raw_items = [root_dir]
        else:
            raw_items = list(root_dir)
        normalized: list[SubagentDiscoveryRoot] = []
        seen: set[tuple[str, str]] = set()
        for item in raw_items:
            if isinstance(item, SubagentDiscoveryRoot):
                root = SubagentDiscoveryRoot(
                    host_root_path=str(item.host_root_path),
                    scope=str(item.scope or "project"),
                )
            else:
                raw = str(item or "").strip()
                if not raw:
                    continue
                root = SubagentDiscoveryRoot(host_root_path=raw, scope="project")
            key = (str(root.path), root.scope)
            if key in seen:
                continue
            normalized.append(root)
            seen.add(key)
        return normalized

    @staticmethod
    def _iter_subagent_dirs(root_dir: Path) -> list[Path]:
        """列出某个根目录下全部包含 `SUBAGENT.md` 的目录."""

        subagent_dirs: list[Path] = []
        for subagent_md in sorted(
            root_dir.rglob("SUBAGENT.md"),
            key=lambda item: str(item.relative_to(root_dir)),
        ):
            if not subagent_md.is_file():
                continue
            subagent_dirs.append(subagent_md.parent)
        return subagent_dirs

    @staticmethod
    def _subagent_name_for_dir(root_dir: Path, subagent_dir: Path) -> str:
        """把 subagent 目录相对路径转成稳定 subagent 名."""

        relative = subagent_dir.relative_to(root_dir)
        parts = [part for part in relative.parts if part]
        if not parts:
            return subagent_dir.name
        return ":".join(parts)

    def _find_candidate_subagent_dir(self, subagent_name: str) -> tuple[Path | None, str]:
        """按 subagent 名直接推导可能的目录位置."""

        relative = Path(*[part for part in subagent_name.split(":") if part])
        for root in self.roots:
            candidate = (root.path / relative).resolve()
            if candidate.exists() and candidate.is_dir():
                return candidate, root.scope
        return None, "project"

    @staticmethod
    def _scope_rank(scope: str) -> int:
        """给 scope 一个稳定优先级."""

        if scope == "project":
            return 0
        if scope == "user":
            return 1
        return 99

    @staticmethod
    def _read_document_from_dir(
        *,
        subagent_name: str,
        scope: str,
        subagent_dir: Path,
    ) -> SubagentPackageDocument:
        """直接从指定 subagent 目录读取文档."""

        return parse_subagent_package(
            subagent_name=subagent_name,
            scope=scope,
            root_dir=subagent_dir,
        )
