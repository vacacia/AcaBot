"""runtime.threads 定义 thread 状态管理接口和最小内存实现.

ThreadManager 只负责 thread 的创建, 读取和保存, 不负责决定 agent 绑定.

Session 是 对话+处理 的混合体, Thread 是纯粹的上下文容器
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import ThreadState


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
