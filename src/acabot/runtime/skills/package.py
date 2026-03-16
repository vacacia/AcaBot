"""runtime.skill_package 定义 skill package 的标准数据对象."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class SkillPackageFormatError(ValueError):
    """当前 skill package 不满足约定格式."""


@dataclass(slots=True)
class SkillPackageManifest:
    """一条 skill package 的轻量清单."""

    skill_name: str
    display_name: str
    description: str
    root_dir: str
    skill_md_path: str
    references_dir: str = ""
    scripts_dir: str = ""
    assets_dir: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_references(self) -> bool:
        return bool(self.references_dir)

    @property
    def has_scripts(self) -> bool:
        return bool(self.scripts_dir)

    @property
    def has_assets(self) -> bool:
        return bool(self.assets_dir)


@dataclass(slots=True)
class SkillPackageDocument:
    """一条完整 skill package 文档."""

    manifest: SkillPackageManifest
    raw_markdown: str
    body_markdown: str


def parse_skill_package(
    *,
    skill_name: str,
    root_dir: str | Path,
) -> SkillPackageDocument:
    """从 skill 目录解析出标准 package 文档."""

    root = Path(root_dir).expanduser().resolve()
    skill_md = root / "SKILL.md"
    if not root.exists() or not root.is_dir():
        raise SkillPackageFormatError(f"skill package directory not found: {root}")
    if not skill_md.exists() or not skill_md.is_file():
        raise SkillPackageFormatError(f"missing SKILL.md: {root}")

    raw_markdown = skill_md.read_text(encoding="utf-8")
    frontmatter, body_markdown = _split_frontmatter(raw_markdown, skill_md)
    display_name = str(frontmatter.get("name", "") or "").strip()
    description = str(frontmatter.get("description", "") or "").strip()
    if not display_name:
        raise SkillPackageFormatError(f"SKILL.md missing frontmatter.name: {skill_md}")
    if not description:
        raise SkillPackageFormatError(f"SKILL.md missing frontmatter.description: {skill_md}")

    references_dir = _existing_dir(root / "references")
    scripts_dir = _existing_dir(root / "scripts")
    assets_dir = _existing_dir(root / "assets")
    metadata = {
        key: value
        for key, value in dict(frontmatter).items()
        if key not in {"name", "description"}
    }
    manifest = SkillPackageManifest(
        skill_name=skill_name,
        display_name=display_name,
        description=description,
        root_dir=str(root),
        skill_md_path=str(skill_md),
        references_dir=references_dir,
        scripts_dir=scripts_dir,
        assets_dir=assets_dir,
        metadata=metadata,
    )
    return SkillPackageDocument(
        manifest=manifest,
        raw_markdown=raw_markdown,
        body_markdown=body_markdown,
    )


def _split_frontmatter(raw_markdown: str, skill_md_path: Path) -> tuple[dict[str, Any], str]:
    if not raw_markdown.startswith("---\n"):
        raise SkillPackageFormatError(f"SKILL.md missing YAML frontmatter: {skill_md_path}")

    marker = "\n---\n"
    closing_index = raw_markdown.find(marker, 4)
    if closing_index < 0:
        raise SkillPackageFormatError(f"SKILL.md missing closing YAML frontmatter fence: {skill_md_path}")

    frontmatter_text = raw_markdown[4:closing_index]
    body_markdown = raw_markdown[closing_index + len(marker) :]
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise SkillPackageFormatError(f"invalid SKILL.md frontmatter: {skill_md_path}") from exc
    if not isinstance(frontmatter, dict):
        raise SkillPackageFormatError(f"SKILL.md frontmatter must be a mapping: {skill_md_path}")
    return dict(frontmatter), body_markdown


def _existing_dir(path: Path) -> str:
    if path.exists() and path.is_dir():
        return str(path.resolve())
    return ""
