"""runtime.skill_loader 提供 filesystem skill package loader."""

from __future__ import annotations

import logging
from pathlib import Path

from .package import (
    SkillPackageDocument,
    SkillPackageFormatError,
    SkillPackageManifest,
    parse_skill_package,
)

logger = logging.getLogger("acabot.runtime.skill_loader")


class FileSystemSkillPackageLoader:
    """从统一 skill catalog 目录读取 skill package."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).expanduser()

    def discover(self) -> list[SkillPackageManifest]:
        manifests: list[SkillPackageManifest] = []
        if not self.root_dir.exists():
            return manifests
        for path in sorted(item for item in self.root_dir.iterdir() if item.is_dir()):
            try:
                manifests.append(self.read_manifest(path.name))
            except SkillPackageFormatError as exc:
                logger.warning("Skipping invalid skill package '%s': %s", path.name, exc)
        return manifests

    def read_manifest(self, skill_name: str) -> SkillPackageManifest:
        return self.read_document(skill_name).manifest

    def read_document(self, skill_name: str) -> SkillPackageDocument:
        skill_dir = self.root_dir / skill_name
        if not skill_dir.exists() or not skill_dir.is_dir():
            raise KeyError(skill_name)
        return parse_skill_package(skill_name=skill_name, root_dir=skill_dir)
