"""KVStore 抽象基类 — 键值存储的统一接口.

所有 key/value 均为 str, 复杂数据由调用方自行序列化.
提供原子 update(读-改-写) 操作, 具体实现负责保证原子性.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class BaseKVStore(ABC):
    """键值存储抽象基类.

    接口设计:
        - get/set/delete: 基础 CRUD.
        - update: 原子读-改-写, 适用于计数器/追加等场景.
    """

    @abstractmethod
    async def get(self, key: str) -> str | None:
        """读取 key 对应的值.

        Args:
            key: 键名.

        Returns:
            值字符串, 不存在返回 None.
        """
        ...

    @abstractmethod
    async def set(self, key: str, value: str) -> None:
        """写入 key-value.

        Args:
            key: 键名.
            value: 值字符串.
        """
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """删除 key. key 不存在时静默忽略.

        Args:
            key: 键名.
        """
        ...

    @abstractmethod
    async def update(self, key: str, updater: Callable[[str | None], str]) -> str:
        """原子读-改-写.

        读出旧值 -> 调 updater(旧值) -> 写回新值 -> 返回新值.
        实现层负责保证整个过程的原子性(如加锁).

        Args:
            key: 键名.
            updater: 接收旧值(可能为 None), 返回新值的函数.

        Returns:
            updater 返回的新值.
        """
        ...
