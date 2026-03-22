"""runtime.bootstrap.config 定义 bootstrap 期使用的路径辅助函数."""

from __future__ import annotations

from pathlib import Path

from acabot.config import Config


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
    runtime_root = Path(str(runtime_conf.get("runtime_root", ".acabot-runtime") or ".acabot-runtime"))
    if not runtime_root.is_absolute():
        runtime_root = config.resolve_path(runtime_root)
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    return (runtime_root / path).resolve()


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
]
