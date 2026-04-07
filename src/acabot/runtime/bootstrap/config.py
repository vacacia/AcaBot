"""runtime.bootstrap.config 定义 bootstrap 期使用的路径辅助函数.

这里主要负责两类事情:

- 把配置里的相对路径解析成绝对路径
- 给 bootstrap 期需要的默认目录约定提供统一 helper
"""

from __future__ import annotations

from pathlib import Path

from acabot.config import Config

from ..skills.loader import SkillDiscoveryRoot
from ..subagents.loader import SubagentDiscoveryRoot


def resolve_filesystem_path(
    config: Config,
    fs_conf: dict[str, object],
    *,
    key: str,
    default: str,
) -> Path:
    """把 filesystem 相对路径解析到配置基目录.

    Args:
        config: 当前 runtime 配置.
        fs_conf: `runtime.filesystem` 配置块.
        key: 目标字段名.
        default: 缺省路径.

    Returns:
        Path: 解析后的绝对路径.
    """

    base_dir = Path(str(fs_conf.get("base_dir", ".") or "."))
    if not base_dir.is_absolute():
        base_dir = config.resolve_path(base_dir)
    raw_value = Path(str(fs_conf.get(key, default) or default))
    if raw_value.is_absolute():
        return raw_value
    return (base_dir / raw_value).resolve()


def resolve_runtime_path(config: Config, raw_path: object) -> Path:
    """把 runtime 相关路径解析到 `runtime.runtime_root` 下.

    Args:
        config: 当前 runtime 配置.
        raw_path: 原始路径值.

    Returns:
        Path: 解析后的绝对路径.
    """

    runtime_conf = config.get("runtime", {})
    runtime_root = Path(str(runtime_conf.get("runtime_root", "runtime_data") or "runtime_data"))
    if not runtime_root.is_absolute():
        runtime_root = config.resolve_path(runtime_root)
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    return (runtime_root / path).resolve()


def resolve_skill_catalog_dirs(
    config: Config,
    fs_conf: dict[str, object],
    *,
    defaults: list[str],
) -> list[SkillDiscoveryRoot]:
    """解析 skill catalog 扫描根目录列表.

    `skill_catalog_dirs` 现在表达的是“要扫描哪些 skill 根目录”。

    规则是:

    - 相对路径算 `project`
    - `~` 路径和根目录绝对路径算 `user`
    - 如果配置没写, 就使用传进来的默认常用目录列表

    Args:
        config: 当前 runtime 配置.
        fs_conf: `runtime.filesystem` 配置块.
        defaults: 默认扫描目录列表.

    Returns:
        list[SkillDiscoveryRoot]: 去重后的扫描根列表.
    """

    raw_values = fs_conf.get("skill_catalog_dirs")
    items = _normalize_catalog_dir_values(raw_values, defaults=defaults)
    project_root = Path(str(fs_conf.get("base_dir", ".") or "."))
    if not project_root.is_absolute():
        project_root = config.resolve_path(project_root)

    resolved: list[SkillDiscoveryRoot] = []
    seen: set[tuple[str, str]] = set()
    for raw in items:
        scope = _scope_for_catalog_dir(raw)
        path = _resolve_catalog_dir_path(raw=raw, base_dir=project_root)
        root = SkillDiscoveryRoot(host_root_path=str(path), scope=scope)
        key = (str(root.path), root.scope)
        if key in seen:
            continue
        resolved.append(root)
        seen.add(key)
    return resolved


def resolve_subagent_catalog_dirs(
    config: Config,
    fs_conf: dict[str, object],
    *,
    defaults: list[str],
) -> list[SubagentDiscoveryRoot]:
    """解析 subagent catalog 扫描根目录列表.

    Args:
        config: 当前 runtime 配置.
        fs_conf: `runtime.filesystem` 配置块.
        defaults: 默认扫描目录列表.

    Returns:
        list[SubagentDiscoveryRoot]: 去重后的扫描根列表.
    """

    raw_values = fs_conf.get("subagent_catalog_dirs")
    items = _normalize_catalog_dir_values(raw_values, defaults=defaults)
    project_root = Path(str(fs_conf.get("base_dir", ".") or "."))
    if not project_root.is_absolute():
        project_root = config.resolve_path(project_root)

    resolved: list[SubagentDiscoveryRoot] = []
    seen: set[tuple[str, str]] = set()
    for raw in items:
        scope = _scope_for_catalog_dir(raw)
        path = _resolve_catalog_dir_path(raw=raw, base_dir=project_root)
        root = SubagentDiscoveryRoot(host_root_path=str(path), scope=scope)
        key = (str(root.path), root.scope)
        if key in seen:
            continue
        resolved.append(root)
        seen.add(key)
    return resolved


def _normalize_catalog_dir_values(raw_values: object, *, defaults: list[str]) -> list[str]:
    """把配置里的 catalog 根目录配置收成字符串列表."""

    if raw_values in (None, ""):
        values = list(defaults)
    elif isinstance(raw_values, str):
        values = [raw_values]
    else:
        values = [str(item) for item in list(raw_values or [])]

    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        normalized.append(text)
    return normalized


def _scope_for_catalog_dir(raw_value: str) -> str:
    """按配置写法推断 catalog 根目录 scope."""

    if raw_value.startswith("~"):
        return "user"
    if Path(raw_value).is_absolute():
        return "user"
    return "project"


def _resolve_catalog_dir_path(*, raw: str, base_dir: Path) -> Path:
    """把 catalog 扫描目录解析成宿主机绝对路径."""

    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def optional_str(value: object) -> str | None:
    """把可空值转成可选字符串.

    Args:
        value: 原始值.

    Returns:
        str | None: 空值返回 `None`, 否则返回字符串.
    """

    if value in (None, ""):
        return None
    return str(value)


def get_persistence_sqlite_path(config: Config) -> str | None:
    """读取 persistence sqlite 路径.

    Args:
        config: 当前 runtime 配置.

    Returns:
        str | None: 解析后的 sqlite 路径. 未声明时返回 `None`.
    """

    runtime_conf = config.get("runtime", {})
    persistence_conf = runtime_conf.get("persistence", {})
    sqlite_path = persistence_conf.get("sqlite_path")
    if sqlite_path in (None, ""):
        return None
    return str(resolve_runtime_path(config, sqlite_path))


__all__ = [
    "get_persistence_sqlite_path",
    "optional_str",
    "resolve_filesystem_path",
    "resolve_runtime_path",
    "resolve_skill_catalog_dirs",
    "resolve_subagent_catalog_dirs",
]
