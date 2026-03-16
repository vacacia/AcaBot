"""runtime.skills 定义 skill catalog 和 skill assignment 边界."""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import AgentProfile, SkillAssignment
from .loader import FileSystemSkillPackageLoader
from .package import SkillPackageDocument, SkillPackageManifest


@dataclass(slots=True)
class ResolvedSkillAssignment:
    """一条已经展开后的 skill assignment."""

    skill: SkillPackageManifest
    assignment: SkillAssignment


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
        return [item.skill for item in self.resolve_assignments(profile)]

    def resolve_assignments(self, profile: AgentProfile) -> list[ResolvedSkillAssignment]:
        resolved: list[ResolvedSkillAssignment] = []
        seen: set[str] = set()
        for assignment in profile.skill_assignments:
            if assignment.skill_name in seen:
                continue
            manifest = self._skills.get(assignment.skill_name)
            if manifest is None:
                continue
            resolved.append(ResolvedSkillAssignment(skill=manifest, assignment=assignment))
            seen.add(assignment.skill_name)
        return resolved
