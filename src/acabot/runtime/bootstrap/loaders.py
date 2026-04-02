"""runtime.bootstrap.loaders 构造 prompt、session runtime 和 bootstrap defaults."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from acabot.config import Config

from ..computer import ComputerPolicy
from ..control.prompt_loader import (
    ChainedPromptLoader,
    FileSystemPromptLoader,
    PromptLoader,
    StaticPromptLoader,
)
from ..control.session_bundle_loader import SessionBundleLoader
from ..control.session_loader import SessionConfigLoader
from ..control.session_runtime import SessionRuntime
from ..subagents import SubagentCatalog
from .config import resolve_filesystem_path


@dataclass(frozen=True, slots=True)
class BootstrapDefaults:
    """Bootstrap 期间的种子默认值。不是 agent，不参与路由/UI/model target。"""

    prompt_ref: str = "prompt/default"
    computer_policy: ComputerPolicy | None = None


def build_bootstrap_defaults(
    config: Config,
    *,
    default_computer_policy: ComputerPolicy,
) -> BootstrapDefaults:
    """从 config 构造 bootstrap 种子默认值。"""

    _ = config
    return BootstrapDefaults(
        prompt_ref="prompt/default",
        computer_policy=default_computer_policy,
    )


def build_prompt_loader(
    config: Config,
    *,
    prompt_refs: set[str] | None = None,
    subagent_catalog: SubagentCatalog | None = None,
) -> PromptLoader:
    """构造 prompt loader（filesystem-only，无 inline）."""

    runtime_conf = dict(config.get("runtime", {}) or {})
    fs_conf = dict(runtime_conf.get("filesystem", {}) or {})
    subagent_prompts = _build_subagent_prompt_map(subagent_catalog)
    prompts_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="prompts_dir",
        default="prompts",
    )
    loaders: list[PromptLoader] = [
        FileSystemPromptLoader(prompts_dir),
    ]
    if subagent_prompts:
        loaders.append(StaticPromptLoader(subagent_prompts))
    return ChainedPromptLoader(loaders)


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
    """枚举当前 runtime 已知的 prompt_ref 集合（filesystem-only）."""

    runtime_conf = dict(config.get("runtime", {}) or {})
    fs_conf = dict(runtime_conf.get("filesystem", {}) or {})
    refs: set[str] = set()
    refs.update(str(prompt_ref or "").strip() for prompt_ref in set(prompt_refs or set()) if str(prompt_ref or "").strip())
    refs.update(_build_subagent_prompt_map(subagent_catalog).keys())
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
    model_target_ids: set[str] | None = None,
) -> SessionBundleLoader:
    """按当前配置构造 session bundle loader（始终构造，filesystem-only）."""

    runtime_conf = dict(config.get("runtime", {}) or {})
    fs_conf = dict(runtime_conf.get("filesystem", {}) or {})
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
        model_target_ids=model_target_ids,
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
    """构造 session-config 驱动的决策运行时（filesystem-only）."""

    runtime_conf = dict(config.get("runtime", {}) or {})
    fs_conf = dict(runtime_conf.get("filesystem", {}) or {})
    sessions_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="sessions_dir",
        default="sessions",
    )
    return SessionRuntime(SessionConfigLoader(config_root=sessions_dir))


__all__ = [
    "BootstrapDefaults",
    "build_bootstrap_defaults",
    "build_prompt_loader",
    "build_prompt_refs",
    "build_session_bundle_loader",
    "build_session_runtime",
]
