"""配置加载: 从 config.yaml 读取并提供最小读写接口."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml


class Config:
    """配置容器.

    Args:
        data: 配置字典, 通常从 config.yaml 加载.
    """

    def __init__(self, data: dict[str, Any], *, path: str | None = None):
        self._data = data
        self.path = path

    @classmethod
    def from_file(cls, path: str = "config.yaml") -> Config:
        """从 yaml 文件加载配置. 文件不存在则返回空配置."""
        if os.path.exists(path):
            with open(path) as f:
                return cls(yaml.safe_load(f) or {}, path=path)
        return cls({}, path=path)

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

    def to_dict(self) -> dict[str, Any]:
        """返回一份当前配置的浅拷贝."""

        return dict(self._data)

    def replace(self, data: dict[str, Any]) -> None:
        """用新的配置字典替换当前内容."""

        self._data = dict(data)

    def save(self, *, path: str | None = None) -> None:
        """把当前配置原子写回到 YAML 文件."""

        target = Path(path or self.path or "config.yaml")
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(target.parent),
            delete=False,
            suffix=target.suffix or ".yaml",
        ) as handle:
            yaml.safe_dump(
                self._data,
                handle,
                allow_unicode=True,
                sort_keys=False,
            )
            tmp_path = Path(handle.name)
        tmp_path.replace(target)
        self.path = str(target)

    def reload_from_file(self, path: str | None = None) -> None:
        """从磁盘重新加载当前配置对象."""

        target = Path(path or self.path or "config.yaml")
        self.path = str(target)
        if not target.exists():
            self._data = {}
            return
        self._data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
