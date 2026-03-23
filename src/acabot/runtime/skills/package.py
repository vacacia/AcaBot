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
    """一条 skill package 的核心 metadata.

    Attributes:
        skill_name (str): 模型和 runtime 使用的 skill 名字.
        scope (str): 当前 skill 的来源范围, 例如 `project` 或 `user`.
        description (str): 当前 skill 的简短说明.
        host_skill_file_path (str): 当前 `SKILL.md` 的宿主机绝对路径.
        argument_hint (str): 可选的参数提示文本.
        disable_model_invocation (bool): 是否禁用模型主动调用这个 skill.
        metadata (dict[str, Any]): 额外 frontmatter 字段.
    """

    skill_name: str
    scope: str
    description: str
    host_skill_file_path: str
    argument_hint: str = ""
    disable_model_invocation: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def host_skill_root_path(self) -> str:
        """返回当前 skill 根目录的宿主机绝对路径."""

        return str(Path(self.host_skill_file_path).resolve().parent)

    @property
    def display_name(self) -> str:
        """返回给控制面展示的标题.

        优先取 frontmatter.name, 没有就回退成 `skill_name`.
        """

        value = str(self.metadata.get("display_name", "") or "").strip()
        if value:
            return value
        return self.skill_name

    @property
    def has_references(self) -> bool:
        """判断 skill 根目录下是否存在 `references/`."""

        return (Path(self.host_skill_root_path) / "references").is_dir()

    @property
    def has_scripts(self) -> bool:
        """判断 skill 根目录下是否存在 `scripts/`."""

        return (Path(self.host_skill_root_path) / "scripts").is_dir()

    @property
    def has_assets(self) -> bool:
        """判断 skill 根目录下是否存在 `assets/`."""

        return (Path(self.host_skill_root_path) / "assets").is_dir()


@dataclass(slots=True)
class SkillPackageDocument:
    """一条完整 skill package 文档."""

    manifest: SkillPackageManifest
    raw_markdown: str
    body_markdown: str


def parse_skill_package(
    *,
    skill_name: str,
    scope: str,
    root_dir: str | Path,
) -> SkillPackageDocument:
    """从 skill 目录解析出标准 package 文档.

    Args:
        skill_name: 模型和 runtime 使用的 skill 名字.
        scope: 当前 skill 的来源范围.
        root_dir: 当前 skill 根目录.

    Returns:
        SkillPackageDocument: 解析后的 skill 文档.
    """

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
    argument_hint = str(frontmatter.get("argument-hint", "") or "").strip()
    disable_model_invocation = bool(frontmatter.get("disable-model-invocation", False))
    if not description:
        raise SkillPackageFormatError(f"SKILL.md missing frontmatter.description: {skill_md}")

    metadata = {
        key: value
        for key, value in dict(frontmatter).items()
        if key not in {"name", "description", "argument-hint", "disable-model-invocation"}
    }
    if display_name:
        metadata["display_name"] = display_name
    manifest = SkillPackageManifest(
        skill_name=skill_name,
        scope=scope,
        description=description,
        host_skill_file_path=str(skill_md),
        argument_hint=argument_hint,
        disable_model_invocation=disable_model_invocation,
        metadata=metadata,
    )
    return SkillPackageDocument(
        manifest=manifest,
        raw_markdown=raw_markdown,
        body_markdown=body_markdown,
    )


def _split_frontmatter(raw_markdown: str, skill_md_path: Path) -> tuple[dict[str, Any], str]:
    """拆出 frontmatter 和正文."""

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
