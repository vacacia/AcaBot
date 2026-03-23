"""runtime.skills.loader 提供 filesystem skill package loader.

这个 loader 负责两件事:

- 从一个或多个 skill 根目录里递归发现 `SKILL.md`
- 把所有发现到的 skill metadata 原样交给 catalog

它不负责按同名去重, 也不负责决定 project 和 user 谁生效.
那些事情交给 `runtime.skills.catalog`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .package import (
    SkillPackageDocument,
    SkillPackageFormatError,
    SkillPackageManifest,
    parse_skill_package,
)

logger = logging.getLogger("acabot.runtime.skill_loader")


@dataclass(slots=True)
class SkillDiscoveryRoot:
    """一个要扫描的 skill 根目录.

    Attributes:
        host_root_path (str): skill 根目录的宿主机绝对路径.
        scope (str): 这个根目录下 skill 的来源范围.
    """

    host_root_path: str
    scope: str = "project"

    @property
    def path(self) -> Path:
        """返回当前根目录的 Path 对象."""

        return Path(self.host_root_path).expanduser().resolve()


# region loader
class FileSystemSkillPackageLoader:
    """从一个或多个 filesystem skill 根目录读取 skill package.

    Attributes:
        roots (list[SkillDiscoveryRoot]): 按扫描顺序排列的 skill 根目录列表.
        root_dir (Path): 兼容旧调用方保留的主根目录.
        root_dirs (list[Path]): 兼容旧调用方保留的根目录路径列表.
        _manifests (list[SkillPackageManifest]): 最近一次 discover 的全部 manifest.
    """

    def __init__(
        self,
        root_dir: str | Path | SkillDiscoveryRoot | Iterable[str | Path | SkillDiscoveryRoot],
    ) -> None:
        """保存 skill 根目录列表.

        Args:
            root_dir: 单个根目录, 或按顺序排列的多个根目录.
        """

        self.roots = self._normalize_roots(root_dir)
        self.root_dir = self.roots[0].path if self.roots else Path(".").expanduser().resolve()
        self.root_dirs = [item.path for item in self.roots]
        self._manifests: list[SkillPackageManifest] = []

    def discover(self) -> list[SkillPackageManifest]:
        """递归发现全部有效 skill package.

        Returns:
            list[SkillPackageManifest]: 按名字、scope、路径排序后的完整 skill 列表.
        """

        manifests: list[SkillPackageManifest] = []
        for root in self.roots:
            if not root.path.exists():
                continue
            for skill_dir in self._iter_skill_dirs(root.path):
                skill_name = self._skill_name_for_dir(root.path, skill_dir)
                try:
                    document = self._read_document_from_dir(
                        skill_name=skill_name,
                        scope=root.scope,
                        skill_dir=skill_dir,
                    )
                except SkillPackageFormatError as exc:
                    logger.warning("Skipping invalid skill package '%s': %s", skill_name, exc)
                    continue
                manifests.append(document.manifest)
        manifests.sort(
            key=lambda item: (item.skill_name, self._scope_rank(item.scope), item.host_skill_file_path)
        )
        self._manifests = manifests
        return list(self._manifests)

    def read_manifest(self, skill_name: str) -> SkillPackageManifest:
        """读取单个 skill 的 manifest.

        Args:
            skill_name: 目标 skill 名.

        Returns:
            SkillPackageManifest: 目标 skill 的 manifest.
        """

        return self.read_document(skill_name).manifest

    def read_document(self, skill_name: str) -> SkillPackageDocument:
        """读取单个 skill 的完整文档.

        这里主要服务没有重名冲突的简单读取场景.
        真正的 project > user 选择逻辑由 catalog 负责.

        Args:
            skill_name: 目标 skill 名.

        Returns:
            SkillPackageDocument: 目标 skill 的完整文档.

        Raises:
            KeyError: skill 不存在时抛出.
        """

        manifest = self._resolve_single_manifest(skill_name)
        return self.read_document_for_manifest(manifest)

    def read_document_for_manifest(self, manifest: SkillPackageManifest) -> SkillPackageDocument:
        """按 manifest 直接读取 skill 文档.

        Args:
            manifest: 已解析出的 skill metadata.

        Returns:
            SkillPackageDocument: 对应的完整文档.
        """

        return parse_skill_package(
            skill_name=manifest.skill_name,
            scope=manifest.scope,
            root_dir=Path(manifest.host_skill_file_path).resolve().parent,
        )

    def _resolve_single_manifest(self, skill_name: str) -> SkillPackageManifest:
        """按名字选出一个单条 manifest.

        Args:
            skill_name: 目标 skill 名.

        Returns:
            SkillPackageManifest: 选中的 manifest.

        Raises:
            KeyError: skill 不存在时抛出.
        """

        candidates = [item for item in self.discover() if item.skill_name == skill_name]
        if candidates:
            candidates.sort(key=lambda item: (self._scope_rank(item.scope), item.host_skill_file_path))
            return candidates[0]
        skill_dir, scope = self._find_candidate_skill_dir(skill_name)
        if skill_dir is None:
            raise KeyError(skill_name)
        return self._read_document_from_dir(
            skill_name=skill_name,
            scope=scope,
            skill_dir=skill_dir,
        ).manifest

    @staticmethod
    def _normalize_roots(
        root_dir: str | Path | SkillDiscoveryRoot | Iterable[str | Path | SkillDiscoveryRoot],
    ) -> list[SkillDiscoveryRoot]:
        """把输入根目录收成去重后的扫描根列表."""

        if isinstance(root_dir, (str, Path, SkillDiscoveryRoot)):
            raw_items = [root_dir]
        else:
            raw_items = list(root_dir)
        normalized: list[SkillDiscoveryRoot] = []
        seen: set[tuple[str, str]] = set()
        for item in raw_items:
            if isinstance(item, SkillDiscoveryRoot):
                root = SkillDiscoveryRoot(
                    host_root_path=str(item.host_root_path),
                    scope=str(item.scope or "project"),
                )
            else:
                raw = str(item or "").strip()
                if not raw:
                    continue
                root = SkillDiscoveryRoot(host_root_path=raw, scope="project")
            key = (str(root.path), root.scope)
            if key in seen:
                continue
            normalized.append(root)
            seen.add(key)
        return normalized

    @staticmethod
    def _iter_skill_dirs(root_dir: Path) -> list[Path]:
        """列出某个根目录下全部包含 `SKILL.md` 的目录."""

        skill_dirs: list[Path] = []
        for skill_md in sorted(
            root_dir.rglob("SKILL.md"),
            key=lambda item: str(item.relative_to(root_dir)),
        ):
            if not skill_md.is_file():
                continue
            skill_dirs.append(skill_md.parent)
        return skill_dirs

    @staticmethod
    def _skill_name_for_dir(root_dir: Path, skill_dir: Path) -> str:
        """把 skill 目录相对路径转成稳定 skill 名."""

        relative = skill_dir.relative_to(root_dir)
        parts = [part for part in relative.parts if part]
        if not parts:
            return skill_dir.name
        return ":".join(parts)

    def _find_candidate_skill_dir(self, skill_name: str) -> tuple[Path | None, str]:
        """按 skill 名直接推导可能的目录位置."""

        relative = Path(*[part for part in skill_name.split(":") if part])
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
    def _read_document_from_dir(*, skill_name: str, scope: str, skill_dir: Path) -> SkillPackageDocument:
        """直接从指定 skill 目录读取文档."""

        return parse_skill_package(skill_name=skill_name, scope=scope, root_dir=skill_dir)


# endregion
