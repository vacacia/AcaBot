"""运行时依赖的持久化接口.

只声明协议, 不绑定具体数据库实现.

当前覆盖五类持久化:
- ChannelEventStore
- MemoryStore
- MessageStore
- ThreadStore
- RunStore
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import (
    ChannelEventRecord,
    MemoryItem,
    MessageRecord,
    RunRecord,
    RunStep,
    ThreadRecord,
)


class ChannelEventStore(ABC):
    """channel event 存储接口."""

    @abstractmethod
    async def save(self, event: ChannelEventRecord) -> None:
        """保存一条 channel event 记录.

        Args:
            event: 待写入的 ChannelEventRecord.
        """

        ...

    @abstractmethod
    async def get_thread_events(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
        since: int | None = None,
        event_types: list[str] | None = None,
    ) -> list[ChannelEventRecord]:
        """按 thread 查询 channel event 记录.

        Args:
            thread_id: 要查询的 thread 标识.
            limit: 最多返回多少条事件.
            since: 只返回晚于该时间戳的事件.
            event_types: 可选事件类型过滤列表.

        Returns:
            满足条件的 ChannelEventRecord 列表.
        """

        ...


class MessageStore(ABC):
    """message 存储接口."""

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


# region memory store
class MemoryStore(ABC):
    """长期记忆项的持久化接口."""

    @abstractmethod
    async def upsert(self, item: MemoryItem) -> None:
        """插入或更新一条长期记忆项.

        Args:
            item: 待写入的 MemoryItem.
        """

        ...

    @abstractmethod
    async def find(
        self,
        *,
        scope: str,
        scope_key: str,
        memory_types: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryItem]:
        """按 scope 查询长期记忆项.

        Args:
            scope: 当前查询的 scope.
            scope_key: 当前 scope 对应的 key.
            memory_types: 可选的记忆类型过滤列表.
            limit: 最多返回多少条记忆项.

        Returns:
            满足条件的 MemoryItem 列表.
        """

        ...


# endregion


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
    async def get_run(self, run_id: str) -> RunRecord | None:
        """按 run_id 获取一条 run 记录."""

        ...

    @abstractmethod
    async def update_run(self, run: RunRecord) -> None:
        """更新一条已有的 run 记录."""

        ...

    @abstractmethod
    async def list_active_runs(self, statuses: set[str]) -> list[RunRecord]:
        """按状态集合列出所有活跃 run.
        
        Args:
            statuses: 需要被视为活跃状态的 status 集合.
            _ACTIVE_STATUSES: set[RunStatus] = {"queued", "running", "waiting_approval"}
        """

        ...

    @abstractmethod
    async def append_step(self, step: RunStep) -> None:
        """追加一条 run step 审计记录."""

        ...
