"""runtime.threads 定义 thread 状态管理接口和最小内存实现.

ThreadManager 只负责 thread 的创建, 读取和保存, 不负责决定 agent 绑定.

Session 是 对话+处理 的混合体, Thread 是纯粹的上下文容器
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import ThreadRecord, ThreadState
from .stores import ThreadStore


class ThreadManager(ABC):
    """thread 状态管理接口."""

    @abstractmethod
    async def get(self, thread_id: str) -> ThreadState | None:
        """按 thread_id 获取运行时 thread 状态."""

        ...

    @abstractmethod
    async def get_or_create(
        self,
        *,
        thread_id: str,
        channel_scope: str,
        thread_kind: str = "channel",
        last_event_at: int = 0,
    ) -> ThreadState:
        """按 thread_id 获取或创建一个 thread 状态对象.

        Args:
            thread_id: thread 的稳定标识.
            channel_scope: 这条 thread 当前对应的 channel scope.
            thread_kind: thread 类型, 当前默认 `channel`.
            last_event_at: 最近一次事件时间戳.
        """

        ...

    @abstractmethod
    async def save(self, thread: ThreadState) -> None:
        """保存 thread 的最新运行时状态."""

        ...

    @abstractmethod
    async def list_threads(self, *, limit: int | None = None) -> list[ThreadState]:
        """按最近活跃时间列出 threads."""

        ...


class InMemoryThreadManager(ThreadManager):
    """内存版 ThreadManager.

    简易实现, 重启后状态会丢失.
    """

    def __init__(self) -> None:
        """初始化内存 thread 容器."""

        self._threads: dict[str, ThreadState] = {}

    async def get(self, thread_id: str) -> ThreadState | None:
        """读取内存中的 thread 状态."""

        return self._threads.get(thread_id)

    async def get_or_create(
        self,
        *,
        thread_id: str,
        channel_scope: str,
        thread_kind: str = "channel",
        last_event_at: int = 0,
    ) -> ThreadState:
        """获取已有 thread, 或创建一个新的 thread 状态.

        如果 thread 已存在, 这个方法只更新轻量元数据, 不会重置 working memory.
        """

        thread = self._threads.get(thread_id)
        if thread is None:
            thread = ThreadState(
                thread_id=thread_id,
                channel_scope=channel_scope,
                thread_kind=thread_kind,
                last_event_at=last_event_at,
            )
            self._threads[thread_id] = thread
            return thread

        if last_event_at > thread.last_event_at:
            thread.last_event_at = last_event_at
        if channel_scope:
            thread.channel_scope = channel_scope
        if thread_kind:
            thread.thread_kind = thread_kind
        return thread

    async def save(self, thread: ThreadState) -> None:
        """把 thread 状态回写到内存容器."""

        self._threads[thread.thread_id] = thread

    async def list_threads(self, *, limit: int | None = None) -> list[ThreadState]:
        """按最近活跃时间列出当前内存中的 threads."""

        threads = sorted(
            self._threads.values(),
            key=lambda item: (item.last_event_at, item.thread_id),
            reverse=True,
        )
        if limit is not None:
            return list(threads[:limit])
        return list(threads)


class StoreBackedThreadManager(ThreadManager):
    """基于 ThreadStore 的 ThreadManager.

    这个实现负责:
    - 在内存中缓存活跃 ThreadState.
    - 从持久化层恢复 thread.
    - 把最新状态写回 ThreadStore.
    """

    def __init__(self, store: ThreadStore) -> None:
        """初始化 store-backed ThreadManager.

        Args:
            store: thread 持久化实现.
        """

        self.store = store
        self._threads: dict[str, ThreadState] = {}

    async def get(self, thread_id: str) -> ThreadState | None:
        """按 thread_id 获取 thread 状态.
        
        Returns:
            命中的 ThreadState, 或 None.
        """

        thread = self._threads.get(thread_id)
        if thread is not None:
            return thread

        record = await self.store.get(thread_id)
        if record is None:
            return None

        thread = self._state_from_record(record)
        self._threads[thread_id] = thread
        return thread

    async def get_or_create(
        self,
        *,
        thread_id: str,
        channel_scope: str,
        thread_kind: str = "channel",
        last_event_at: int = 0,
    ) -> ThreadState:
        """按 thread_id 获取或创建一个 thread 状态对象.

        Returns:
            现有或新建的 ThreadState.
        """

        thread = await self.get(thread_id)
        if thread is None:
            thread = ThreadState(
                thread_id=thread_id,
                channel_scope=channel_scope,
                thread_kind=thread_kind,
                last_event_at=last_event_at,
            )
            self._threads[thread_id] = thread
            return thread

        if last_event_at > thread.last_event_at:
            thread.last_event_at = last_event_at
        if channel_scope:
            thread.channel_scope = channel_scope
        if thread_kind:
            thread.thread_kind = thread_kind
        return thread

    async def save(self, thread: ThreadState) -> None:
        """保存 thread 的最新运行时状态.

        Args:
            thread: 待保存的 ThreadState.
        """

        self._threads[thread.thread_id] = thread
        await self.store.upsert(self._record_from_state(thread))

    async def list_threads(self, *, limit: int | None = None) -> list[ThreadState]:
        """按最近活跃时间列出 threads."""

        records = await self.store.list_threads(limit=limit)
        states = [self._state_from_record(record) for record in records]
        for state in states:
            self._threads[state.thread_id] = state
        return states

    @staticmethod
    def _record_from_state(thread: ThreadState) -> ThreadRecord:
        """把 ThreadState 转成可持久化的 ThreadRecord.
        
        Args:
            thread: 当前运行时 thread 状态.

        Returns:
            对应的 ThreadRecord.
        """
        # 丢弃 lock
        return ThreadRecord(
            thread_id=thread.thread_id,
            channel_scope=thread.channel_scope,
            thread_kind=thread.thread_kind,
            working_messages=list(thread.working_messages),
            working_summary=thread.working_summary,
            last_event_at=thread.last_event_at,
            metadata=dict(thread.metadata),
        )

    @staticmethod
    def _state_from_record(record: ThreadRecord) -> ThreadState:
        """把 ThreadRecord 恢复成 ThreadState.

        Args:
            record: 从持久化层读出的 ThreadRecord.

        Returns:
            可直接进入运行时的 ThreadState.
        """
        # 自动创建新锁对象
        # lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)
        return ThreadState(
            thread_id=record.thread_id,
            channel_scope=record.channel_scope,
            thread_kind=record.thread_kind,
            working_messages=list(record.working_messages),
            working_summary=record.working_summary,
            last_event_at=record.last_event_at,
            metadata=dict(record.metadata),
        )
