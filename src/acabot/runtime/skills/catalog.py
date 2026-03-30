"""runtime.skills 定义 skill catalog 和 agent 可见 skill 边界."""

from __future__ import annotations

from collections import defaultdict

from ..contracts import ResolvedAgent
from .loader import FileSystemSkillPackageLoader
from .package import SkillPackageDocument, SkillPackageManifest


class SkillCatalog:
    """统一 skill catalog."""

    def __init__(self, loader: FileSystemSkillPackageLoader | None = None) -> None:
        self.loader = loader
        self._skills: list[SkillPackageManifest] = []
        self._skills_by_name: dict[str, list[SkillPackageManifest]] = {}

    def reload(self) -> list[SkillPackageManifest]:
        """重新扫描全部 skill metadata."""

        if self.loader is None:
            self._skills = []
            self._skills_by_name = {}
            return []
        manifests = list(self.loader.discover())
        grouped: dict[str, list[SkillPackageManifest]] = defaultdict(list)
        for item in manifests:
            grouped[item.skill_name].append(item)
        self._skills = sorted(
            manifests,
            key=lambda item: (item.skill_name, self._scope_rank(item.scope), item.host_skill_file_path),
        )
        self._skills_by_name = {
            name: sorted(
                items,
                key=lambda item: (self._scope_rank(item.scope), item.host_skill_file_path),
            )
            for name, items in grouped.items()
        }
        return self.list_all()

    def replace_loader(self, loader: FileSystemSkillPackageLoader | None) -> None:
        """替换当前 catalog 使用的底层 loader."""

        self.loader = loader

    def get(self, skill_name: str) -> SkillPackageManifest | None:
        """按当前正式选择规则拿一条 skill metadata."""

        candidates = self._skills_by_name.get(skill_name, [])
        if not candidates:
            return None
        return candidates[0]

    def list_all(self) -> list[SkillPackageManifest]:
        """列出全部扫描到的 skill metadata, 不做同名过滤."""

        return list(self._skills)

    def read(self, skill_name: str) -> SkillPackageDocument:
        """按当前正式选择规则读取一条 skill 文档."""

        manifest = self.get(skill_name)
        if manifest is None:
            raise KeyError(skill_name)
        if self.loader is None:
            raise KeyError(skill_name)
        return self.loader.read_document_for_manifest(manifest)

    def visible_skills(self, agent: ResolvedAgent) -> list[SkillPackageManifest]:
        """按 agent 技能可见性和 scope 优先级选出可见 skills."""

        visible: list[SkillPackageManifest] = []
        seen: set[str] = set()
        for skill_name in agent.skills:
            if skill_name in seen:
                continue
            manifest = self.get(skill_name)
            if manifest is None:
                continue
            visible.append(manifest)
            seen.add(skill_name)
        return visible

    @staticmethod
    def _scope_rank(scope: str) -> int:
        """给 scope 一个稳定优先级."""

        if scope == "project":
            return 0
        if scope == "user":
            return 1
        return 99
