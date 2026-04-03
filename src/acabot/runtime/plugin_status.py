"""runtime.plugin_status 定义 PluginStatus 数据对象和 StatusStore.

StatusStore 负责读写 runtime_data/plugins/ 下的插件状态观察结果.
Reconciler 是唯一写入方, API 和 WebUI 只读.
"""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger("acabot.runtime.plugin")


PluginPhase = Literal["disabled", "loaded", "failed", "uninstalled"]


@dataclass(slots=True)
class PluginStatus:
    """Reconciler 的输出, 持久化的观察结果.

    不参与决策, 仅用于展示和诊断.

    Attributes:
        plugin_id (str): 插件 ID.
        phase (PluginPhase): 当前阶段.
        load_error (str): 加载失败时的错误信息.
        registered_tools (list[str]): 已注册的工具名列表.
        registered_hooks (list[str]): 已注册的 hook 描述列表, 如 "pre_agent:OpsCommandHook".
        updated_at (str): 最后更新时间, ISO 8601 格式.
    """

    plugin_id: str
    phase: PluginPhase
    load_error: str = ""
    registered_tools: list[str] = field(default_factory=list)
    registered_hooks: list[str] = field(default_factory=list)
    updated_at: str = ""


class StatusStore:
    """读写 runtime_data/plugins/ 下的 PluginStatus.

    磁盘格式: runtime_data/plugins/<plugin_id>/status.json.
    delete() 只删 status.json, 不删整个目录 (保护插件 data/).

    Attributes:
        _plugins_data_dir (Path): runtime_data/plugins/ 目录路径.
    """

    def __init__(self, plugins_data_dir: Path) -> None:
        """初始化 StatusStore.

        Args:
            plugins_data_dir: runtime_data/plugins/ 目录路径.
        """

        self._plugins_data_dir = plugins_data_dir

    def load_all(self) -> dict[str, PluginStatus]:
        """加载所有 PluginStatus.

        单个坏文件 warning log + 跳过.

        Returns:
            按 plugin_id 索引的 status 字典.
        """

        statuses: dict[str, PluginStatus] = {}

        if not self._plugins_data_dir.is_dir():
            return statuses

        for child in sorted(self._plugins_data_dir.iterdir()):
            if not child.is_dir():
                continue
            plugin_id = child.name
            status_path = child / "status.json"
            if not status_path.is_file():
                continue

            try:
                raw = json.loads(status_path.read_text(encoding="utf-8"))
                statuses[plugin_id] = self._from_dict(plugin_id, raw)
            except Exception:
                logger.warning(
                    "Failed to load plugin status, skipping: plugin_id=%s path=%s",
                    plugin_id,
                    status_path,
                )

        return statuses

    def load(self, plugin_id: str) -> PluginStatus | None:
        """加载单个 PluginStatus.

        Args:
            plugin_id: 插件 ID.

        Returns:
            PluginStatus | None: 找到且解析成功时返回, 否则 None.
        """

        status_path = self._plugins_data_dir / plugin_id / "status.json"
        if not status_path.is_file():
            return None
        try:
            raw = json.loads(status_path.read_text(encoding="utf-8"))
            return self._from_dict(plugin_id, raw)
        except Exception:
            logger.warning(
                "Failed to load plugin status: plugin_id=%s path=%s",
                plugin_id,
                status_path,
            )
            return None

    def save(self, status: PluginStatus) -> None:
        """原子写入 PluginStatus 到磁盘.

        使用 NamedTemporaryFile + Path.replace() 实现原子写.
        自动创建子目录.

        Args:
            status: 要保存的 PluginStatus.
        """

        plugin_dir = self._plugins_data_dir / status.plugin_id
        plugin_dir.mkdir(parents=True, exist_ok=True)
        target_path = plugin_dir / "status.json"

        payload = {
            "plugin_id": status.plugin_id,
            "phase": status.phase,
            "load_error": status.load_error,
            "registered_tools": list(status.registered_tools),
            "registered_hooks": list(status.registered_hooks),
            "updated_at": status.updated_at,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)

        fd = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json.tmp",
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
        """删除指定插件的 status.json.

        只删 status.json, 不删目录 (保护 data/ 等插件私有数据).

        Args:
            plugin_id: 插件 ID.
        """

        status_path = self._plugins_data_dir / plugin_id / "status.json"
        if status_path.is_file():
            status_path.unlink()

    @staticmethod
    def _from_dict(plugin_id: str, raw: dict) -> PluginStatus:
        """从字典构造 PluginStatus.

        Args:
            plugin_id: 期望的 plugin_id.
            raw: JSON 反序列化后的字典.

        Returns:
            PluginStatus 对象.
        """

        return PluginStatus(
            plugin_id=plugin_id,
            phase=raw.get("phase", "disabled"),
            load_error=str(raw.get("load_error", "") or ""),
            registered_tools=list(raw.get("registered_tools", []) or []),
            registered_hooks=list(raw.get("registered_hooks", []) or []),
            updated_at=str(raw.get("updated_at", "") or ""),
        )


__all__ = [
    "PluginPhase",
    "PluginStatus",
    "StatusStore",
]
