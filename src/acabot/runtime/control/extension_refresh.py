"""runtime.control.extension_refresh 提供共享的扩展刷新服务。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import stat
from tempfile import TemporaryDirectory
import time
from typing import TYPE_CHECKING, Any
import zipfile

import yaml

from ..skills import SkillCatalog
from ..skills.package import SkillPackageFormatError, parse_skill_package
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
        visible_skills = self._reload_catalog_and_collect_winners()
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

    async def install_skill_zip(self, *, filename: str, content: bytes) -> dict[str, Any]:
        """把一份 zip skill 包安装到项目级 skill 根目录, 并刷新 catalog。"""

        if self.skill_catalog is None:
            raise RuntimeError("skill catalog unavailable")
        project_skill_root_path = self._unique_project_skill_root_path()
        project_skill_root = Path(project_skill_root_path)
        project_skill_root.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory(prefix="acabot-skill-upload-") as temp_dir:
            temp_root = Path(temp_dir)
            package_root = self._extract_uploaded_zip(
                archive_bytes=content,
                archive_filename=filename,
                destination_root=temp_root,
            )
            target_name = self._target_name_for_package_root(
                package_root=package_root,
                archive_filename=filename,
            )
            parse_skill_package(
                skill_name=target_name,
                scope="project",
                root_dir=package_root,
            )
            target_dir = project_skill_root / target_name
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(package_root, target_dir)
            self._write_install_origin_file(
                target_dir=target_dir,
                archive_filename=filename,
            )

        visible_skills = self._reload_catalog_and_collect_winners()
        session_updates = self._rewrite_all_session_agent_visible_skills(visible_skills=visible_skills)
        self.config_control_plane._refresh_session_bundle_loader()
        await self.config_control_plane._refresh_session_agent_targets()
        installed_manifest = self.skill_catalog.get(target_name)
        if installed_manifest is None:
            raise RuntimeError(f"installed skill not visible after refresh: {target_name}")
        return {
            "installed_skill": {
                "skill_name": installed_manifest.skill_name,
                "display_name": installed_manifest.display_name,
                "description": installed_manifest.description,
                "has_references": installed_manifest.has_references,
                "has_scripts": installed_manifest.has_scripts,
                "has_assets": installed_manifest.has_assets,
                "host_skill_root_path": installed_manifest.host_skill_root_path,
            },
            "project_skill_root_path": project_skill_root_path,
            "visible_skills": visible_skills,
            "session_updates": session_updates,
        }

    def _reload_catalog_and_collect_winners(self) -> list[str]:
        """重建 loader 并返回当前技能赢家集合。"""

        self.skill_catalog.replace_loader(self.config_control_plane._skill_catalog_loader())
        self.skill_catalog.reload()
        return self._winner_skill_names()

    def _rewrite_all_session_agent_visible_skills(self, *, visible_skills: list[str]) -> list[dict[str, Any]]:
        """把全部 session 的 visible_skills 回写成当前赢家集合。"""

        updates: list[dict[str, Any]] = []
        for item in self.config_control_plane.list_sessions():
            session_id = str(item.get("session_id", "") or "").strip()
            if not session_id:
                continue
            try:
                paths = self.describe_skill_refresh_paths(session_id=session_id)
                changed, previous_visible_skills = self._rewrite_session_agent_visible_skills(
                    agent_config_path=Path(paths.agent_config_path),
                    visible_skills=visible_skills,
                )
            except FileNotFoundError:
                continue
            updates.append(
                {
                    "session_id": session_id,
                    "changed": changed,
                    "previous_visible_skills": previous_visible_skills,
                }
            )
        return updates

    def _unique_project_skill_root_path(self) -> str:
        """返回唯一的项目级 skill 根目录。"""

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
            raise ValueError("skill install requires a unique project-scope skill root")
        return unique_project_roots[0]

    def _extract_uploaded_zip(
        self,
        *,
        archive_bytes: bytes,
        archive_filename: str,
        destination_root: Path,
    ) -> Path:
        """把上传 zip 安全解压到临时目录, 并定位 skill 根目录。"""

        _ = archive_filename
        archive_path = destination_root / "upload.zip"
        archive_path.write_bytes(archive_bytes)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                infos = archive.infolist()
                if not infos:
                    raise ValueError("uploaded zip is empty")
                for info in infos:
                    self._validate_archive_entry(info)
                archive.extractall(destination_root / "unzipped")
        except zipfile.BadZipFile as exc:
            raise ValueError("uploaded file is not a valid zip archive") from exc
        extracted_root = destination_root / "unzipped"
        direct_skill_md = extracted_root / "SKILL.md"
        if direct_skill_md.is_file():
            return extracted_root
        top_level_dirs = [item for item in extracted_root.iterdir() if item.is_dir()]
        if len(top_level_dirs) == 1 and (top_level_dirs[0] / "SKILL.md").is_file():
            return top_level_dirs[0]
        raise SkillPackageFormatError("zip must contain exactly one skill root with SKILL.md")

    @staticmethod
    def _validate_archive_entry(info: zipfile.ZipInfo) -> None:
        """拒绝路径穿越、绝对路径和 symlink。"""

        normalized = str(info.filename or "").replace("\\", "/")
        parts = [part for part in normalized.split("/") if part not in {"", "."}]
        if not parts:
            return
        if normalized.startswith("/") or any(part == ".." for part in parts):
            raise ValueError(f"unsafe zip entry: {info.filename}")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise ValueError(f"zip symlink entry is not allowed: {info.filename}")

    @staticmethod
    def _target_name_for_package_root(*, package_root: Path, archive_filename: str) -> str:
        """为安装目录选一个稳定名字。"""

        raw_name = package_root.name or Path(str(archive_filename or "skill.zip")).stem
        normalized = str(raw_name).strip().replace(" ", "-")
        normalized = "".join(ch for ch in normalized if ch.isalnum() or ch in {"-", "_", "."})
        if not normalized:
            raise ValueError("cannot infer skill directory name from uploaded zip")
        return normalized

    @staticmethod
    def _write_install_origin_file(*, target_dir: Path, archive_filename: str) -> None:
        """记录上传安装来源, 便于后续追踪。"""

        origin_path = target_dir / ".acabot-origin.json"
        origin_payload = {
            "installed_via": "webui-upload",
            "archive_filename": str(archive_filename or ""),
            "installed_at": int(time.time()),
        }
        origin_path.write_text(
            json.dumps(origin_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
