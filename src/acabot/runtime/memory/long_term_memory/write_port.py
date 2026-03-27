"""runtime.memory.long_term_memory.write_port 负责长期记忆写侧主状态机."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from ..conversation_facts import ConversationDelta, ConversationFact
from ..long_term_ingestor import (
    LongTermMemoryWritePort,
    ThreadLtmCursor,
    ThreadLtmIngestResult,
)
from .contracts import FailedWindowRecord, MemoryEntry
from .fact_ids import build_fact_id_from_conversation_fact


class LtmWindowExtractor(Protocol):
    """LtmWindowExtractor 定义写侧提取依赖面."""

    async def extract_window(
        self,
        *,
        conversation_id: str,
        facts: list[ConversationFact],
        now_ts: int,
    ) -> list[MemoryEntry]:
        """把一个事实窗口提取成长期记忆列表."""


class LtmEntryEmbeddingClient(Protocol):
    """LtmEntryEmbeddingClient 定义写侧 embedding 依赖面."""

    async def embed_entries(self, entries: list[MemoryEntry]) -> list[list[float]]:
        """把一批 entry 变成向量."""


class LongTermMemoryWriteStore(Protocol):
    """LongTermMemoryWriteStore 定义写侧需要的最小存储依赖面."""

    def load_cursor(self, thread_id: str) -> ThreadLtmCursor | None:
        """读取一个 thread 当前游标."""

    def save_cursor(self, cursor: ThreadLtmCursor) -> None:
        """保存一个 thread 当前游标."""

    def upsert_entries(
        self,
        entries: list[MemoryEntry],
        *,
        vectors: list[list[float]] | None = None,
    ) -> None:
        """写入一批长期记忆对象."""

    def save_failed_window(self, record: FailedWindowRecord) -> None:
        """保存一个失败窗口对象."""

    def load_failed_window(self, window_id: str) -> FailedWindowRecord | None:
        """读取一个失败窗口对象."""


@dataclass(slots=True)
class FactWindow:
    """FactWindow 表示一个按 fact 数量切出来的写侧窗口.

    Attributes:
        facts (list[ConversationFact]): 当前窗口事实.
        fact_ids (list[str]): 当前窗口正式 fact_id 集合.
    """

    facts: list[ConversationFact]
    fact_ids: list[str]


class CoreSimpleMemWritePort(LongTermMemoryWritePort):
    """CoreSimpleMemWritePort 把 ConversationDelta 接到 Core SimpleMem."""

    def __init__(
        self,
        *,
        store: LongTermMemoryWriteStore,
        extractor: LtmWindowExtractor,
        embedding_client: LtmEntryEmbeddingClient,
        window_size: int = 50,
        overlap_size: int = 10,
    ) -> None:
        """初始化长期记忆写侧端口.

        Args:
            store: 写侧存储依赖面.
            extractor: 窗口提取器.
            embedding_client: entry embedding 客户端.
            window_size: 每个窗口默认包含的 fact 数.
            overlap_size: 相邻窗口重叠的 fact 数.
        """

        self.store = store
        self.extractor = extractor
        self.embedding_client = embedding_client
        self.window_size = int(window_size)
        self.overlap_size = int(overlap_size)
        self.step_size = max(1, self.window_size - self.overlap_size)

    async def load_cursor(self, thread_id: str) -> ThreadLtmCursor | None:
        """读取一个 thread 的写入游标.

        Args:
            thread_id: 目标 thread.

        Returns:
            当前游标, 不存在则返回 None.
        """

        return await asyncio.to_thread(self.store.load_cursor, thread_id)

    async def save_cursor(self, cursor: ThreadLtmCursor) -> None:
        """保存一个 thread 的写入游标.

        Args:
            cursor: 待保存游标.
        """

        await asyncio.to_thread(self.store.save_cursor, cursor)

    async def ingest_thread_delta(
        self,
        thread_id: str,
        delta: ConversationDelta,
    ) -> ThreadLtmIngestResult:
        """把一个 thread 的增量事实窗口写进 Core SimpleMem.

        Args:
            thread_id: 目标 thread.
            delta: 当前增量事实窗口.

        Returns:
            当前增量的写入结果.
        """

        _ = thread_id
        if not delta.facts:
            return ThreadLtmIngestResult(advance_cursor=True, has_failures=False)
        conversation_id = derive_conversation_id_from_delta(delta)
        has_failures = False
        for window in slice_fact_windows(
            delta.facts,
            window_size=self.window_size,
            overlap_size=self.overlap_size,
        ):
            try:
                now_ts = max(int(fact.timestamp) for fact in window.facts)
                entries = await self.extractor.extract_window(
                    conversation_id=conversation_id,
                    facts=window.facts,
                    now_ts=now_ts,
                )
                vectors = await self.embedding_client.embed_entries(entries)
                await asyncio.to_thread(self.store.upsert_entries, entries, vectors=vectors)
            except Exception as exc:
                window_id = build_failed_window_id(conversation_id, window.fact_ids)
                window_ts = max(int(fact.timestamp) for fact in window.facts)
                existing_failed_window = await asyncio.to_thread(self.store.load_failed_window, window_id)
                failed_window = FailedWindowRecord(
                    window_id=window_id,
                    conversation_id=conversation_id,
                    thread_id=window.facts[0].thread_id,
                    fact_ids=window.fact_ids,
                    error=str(exc),
                    retry_count=(
                        int(existing_failed_window.retry_count) + 1
                        if existing_failed_window is not None
                        else 1
                    ),
                    first_failed_at=(
                        int(existing_failed_window.first_failed_at)
                        if existing_failed_window is not None
                        else window_ts
                    ),
                    last_failed_at=window_ts,
                )
                try:
                    await asyncio.to_thread(self.store.save_failed_window, failed_window)
                except Exception:
                    return ThreadLtmIngestResult(advance_cursor=False, has_failures=True)
                has_failures = True
                continue
        return ThreadLtmIngestResult(
            advance_cursor=True,
            has_failures=has_failures,
        )


def derive_conversation_id_from_delta(delta: ConversationDelta) -> str:
    """从增量窗口里推导正式 `conversation_id`.

    Args:
        delta: 当前增量事实窗口.

    Returns:
        当前窗口所属对话容器.

    Raises:
        ValueError: 当窗口为空或混入多个 conversation 时抛出.
    """

    if not delta.facts:
        raise ValueError("delta.facts is required")
    conversation_ids = {
        str(fact.channel_scope or "").strip()
        for fact in delta.facts
        if str(fact.channel_scope or "").strip()
    }
    if len(conversation_ids) != 1:
        raise ValueError("delta must belong to exactly one conversation_id")
    return next(iter(conversation_ids))


def slice_fact_windows(
    facts: list[ConversationFact],
    *,
    window_size: int,
    overlap_size: int,
) -> list[FactWindow]:
    """按固定 fact 窗口切分一段对话事实.

    Args:
        facts: 当前增量事实窗口.
        window_size: 单窗 fact 数.
        overlap_size: 相邻窗口重叠的 fact 数.

    Returns:
        事实窗口列表.
    """

    if not facts:
        return []
    normalized_window_size = max(1, int(window_size))
    step_size = max(1, normalized_window_size - max(0, int(overlap_size)))
    windows: list[FactWindow] = []
    start = 0
    while start < len(facts):
        fact_window = list(facts[start : start + normalized_window_size])
        if not fact_window:
            break
        windows.append(
            FactWindow(
                facts=fact_window,
                fact_ids=[build_fact_id_from_conversation_fact(fact) for fact in fact_window],
            )
        )
        if start + normalized_window_size >= len(facts):
            break
        start += step_size
    return windows


def build_failed_window_id(conversation_id: str, fact_ids: list[str]) -> str:
    """根据对话容器和窗口 fact 集合构造稳定失败窗口主键.

    Args:
        conversation_id: 所属对话容器.
        fact_ids: 当前窗口正式 fact_id 集合.

    Returns:
        稳定失败窗口主键.
    """

    if not fact_ids:
        raise ValueError("fact_ids is required")
    return f"{conversation_id}:{fact_ids[0]}:{fact_ids[-1]}"


__all__ = [
    "CoreSimpleMemWritePort",
    "FactWindow",
    "LongTermMemoryWriteStore",
    "build_failed_window_id",
    "derive_conversation_id_from_delta",
    "slice_fact_windows",
]
