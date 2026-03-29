"""runtime.subagents.package 定义 subagent package 的标准数据对象."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class SubagentPackageFormatError(ValueError):
    """当前 subagent package 不满足约定格式."""


@dataclass(slots=True)
class SubagentPackageManifest:
    """一条 subagent package 的核心 metadata.

    Attributes:
        subagent_name (str): runtime 使用的 subagent 名字.
        scope (str): 当前 subagent 的来源范围, 例如 `project` 或 `user`.
        host_subagent_file_path (str): 当前 `SUBAGENT.md` 的宿主机绝对路径.
        description (str): 当前 subagent 的简短说明.
        tools (list[str]): 当前 subagent 允许使用的工具列表.
        model_target (str | None): 可选的模型目标 id.
        metadata (dict[str, Any]): 额外 frontmatter 字段.
    """

    subagent_name: str
    scope: str
    host_subagent_file_path: str
    description: str
    tools: list[str]
    model_target: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def host_subagent_root_path(self) -> str:
        """返回当前 subagent 根目录的宿主机绝对路径."""

        return str(Path(self.host_subagent_file_path).resolve().parent)

    @property
    def subagent_id(self) -> str:
        """返回当前 manifest 的稳定实体 id.

        `subagent_name` 表达的是逻辑调用名, 可以重复;
        控制面 / WebUI 需要一个按实际文件路径区分的稳定实体标识.
        """

        resolved_path = Path(self.host_subagent_file_path).expanduser().resolve()
        return f"{self.scope}:{resolved_path}"


@dataclass(slots=True)
class SubagentPackageDocument:
    """一条完整 subagent package 文档."""

    manifest: SubagentPackageManifest
    raw_markdown: str
    body_markdown: str


def parse_subagent_package(
    *,
    subagent_name: str,
    scope: str,
    root_dir: str | Path,
) -> SubagentPackageDocument:
    """从 subagent 目录解析出标准 package 文档.

    Args:
        subagent_name: 当前解析入口使用的 subagent 名字.
        scope: 当前 subagent 的来源范围.
        root_dir: 当前 subagent 根目录.

    Returns:
        SubagentPackageDocument: 解析后的 subagent 文档.
    """

    root = Path(root_dir).expanduser().resolve()
    subagent_md = root / "SUBAGENT.md"
    if not root.exists() or not root.is_dir():
        raise SubagentPackageFormatError(f"subagent package directory not found: {root}")
    if not subagent_md.exists() or not subagent_md.is_file():
        raise SubagentPackageFormatError(f"missing SUBAGENT.md: {root}")

    raw_markdown = subagent_md.read_text(encoding="utf-8")
    frontmatter, body_markdown = _split_frontmatter(raw_markdown, subagent_md)
    resolved_subagent_name = str(frontmatter.get("name", "") or "").strip() or subagent_name
    description = str(frontmatter.get("description", "") or "").strip()
    if not resolved_subagent_name:
        raise SubagentPackageFormatError(f"SUBAGENT.md missing frontmatter.name: {subagent_md}")
    if not description:
        raise SubagentPackageFormatError(f"SUBAGENT.md missing frontmatter.description: {subagent_md}")
    tools = _parse_tools(frontmatter.get("tools"), subagent_md)
    model_target = _parse_optional_model_target(frontmatter.get("model_target"))

    metadata = {
        key: value
        for key, value in dict(frontmatter).items()
        if key not in {"name", "description", "tools", "model_target"}
    }
    manifest = SubagentPackageManifest(
        subagent_name=resolved_subagent_name,
        scope=scope,
        host_subagent_file_path=str(subagent_md),
        description=description,
        tools=tools,
        model_target=model_target,
        metadata=metadata,
    )
    return SubagentPackageDocument(
        manifest=manifest,
        raw_markdown=raw_markdown,
        body_markdown=body_markdown,
    )


def _split_frontmatter(raw_markdown: str, subagent_md_path: Path) -> tuple[dict[str, Any], str]:
    """拆出 frontmatter 和正文."""

    if not raw_markdown.startswith("---\n"):
        raise SubagentPackageFormatError(f"SUBAGENT.md missing YAML frontmatter: {subagent_md_path}")

    marker = "\n---\n"
    closing_index = raw_markdown.find(marker, 4)
    if closing_index < 0:
        raise SubagentPackageFormatError(
            f"SUBAGENT.md missing closing YAML frontmatter fence: {subagent_md_path}"
        )

    frontmatter_text = raw_markdown[4:closing_index]
    body_markdown = raw_markdown[closing_index + len(marker) :]
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise SubagentPackageFormatError(f"invalid SUBAGENT.md frontmatter: {subagent_md_path}") from exc
    if not isinstance(frontmatter, dict):
        raise SubagentPackageFormatError(
            f"SUBAGENT.md frontmatter must be a mapping: {subagent_md_path}"
        )
    return dict(frontmatter), body_markdown


def _parse_tools(raw_tools: object, subagent_md_path: Path) -> list[str]:
    """把 tools frontmatter 收成去重后的工具列表."""

    if raw_tools in (None, ""):
        raise SubagentPackageFormatError(f"SUBAGENT.md missing frontmatter.tools: {subagent_md_path}")
    if not isinstance(raw_tools, list):
        raise SubagentPackageFormatError(f"SUBAGENT.md frontmatter.tools must be a list: {subagent_md_path}")

    tools: list[str] = []
    seen: set[str] = set()
    for item in raw_tools:
        tool_name = str(item or "").strip()
        if not tool_name or tool_name in seen:
            continue
        tools.append(tool_name)
        seen.add(tool_name)
    if not tools:
        raise SubagentPackageFormatError(f"SUBAGENT.md frontmatter.tools must not be empty: {subagent_md_path}")
    return tools


def _parse_optional_model_target(raw_model_target: object) -> str | None:
    """把可选 model_target 收成字符串."""

    if raw_model_target in (None, ""):
        return None
    return str(raw_model_target)
