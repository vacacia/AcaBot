"""配置加载: 从 config.yaml 读取并提供 get() 接口."""

from __future__ import annotations

import os
from typing import Any

import yaml


class Config:
    """配置容器.

    Args:
        data: 配置字典, 通常从 config.yaml 加载.
    """

    def __init__(self, data: dict[str, Any]):
        self._data = data

    @classmethod
    def from_file(cls, path: str = "config.yaml") -> Config:
        """从 yaml 文件加载配置. 文件不存在则返回空配置."""
        if os.path.exists(path):
            with open(path) as f:
                return cls(yaml.safe_load(f) or {})
        return cls({})

    def get(self, key: str, default: Any = None) -> Any:
        """获取顶层配置项."""
        return self._data.get(key, default)

    def get_plugin_config(self, plugin_name: str) -> dict[str, Any]:
        """获取指定插件的配置段.

        从 config.yaml 的 plugins.<plugin_name> 节读取.
        插件不存在则返回空 dict, 调用方无需做 None 检查.
        """
        plugins = self._data.get("plugins", {})
        return plugins.get(plugin_name, {})
