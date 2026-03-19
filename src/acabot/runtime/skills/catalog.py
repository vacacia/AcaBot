"""runtime.skills 定义 skill catalog 和 profile 可见 skill 边界."""

from __future__ import annotations

from ..contracts import AgentProfile
from .loader import FileSystemSkillPackageLoader
from .package import SkillPackageDocument, SkillPackageManifest


class SkillCatalog:
    """统一 skill catalog."""

    def __init__(self, loader: FileSystemSkillPackageLoader | None = None) -> None:
        self.loader = loader
        self._skills: dict[str, SkillPackageManifest] = {}

    def reload(self) -> list[SkillPackageManifest]:
        if self.loader is None:
            self._skills = {}
            return []
        manifests = self.loader.discover()
        self._skills = {item.skill_name: item for item in manifests}
        return self.list_all()

    def get(self, skill_name: str) -> SkillPackageManifest | None:
        return self._skills.get(skill_name)

    def list_all(self) -> list[SkillPackageManifest]:
        return [self._skills[name] for name in sorted(self._skills)]

    def read(self, skill_name: str) -> SkillPackageDocument:
        manifest = self._skills.get(skill_name)
        if manifest is None:
            raise KeyError(skill_name)
        if self.loader is None:
            raise KeyError(skill_name)
        return self.loader.read_document(skill_name)

    def visible_skills(self, profile: AgentProfile) -> list[SkillPackageManifest]:
        visible: list[SkillPackageManifest] = []
        seen: set[str] = set()
        for skill_name in profile.skills:
            if skill_name in seen:
                continue
            manifest = self._skills.get(skill_name)
            if manifest is None:
                continue
            visible.append(manifest)
            seen.add(skill_name)
        return visible
