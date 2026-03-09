"""NullKVStore — Null Object 模式的空实现.

当框架未配置 KV 存储时使用, 插件无需做 None 检查.
get 返回 None, set/delete 静默丢弃, update 调 updater 但不存储.
"""

from __future__ import annotations

from typing import Callable

from .base import BaseKVStore


class NullKVStore(BaseKVStore):
    """空键值存储 — 所有写入操作静默丢弃.

    与 NullMessageStore 同理: 让调用方不用 if kv is not None.
    """

    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str) -> None:
        pass

    async def delete(self, key: str) -> None:
        pass

    async def update(self, key: str, updater: Callable[[str | None], str]) -> str:
        # 调 updater 让调用方逻辑跑完, 但不存储结果
        return updater(None)
