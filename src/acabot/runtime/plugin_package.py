"""runtime.plugin_package 定义 PluginPackage 数据对象和 PackageCatalog.

PackageCatalog 负责扫描 extensions/plugins/ 下的目录,
解析 plugin.yaml 构建 PluginPackage 集合.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("acabot.runtime.plugin")


@dataclass(frozen=True)
class PluginPackage:
    """一个已安装的插件包.

    Attributes:
        plugin_id (str): 稳定的插件身份标识, 如 "ops_control".
        display_name (str): WebUI 展示名.
        package_root (Path): 插件包根目录, 如 extensions/plugins/ops_control/.
        entrypoint (str): 导入路径, 如 "plugins.ops_control:Plugin".
        version (str): 版本号.
        default_config (dict[str, Any]): 默认配置.
        config_schema (dict[str, Any] | None): JSON Schema, WebUI 用它生成表单.
    """

    plugin_id: str
    display_name: str
    package_root: Path
    entrypoint: str
    version: str = "1"
    default_config: dict[str, Any] = field(default_factory=dict)
    config_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class PackageScanError:
    """扫描单个插件包时的错误.

    Attributes:
        plugin_id (str): 从目录名推断的 plugin_id.
        error (str): 错误描述.
    """

    plugin_id: str
    error: str


class PackageCatalog:
    """扫描 extensions/plugins/ 下所有 plugin.yaml, 构建 PluginPackage 集合.

    Attributes:
        _extensions_plugins_dir (Path): extensions/plugins/ 目录路径.
        _packages (dict[str, PluginPackage]): 最近一次 scan 的缓存.
    """

    def __init__(self, extensions_plugins_dir: Path) -> None:
        """初始化 PackageCatalog.

        Args:
            extensions_plugins_dir: extensions/plugins/ 目录路径.
        """

        self._extensions_plugins_dir = extensions_plugins_dir
        self._packages: dict[str, PluginPackage] = {}

    def scan(self) -> tuple[dict[str, PluginPackage], list[PackageScanError]]:
        """扫描目录, 解析所有 plugin.yaml.

        Returns:
            (packages, errors) 元组.
            packages 按 plugin_id 索引, errors 包含解析失败的项.
        """

        packages: dict[str, PluginPackage] = {}
        errors: list[PackageScanError] = []

        if not self._extensions_plugins_dir.is_dir():
            self._packages = packages
            return packages, errors

        for child in sorted(self._extensions_plugins_dir.iterdir()):
            if not child.is_dir():
                continue
            dir_name = child.name
            manifest_path = child / "plugin.yaml"
            if not manifest_path.is_file():
                # 没有 plugin.yaml 的目录静默跳过
                continue

            try:
                raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    errors.append(PackageScanError(
                        plugin_id=dir_name,
                        error="plugin.yaml root is not a mapping",
                    ))
                    continue

                plugin_section = raw.get("plugin", {})
                if not isinstance(plugin_section, dict):
                    errors.append(PackageScanError(
                        plugin_id=dir_name,
                        error="plugin.yaml 'plugin' section is not a mapping",
                    ))
                    continue

                declared_id = str(plugin_section.get("plugin_id", "") or "").strip()
                if declared_id and declared_id != dir_name:
                    errors.append(PackageScanError(
                        plugin_id=dir_name,
                        error=f"plugin_id '{declared_id}' does not match directory name '{dir_name}'",
                    ))
                    continue

                plugin_id = dir_name
                display_name = str(plugin_section.get("display_name", "") or "").strip() or plugin_id
                entrypoint = str(plugin_section.get("entrypoint", "") or "").strip()
                if not entrypoint:
                    entrypoint = f"plugins.{plugin_id}:Plugin"
                version = str(plugin_section.get("version", "1") or "1")
                default_config = dict(plugin_section.get("default_config", {}) or {})
                config_schema_raw = plugin_section.get("config_schema")
                config_schema = dict(config_schema_raw) if isinstance(config_schema_raw, dict) else None

                packages[plugin_id] = PluginPackage(
                    plugin_id=plugin_id,
                    display_name=display_name,
                    package_root=child,
                    entrypoint=entrypoint,
                    version=version,
                    default_config=default_config,
                    config_schema=config_schema,
                )
            except Exception as exc:
                errors.append(PackageScanError(
                    plugin_id=dir_name,
                    error=str(exc),
                ))

        self._packages = packages
        return packages, errors

    def get(self, plugin_id: str) -> PluginPackage | None:
        """从最新缓存读取指定 plugin_id 的包.

        Args:
            plugin_id: 插件 ID.

        Returns:
            PluginPackage | None: 找到时返回包对象, 否则 None.
        """

        return self._packages.get(plugin_id)


__all__ = [
    "PackageCatalog",
    "PackageScanError",
    "PluginPackage",
]
