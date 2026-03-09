"""InMemoryKVStore — 基于 dict 的内存键值存储.

适用于开发/测试和单进程部署. 数据不持久化, 进程退出即丢失.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from .base import BaseKVStore


class InMemoryKVStore(BaseKVStore):
    """内存键值存储.

    内部用 dict 存储, asyncio.Lock 保证 update 原子性.
    """

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        # update 需要原子读-改-写, Lock 防止并发 update 同一 key 时丢失更新
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str) -> None:
        self._data[key] = value

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def update(self, key: str, updater: Callable[[str | None], str]) -> str:
        async with self._lock:
            old = self._data.get(key)
            new = updater(old)
            self._data[key] = new
            return new
