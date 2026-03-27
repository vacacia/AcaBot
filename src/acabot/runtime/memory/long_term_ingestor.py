"""runtime.memory.long_term_ingestor 负责长期记忆写入线的编排.

组件关系:

    RuntimeApp / Outbox
        |
        v
    LongTermMemoryIngestor.mark_dirty(thread_id)
        |
        v
    LongTermMemoryIngestor worker
        |
        v
    ConversationFactReader + LongTermMemoryWritePort

这一层只负责写入线编排:
- 收信号
- 读增量事实窗口
- 调写侧端口
- 在成功后推进游标
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Protocol

from .conversation_facts import ConversationDelta, ConversationFactReader
from ..storage.threads import ThreadManager

logger = logging.getLogger("acabot.runtime.memory.long_term_ingestor")


# region 写侧状态
@dataclass(slots=True)
class ThreadLtmCursor:
    """ThreadLtmCursor 表示一个 thread 的长期记忆写入游标.

    Attributes:
        thread_id (str): 所属 thread.
        last_event_id (int | None): 已处理到的最大事件 sequence.
        last_message_id (int | None): 已处理到的最大消息 sequence.
        updated_at (int): 最近一次更新时间.
    """

    thread_id: str
    last_event_id: int | None = None
    last_message_id: int | None = None
    updated_at: int = 0


@dataclass(slots=True)
class ThreadLtmIngestResult:
    """ThreadLtmIngestResult 表示一次增量写入的结果.

    Attributes:
        advance_cursor (bool): 当前增量是否允许推进游标.
        has_failures (bool): 这次增量里是否出现失败窗口.
    """

    advance_cursor: bool
    has_failures: bool = False


class LongTermMemoryWritePort(Protocol):
    """LongTermMemoryWritePort 定义 LTM 写侧最小依赖面."""

    async def load_cursor(self, thread_id: str) -> ThreadLtmCursor | None:
        """读取一个 thread 当前的写入游标.

        Args:
            thread_id: 目标 thread.

        Returns:
            当前游标, 如果还没有则返回 None.
        """

        ...

    async def save_cursor(self, cursor: ThreadLtmCursor) -> None:
        """保存一个 thread 当前的写入游标.

        Args:
            cursor: 待保存游标.
        """

        ...

    async def ingest_thread_delta(
        self,
        thread_id: str,
        delta: ConversationDelta,
    ) -> ThreadLtmIngestResult:
        """把一个 thread 的增量事实窗口交给 LTM.

        Args:
            thread_id: 目标 thread.
            delta: 当前增量事实窗口.

        Returns:
            当前增量的写入结果.
        """

        ...


# endregion


# region ingestor
class LongTermMemoryIngestor:
    """LongTermMemoryIngestor 统一收口长期记忆写入线.

    Attributes:
        _thread_manager (ThreadManager): 用来列出已知 threads.
        _fact_reader (ConversationFactReader): 统一事实窗口读取器.
        _write_port (LongTermMemoryWritePort): LTM 写侧端口.
        _dirty_threads (set[str]): 待处理 thread 集合.
        _wake_event (asyncio.Event): 唤醒 worker 的并发原语.
        _worker_task (asyncio.Task[None] | None): 主消费 task.
        _startup_reconcile_task (asyncio.Task[None] | None): 启动扫库 task.
        _started (bool): 是否已经启动.
        _stopping (bool): 是否正在停机.
    """

    def __init__(
        self,
        *,
        thread_manager: ThreadManager,
        fact_reader: ConversationFactReader,
        write_port: LongTermMemoryWritePort,
    ) -> None:
        """初始化长期记忆写入编排器.

        Args:
            thread_manager: thread 管理器.
            fact_reader: 统一事实窗口读取器.
            write_port: LTM 写侧端口.
        """

        self._thread_manager = thread_manager
        self._fact_reader = fact_reader
        self._write_port = write_port
        self._dirty_threads: set[str] = set()
        self._wake_event = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._startup_reconcile_task: asyncio.Task[None] | None = None
        self._started = False
        self._stopping = False

    async def start(self) -> None:
        """启动 worker 和启动扫库 task.

        Returns:
            None. 这个方法不等待扫库完成.
        """

        if self._started:
            return
        self._started = True
        self._stopping = False
        self._worker_task = asyncio.create_task(self._worker_loop())
        self._startup_reconcile_task = asyncio.create_task(self._startup_reconcile())

    async def stop(self) -> None:
        """优雅停机.

        Returns:
            None. 当前正在处理的 thread 会跑完, 其他待处理项会被丢弃.
        """

        if not self._started:
            return

        self._stopping = True
        reconcile_task = self._startup_reconcile_task
        self._startup_reconcile_task = None
        if reconcile_task is not None:
            reconcile_task.cancel()
            try:
                await reconcile_task
            except asyncio.CancelledError:
                pass

        self._wake_event.set()

        worker_task = self._worker_task
        self._worker_task = None
        if worker_task is not None:
            await worker_task

        self._dirty_threads.clear()
        self._wake_event.clear()
        self._started = False
        self._stopping = False

    def mark_dirty(self, thread_id: str) -> None:
        """标记一个 thread 需要重新拉增量事实窗口.

        Args:
            thread_id: 目标 thread.
        """

        self._dirty_threads.add(thread_id)
        self._wake_event.set()

    async def _startup_reconcile(self) -> None:
        """启动时扫一遍已知 thread, 把落后的 thread 重新标脏."""

        try:
            threads = await self._thread_manager.list_threads()
        except Exception:
            logger.exception("Long-term memory startup reconcile failed while listing threads")
            return

        for thread in threads:
            if self._stopping:
                return

            try:
                cursor = await self._write_port.load_cursor(thread.thread_id)
                delta = await self._fact_reader.get_thread_delta(
                    thread.thread_id,
                    None if cursor is None else cursor.last_event_id,
                    None if cursor is None else cursor.last_message_id,
                )
            except Exception:
                logger.exception(
                    "Long-term memory startup reconcile crashed for thread: %s",
                    thread.thread_id,
                )
                continue
            if delta.facts:
                self.mark_dirty(thread.thread_id)

    async def _worker_loop(self) -> None:
        """后台消费 dirty threads."""

        while True:
            if self._stopping:
                return

            thread_id = self._take_next_dirty_thread()
            if thread_id is not None:
                try:
                    await self._process_thread(thread_id)
                except Exception:
                    logger.exception(
                        "Long-term memory ingest crashed for thread: %s",
                        thread_id,
                    )
                continue

            self._wake_event.clear()
            if self._stopping or self._dirty_threads:
                continue
            await self._wake_event.wait()

    async def _process_thread(self, thread_id: str) -> None:
        """处理一个 thread 的增量事实窗口.

        Args:
            thread_id: 目标 thread.
        """

        cursor = await self._write_port.load_cursor(thread_id)
        current_cursor = cursor or ThreadLtmCursor(thread_id=thread_id)
        delta = await self._fact_reader.get_thread_delta(
            thread_id,
            current_cursor.last_event_id,
            current_cursor.last_message_id,
        )
        if not delta.facts:
            return

        result = await self._write_port.ingest_thread_delta(thread_id, delta)
        if not result.advance_cursor:
            return
        if result.has_failures:
            logger.warning(
                "Long-term memory ingest finished with failed windows for thread: %s",
                thread_id,
            )

        try:
            await self._write_port.save_cursor(
                ThreadLtmCursor(
                    thread_id=thread_id,
                    last_event_id=delta.max_event_id,
                    last_message_id=delta.max_message_id,
                    updated_at=int(time.time()),
                )
            )
        except Exception:
            logger.exception(
                "Long-term memory cursor save failed for thread: %s",
                thread_id,
            )

    def _take_next_dirty_thread(self) -> str | None:
        """取出下一个待处理 thread.

        Returns:
            一个待处理 thread, 如果当前没有则返回 None.
        """

        if not self._dirty_threads:
            return None
        thread_id = sorted(self._dirty_threads)[0]
        self._dirty_threads.remove(thread_id)
        return thread_id


# endregion


__all__ = [
    "LongTermMemoryIngestor",
    "ThreadLtmIngestResult",
    "LongTermMemoryWritePort",
    "ThreadLtmCursor",
]
