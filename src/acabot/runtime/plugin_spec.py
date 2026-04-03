"""runtime.plugin_spec 定义 PluginSpec 数据对象和 SpecStore.

SpecStore 负责读写 runtime_config/plugins/ 下的操作者意图配置.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("acabot.runtime.plugin")


@dataclass(frozen=True)
class PluginSpec:
    """操作者意图.

    enabled 控制是否启用, config 只存覆盖项.
    缺失的配置值由 PluginPackage.default_config 提供.

    Attributes:
        plugin_id (str): 插件 ID.
        enabled (bool): 是否启用.
        config (dict[str, Any]): 操作者配置覆盖.
    """

    plugin_id: str
    enabled: bool = False
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SpecParseError:
    """解析单个 PluginSpec 时的错误.

    Attributes:
        plugin_id (str): 插件 ID.
        error (str): 错误描述.
    """

    plugin_id: str
    error: str


class SpecStore:
    """读写 runtime_config/plugins/ 下的 PluginSpec.

    磁盘格式: runtime_config/plugins/<plugin_id>/plugin.yaml
    顶层 key: plugin (元信息) + config (配置覆盖).

    Attributes:
        _plugins_config_dir (Path): runtime_config/plugins/ 目录路径.
    """

    def __init__(self, plugins_config_dir: Path) -> None:
        """初始化 SpecStore.

        Args:
            plugins_config_dir: runtime_config/plugins/ 目录路径.
        """

        self._plugins_config_dir = plugins_config_dir

    def load_all(self) -> tuple[dict[str, PluginSpec], list[SpecParseError]]:
        """加载所有 PluginSpec.

        Returns:
            (specs, errors) 元组.
            specs 按 plugin_id 索引, errors 包含解析失败的项.
        """

        specs: dict[str, PluginSpec] = {}
        errors: list[SpecParseError] = []

        if not self._plugins_config_dir.is_dir():
            return specs, errors

        for child in sorted(self._plugins_config_dir.iterdir()):
            if not child.is_dir():
                continue
            plugin_id = child.name
            spec_path = child / "plugin.yaml"
            if not spec_path.is_file():
                continue

            try:
                spec = self._parse_spec_file(plugin_id, spec_path)
                specs[plugin_id] = spec
            except Exception as exc:
                errors.append(SpecParseError(plugin_id=plugin_id, error=str(exc)))

        return specs, errors

    def load(self, plugin_id: str) -> PluginSpec | None:
        """加载单个 PluginSpec.

        Args:
            plugin_id: 插件 ID.

        Returns:
            PluginSpec | None: 找到且解析成功时返回, 否则 None.
        """

        spec_path = self._plugins_config_dir / plugin_id / "plugin.yaml"
        if not spec_path.is_file():
            return None
        try:
            return self._parse_spec_file(plugin_id, spec_path)
        except Exception:
            logger.exception("Failed to parse spec for plugin '%s'", plugin_id)
            return None

    def save(self, spec: PluginSpec) -> None:
        """原子写入 PluginSpec 到磁盘.

        使用 NamedTemporaryFile + Path.replace() 实现原子写.
        自动创建子目录.

        Args:
            spec: 要保存的 PluginSpec.
        """

        plugin_dir = self._plugins_config_dir / spec.plugin_id
        plugin_dir.mkdir(parents=True, exist_ok=True)
        target_path = plugin_dir / "plugin.yaml"

        content = {
            "plugin": {
                "plugin_id": spec.plugin_id,
                "enabled": spec.enabled,
            },
            "config": dict(spec.config),
        }
        text = yaml.dump(content, default_flow_style=False, allow_unicode=True)

        # 原子写: 先写临时文件再 rename
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml.tmp",
            dir=str(plugin_dir),
            delete=False,
            encoding="utf-8",
        )
        try:
            fd.write(text)
            fd.flush()
            fd.close()
            Path(fd.name).replace(target_path)
        except Exception:
            Path(fd.name).unlink(missing_ok=True)
            raise

    def delete(self, plugin_id: str) -> None:
        """删除指定插件的 spec 文件和空目录.

        Args:
            plugin_id: 插件 ID.
        """

        plugin_dir = self._plugins_config_dir / plugin_id
        spec_path = plugin_dir / "plugin.yaml"
        if spec_path.is_file():
            spec_path.unlink()
        # 只在目录为空时删除目录
        if plugin_dir.is_dir():
            try:
                plugin_dir.rmdir()
            except OSError:
                pass  # 目录非空, 保留

    @staticmethod
    def _parse_spec_file(plugin_id: str, spec_path: Path) -> PluginSpec:
        """解析单个 spec 文件.

        Args:
            plugin_id: 期望的插件 ID.
            spec_path: spec 文件路径.

        Returns:
            PluginSpec 对象.

        Raises:
            ValueError: 文件格式不正确.
        """

        raw = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("plugin.yaml root is not a mapping")

        plugin_section = raw.get("plugin", {})
        if not isinstance(plugin_section, dict):
            raise ValueError("'plugin' section is not a mapping")

        declared_id = str(plugin_section.get("plugin_id", "") or "").strip()
        if declared_id and declared_id != plugin_id:
            raise ValueError(
                f"plugin_id '{declared_id}' does not match directory '{plugin_id}'"
            )

        enabled = bool(plugin_section.get("enabled", False))
        config_section = raw.get("config", {})
        config = dict(config_section) if isinstance(config_section, dict) else {}

        return PluginSpec(
            plugin_id=plugin_id,
            enabled=enabled,
            config=config,
        )


__all__ = [
    "PluginSpec",
    "SpecParseError",
    "SpecStore",
]
