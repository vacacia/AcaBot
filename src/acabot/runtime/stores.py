"""运行时依赖的持久化接口.

只声明协议, 不绑定具体数据库实现.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import MessageRecord, RunRecord, RunStep, ThreadRecord


class MessageStore(ABC):
    """消息事实存储接口."""

    @abstractmethod
    async def save(self, msg: MessageRecord) -> None:
        """保存一条消息事实记录."""

        ...

    @abstractmethod
    async def get_thread_messages(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
        since: int | None = None,
    ) -> list[MessageRecord]:
        """按 thread 查询消息事实记录.

        Args:
            thread_id: 要查询的 thread 标识.
            limit: 最多返回多少条消息.
            since: 只返回晚于该时间戳的消息.
        """

        ...


class ThreadStore(ABC):
    """thread 持久化接口."""

    @abstractmethod
    async def get(self, thread_id: str) -> ThreadRecord | None:
        """按 thread_id 获取 thread 的持久化记录."""

        ...

    @abstractmethod
    async def upsert(self, thread: ThreadRecord) -> None:
        """插入或更新一条 thread 持久化记录."""

        ...


class RunStore(ABC):
    """run 持久化接口."""

    @abstractmethod
    async def create_run(self, run: RunRecord) -> None:
        """创建一条新的 run 记录."""

        ...

    @abstractmethod
    async def update_run(self, run: RunRecord) -> None:
        """更新一条已有的 run 记录."""

        ...

    @abstractmethod
    async def append_step(self, step: RunStep) -> None:
        """追加一条 run step 审计记录."""

        ...
