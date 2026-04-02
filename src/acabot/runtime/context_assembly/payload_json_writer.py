"""runtime.context_assembly.payload_json_writer 负责落盘最终模型 payload.

组件关系:

    ModelAgentRuntime
        |
        v
    PayloadJsonWriter
        |
        v
    debug/model_payloads/*.json

这一层不决定上下文怎么组装, 也不决定 agent 怎么执行.
它只负责把最终要发给模型的 payload 写成可读的 json 文件.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# region writer
class PayloadJsonWriter:
    """最终模型 payload 的 json 写入器.

    Attributes:
        root_dir (Path): payload json 的根目录.
    """

    def __init__(self, root_dir: Path) -> None:
        """初始化写入器.

        Args:
            root_dir: payload json 的根目录.
        """

        self.root_dir = Path(root_dir)

    def write(self, *, run_id: str, payload: dict[str, Any]) -> Path:
        """把最终 payload 写成 json 文件.

        Args:
            run_id: 当前 run_id.
            payload: 待落盘的最终 payload.

        Returns:
            写好的 json 文件路径.
        """

        safe_run_id = str(run_id or "run").replace("/", "_")
        path = self.root_dir / f"{safe_run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        jsonable_payload = self._to_jsonable(payload)
        path.write_text(
            json.dumps(jsonable_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def _to_jsonable(self, value: Any) -> Any:
        """把 payload 递归收成可以写入 json 的结构.

        Args:
            value: 任意 payload 值.

        Returns:
            一个可 json 序列化的对象.
        """

        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, list):
            return [
                converted
                for item in value
                if (converted := self._to_jsonable(item)) is not _DROP_VALUE
            ]
        if isinstance(value, tuple):
            return [
                converted
                for item in value
                if (converted := self._to_jsonable(item)) is not _DROP_VALUE
            ]
        if isinstance(value, dict):
            normalized: dict[str, Any] = {}
            for key, item in value.items():
                converted = self._to_jsonable(item)
                if converted is _DROP_VALUE:
                    continue
                normalized[str(key)] = converted
            return normalized
        return _DROP_VALUE


class _DropValue:
    """内部占位符, 表示这个值不该写进 json."""


_DROP_VALUE = _DropValue()


# endregion


__all__ = ["PayloadJsonWriter"]
