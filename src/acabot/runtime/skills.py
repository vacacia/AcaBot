"""runtime.skills 定义 skill catalog 和 delegation 边界."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import AgentProfile, SkillAssignment
from .skill_loader import FileSystemSkillPackageLoader
from .skill_package import SkillPackageDocument, SkillPackageManifest


@dataclass(slots=True)
class ResolvedSkillAssignment:
    """一条已经展开后的 skill assignment."""

    skill: SkillPackageManifest
    assignment: SkillAssignment


@dataclass(slots=True)
class SubagentDelegationRequest:
    """未来 subagent delegation 调用的请求边界."""

    skill_name: str
    parent_run_id: str
    parent_thread_id: str
    parent_agent_id: str
    actor_id: str
    channel_scope: str
    delegate_agent_id: str
    payload: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class SubagentDelegationResult:
    """未来 subagent delegation 调用的返回边界."""

    skill_name: str
    ok: bool
    delegated_run_id: str = ""
    summary: str = ""
    artifacts: list[dict[str, object]] = field(default_factory=list)
    error: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


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
