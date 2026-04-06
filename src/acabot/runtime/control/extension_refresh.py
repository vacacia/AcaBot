"""runtime.control.extension_refresh 提供共享的扩展刷新服务。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ..skills import SkillCatalog
from .session_loader import SessionConfigLoader

DEFAULT_SKILL_CATALOG_DIRS = ["./extensions/skills"]


if TYPE_CHECKING:
    from .config_control_plane import RuntimeConfigControlPlane


@dataclass(frozen=True, slots=True)
class SkillRefreshPaths:
    """描述一次 skill 刷新涉及到的关键宿主机路径。"""

    session_id: str
    project_skill_root_path: str
    session_dir_path: str
    session_config_path: str
    agent_config_path: str


class ExtensionRefreshService:
    """集中实现 skill catalog 刷新、agent visible_skills 回写和 loader 失效。"""

    def __init__(
        self,
        *,
        config_control_plane: RuntimeConfigControlPlane,
        skill_catalog: SkillCatalog | None,
    ) -> None:
        """初始化服务。"""

        self.config_control_plane = config_control_plane
        self.skill_catalog = skill_catalog

    def describe_skill_refresh_paths(self, *, session_id: str) -> SkillRefreshPaths:
        """返回某个 session 的 skill 刷新路径摘要。"""

        project_roots = [
            Path(item["host_root_path"]).resolve()
            for item in self.config_control_plane._resolved_catalog_dir_views(
                key="skill_catalog_dirs",
                defaults=DEFAULT_SKILL_CATALOG_DIRS,
            )
            if str(item.get("scope", "") or "") == "project"
        ]
        unique_project_roots = sorted({str(path) for path in project_roots})
        if len(unique_project_roots) != 1:
            raise ValueError("refresh_skills requires a unique project-scope skill root")

        sessions_dir = self.config_control_plane._sessions_dir()
        session_config_path = SessionConfigLoader(config_root=sessions_dir).path_for_session_id(session_id)
        session_dir_path = session_config_path.parent
        agent_config_path = session_dir_path / "agent.yaml"
        if not session_config_path.exists():
            raise FileNotFoundError(f"session config not found: {session_id}")
        if not agent_config_path.exists():
            raise FileNotFoundError(f"session agent config not found: {session_id}")
        return SkillRefreshPaths(
            session_id=session_id,
            project_skill_root_path=unique_project_roots[0],
            session_dir_path=str(session_dir_path),
            session_config_path=str(session_config_path),
            agent_config_path=str(agent_config_path),
        )

    async def refresh_skills(self, *, session_id: str) -> dict[str, Any]:
        """刷新 live skill catalog，并把某个 session 的 visible_skills 回写成当前赢家集合。"""

        if self.skill_catalog is None:
            raise RuntimeError("skill catalog unavailable")

        paths = self.describe_skill_refresh_paths(session_id=session_id)
        self.skill_catalog.replace_loader(self.config_control_plane._skill_catalog_loader())
        self.skill_catalog.reload()
        visible_skills = self._winner_skill_names()
        changed, previous_visible_skills = self._rewrite_session_agent_visible_skills(
            agent_config_path=Path(paths.agent_config_path),
            visible_skills=visible_skills,
        )
        self.config_control_plane._refresh_session_bundle_loader()
        await self.config_control_plane._refresh_session_agent_targets()
        bundle = self.config_control_plane.session_bundle_loader.load_by_session_id(session_id)
        return {
            "kind": "skills",
            "session_id": session_id,
            "changed": changed,
            "visible_skills": list(bundle.frontstage_agent.visible_skills),
            "previous_visible_skills": previous_visible_skills,
            "project_skill_root_path": paths.project_skill_root_path,
            "agent_config_path": paths.agent_config_path,
        }

    def _winner_skill_names(self) -> list[str]:
        """按当前 catalog 正式选择规则返回全部唯一 skill 名称。"""

        winners: list[str] = []
        seen: set[str] = set()
        for item in self.skill_catalog.list_all():
            if item.skill_name in seen:
                continue
            winners.append(item.skill_name)
            seen.add(item.skill_name)
        return winners

    @staticmethod
    def _rewrite_session_agent_visible_skills(
        *,
        agent_config_path: Path,
        visible_skills: list[str],
    ) -> tuple[bool, list[str]]:
        """直接回写 `agent.yaml.visible_skills`，不依赖已验证的 bundle 加载。"""

        raw = yaml.safe_load(agent_config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Session agent file must be a mapping: {agent_config_path}")
        previous_visible_skills = [
            str(item)
            for item in list(raw.get("visible_skills", []) or [])
            if str(item)
        ]
        changed = previous_visible_skills != list(visible_skills)
        raw["visible_skills"] = list(visible_skills)
        agent_config_path.write_text(
            yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return changed, previous_visible_skills


__all__ = ["ExtensionRefreshService", "SkillRefreshPaths"]
