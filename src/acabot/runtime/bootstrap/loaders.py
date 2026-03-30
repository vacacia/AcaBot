"""runtime.bootstrap.loaders 构造前台 agent、prompt 和 session runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acabot.config import Config

from ..computer import ComputerPolicy, parse_computer_policy
from ..contracts import ResolvedAgent
from ..control.prompt_loader import (
    ChainedPromptLoader,
    FileSystemPromptLoader,
    PromptLoader,
    StaticPromptLoader,
)
from ..control.session_bundle_loader import SessionBundleLoader
from ..control.session_loader import ConfigBackedSessionConfigLoader, SessionConfigLoader
from ..control.session_runtime import SessionRuntime
from ..subagents import SubagentCatalog
from .config import resolve_filesystem_path


def _normalize_string_list(raw_items: object) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for item in list(raw_items or []):
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        items.append(text)
        seen.add(text)
    return items


def _filesystem_session_storage_enabled(fs_conf: dict[str, object]) -> bool:
    """是否显式启用了 session bundle 文件真源."""

    return bool(fs_conf.get("enabled", False)) and "sessions_dir" in fs_conf


def build_default_frontstage_agent(
    config: Config,
    *,
    default_computer_policy: ComputerPolicy,
) -> ResolvedAgent:
    """从当前配置构造 inline 模式下的默认前台 agent."""

    runtime_conf = dict(config.get("runtime", {}) or {})
    agent_conf = dict(config.get("agent", {}) or {})
    agent_id = str(runtime_conf.get("default_agent_id", "default") or "default")
    prompt_ref = str(runtime_conf.get("default_prompt_ref", "prompt/default") or "prompt/default")
    merged_config: dict[str, Any] = dict(agent_conf)
    for key in ("max_tool_rounds", "image_caption", "context_management"):
        if key in runtime_conf:
            merged_config[key] = runtime_conf[key]
    return ResolvedAgent(
        agent_id=agent_id,
        name=str(runtime_conf.get("default_agent_name", agent_id) or agent_id),
        prompt_ref=prompt_ref,
        enabled_tools=_normalize_string_list(runtime_conf.get("enabled_tools", [])),
        skills=_normalize_string_list(runtime_conf.get("skills", [])),
        visible_subagents=_normalize_string_list(runtime_conf.get("visible_subagents", [])),
        computer_policy=parse_computer_policy(
            runtime_conf.get("computer"),
            defaults=default_computer_policy,
        ),
        config=merged_config,
    )


def build_prompt_map(
    config: Config,
    *,
    prompt_refs: set[str] | None = None,
) -> dict[str, str]:
    """构造 inline prompt 映射."""

    runtime_conf = dict(config.get("runtime", {}) or {})
    agent_conf = dict(config.get("agent", {}) or {})
    prompts = {
        str(prompt_ref or "").strip(): str(prompt_text or "")
        for prompt_ref, prompt_text in dict(runtime_conf.get("prompts", {}) or {}).items()
        if str(prompt_ref or "").strip()
    }
    default_prompt_text = str(agent_conf.get("system_prompt", "") or "")
    for prompt_ref in set(prompt_refs or set()):
        prompts.setdefault(prompt_ref, default_prompt_text)
    return prompts


def build_prompt_loader(
    config: Config,
    *,
    prompt_refs: set[str] | None = None,
    subagent_catalog: SubagentCatalog | None = None,
) -> PromptLoader:
    """构造 prompt loader."""

    runtime_conf = dict(config.get("runtime", {}) or {})
    fs_conf = dict(runtime_conf.get("filesystem", {}) or {})
    prompt_map = build_prompt_map(config, prompt_refs=prompt_refs)
    prompt_map.update(_build_subagent_prompt_map(subagent_catalog))
    static_loader = StaticPromptLoader(prompt_map)
    if not bool(fs_conf.get("enabled", False)):
        return static_loader
    prompts_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="prompts_dir",
        default="prompts",
    )
    return ChainedPromptLoader([
        FileSystemPromptLoader(prompts_dir),
        static_loader,
    ])


def _build_subagent_prompt_map(subagent_catalog: SubagentCatalog | None) -> dict[str, str]:
    """构造 subagent prompt 映射."""

    if subagent_catalog is None:
        return {}

    prompts: dict[str, str] = {}
    seen: set[str] = set()
    for manifest in subagent_catalog.list_all():
        subagent_name = manifest.subagent_name
        if subagent_name in seen:
            continue
        prompts[f"subagent/{subagent_name}"] = subagent_catalog.read(subagent_name).body_markdown
        seen.add(subagent_name)
    return prompts


def build_prompt_refs(
    config: Config,
    *,
    prompt_refs: set[str] | None = None,
    subagent_catalog: SubagentCatalog | None = None,
) -> set[str]:
    """枚举当前 runtime 已知的 prompt_ref 集合."""

    runtime_conf = dict(config.get("runtime", {}) or {})
    fs_conf = dict(runtime_conf.get("filesystem", {}) or {})
    refs = {
        str(prompt_ref or "").strip()
        for prompt_ref in dict(runtime_conf.get("prompts", {}) or {})
        if str(prompt_ref or "").strip()
    }
    refs.update(str(prompt_ref or "").strip() for prompt_ref in set(prompt_refs or set()) if str(prompt_ref or "").strip())
    refs.update(_build_subagent_prompt_map(subagent_catalog).keys())
    if not bool(fs_conf.get("enabled", False)):
        return refs
    prompts_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="prompts_dir",
        default="prompts",
    )
    if not prompts_dir.exists():
        return refs
    for path in sorted(prompts_dir.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".txt", ".prompt"}:
            continue
        refs.add(_prompt_ref_from_path(prompts_dir, path))
    return refs


def build_session_bundle_loader(
    config: Config,
    *,
    prompt_refs: set[str],
    tool_names: set[str],
    skill_names: set[str],
    subagent_names: set[str],
) -> SessionBundleLoader | None:
    """按当前配置构造 session bundle loader.

    当 runtime 还没有启用 filesystem session 真源时返回 `None`.
    """

    runtime_conf = dict(config.get("runtime", {}) or {})
    fs_conf = dict(runtime_conf.get("filesystem", {}) or {})
    if not _filesystem_session_storage_enabled(fs_conf):
        return None
    sessions_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="sessions_dir",
        default="sessions",
    )
    return SessionBundleLoader(
        config_root=sessions_dir,
        prompt_refs=prompt_refs,
        tool_names=tool_names,
        skill_names=skill_names,
        subagent_names=subagent_names,
    )


def _prompt_ref_from_path(prompts_dir: Path, path: Path) -> str:
    """把 prompt 文件路径映射回 prompt_ref."""

    relative = path.relative_to(prompts_dir)
    if relative.name.startswith("index."):
        normalized = relative.parent
    else:
        normalized = relative.with_suffix("")
    return f"prompt/{normalized.as_posix()}".rstrip("/")


def build_session_runtime(config: Config) -> SessionRuntime:
    """构造 session-config 驱动的决策运行时."""

    runtime_conf = dict(config.get("runtime", {}) or {})
    fs_conf = dict(runtime_conf.get("filesystem", {}) or {})
    if _filesystem_session_storage_enabled(fs_conf):
        sessions_dir = resolve_filesystem_path(
            config,
            fs_conf,
            key="sessions_dir",
            default="sessions",
        )
        return SessionRuntime(SessionConfigLoader(config_root=sessions_dir))
    return SessionRuntime(ConfigBackedSessionConfigLoader(config))


__all__ = [
    "build_default_frontstage_agent",
    "build_prompt_loader",
    "build_prompt_map",
    "build_prompt_refs",
    "build_session_bundle_loader",
    "build_session_runtime",
]
