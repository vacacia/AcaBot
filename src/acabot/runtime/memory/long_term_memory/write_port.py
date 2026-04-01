"""长期记忆写侧主状态机.

把 ConversationDelta 按滑动窗口切分, 逐窗口走 提取 → embedding → 存储 三步.
单窗口失败不阻塞后续窗口, 失败记录落盘供后续重试.
"""

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
    """写侧提取依赖面: 从一组对话事实中提取结构化记忆条目."""

    async def extract_window(
        self,
        *,
        conversation_id: str,
        facts: list[ConversationFact],
        now_ts: int,
    ) -> list[MemoryEntry]:
        """从一个事实窗口提取长期记忆条目 (通常背后是 LLM 调用)."""


class LtmEntryEmbeddingClient(Protocol):
    """写侧 embedding 依赖面: 把记忆条目向量化."""

    async def embed_entries(self, entries: list[MemoryEntry]) -> list[list[float]]:
        """为一批 MemoryEntry 生成对应的 embedding 向量."""


class LongTermMemoryWriteStore(Protocol):
    """写侧最小存储依赖面: cursor 管理 + entry 写入 + 失败记录."""

    def load_cursor(self, thread_id: str) -> ThreadLtmCursor | None:
        """读取指定 thread 的写入游标, 不存在返回 None."""

    def save_cursor(self, cursor: ThreadLtmCursor) -> None:
        """持久化 thread 写入游标."""

    def upsert_entries(
        self,
        entries: list[MemoryEntry],
        *,
        vectors: list[list[float]] | None = None,
    ) -> None:
        """写入或更新一批长期记忆条目, 可选附带 embedding 向量."""

    def save_failed_window(self, record: FailedWindowRecord) -> None:
        """持久化失败窗口记录, 供后续重试."""

    def load_failed_window(self, window_id: str) -> FailedWindowRecord | None:
        """按 window_id 读取失败窗口记录, 不存在返回 None."""


@dataclass(slots=True)
class FactWindow:
    """按 fact 数量切出来的写侧窗口."""

    facts: list[ConversationFact]
    fact_ids: list[str]


class LtmWritePort(LongTermMemoryWritePort):
    """LTM 写入端口: 把 ConversationDelta 按滑动窗口写进长期记忆.

    窗口策略: 每 *window_size* 条 fact 切一窗, 相邻窗口重叠 *overlap_size* 条,
    避免边界处语义丢失. 单窗口处理失败时记录 FailedWindowRecord 并跳过,
    不阻塞后续窗口.
    """

    def __init__(
        self,
        *,
        store: LongTermMemoryWriteStore,
        extractor: LtmWindowExtractor,
        embedding_client: LtmEntryEmbeddingClient,
        window_size: int = 50,
        overlap_size: int = 10,
    ) -> None:
        self.store = store
        self.extractor = extractor
        self.embedding_client = embedding_client
        self.window_size = int(window_size)
        self.overlap_size = int(overlap_size)
        self.step_size = max(1, self.window_size - self.overlap_size)

    async def load_cursor(self, thread_id: str) -> ThreadLtmCursor | None:
        """读取指定 thread 的写入游标, 不存在返回 None."""
        return await asyncio.to_thread(self.store.load_cursor, thread_id)

    async def save_cursor(self, cursor: ThreadLtmCursor) -> None:
        """持久化 thread 写入游标."""
        await asyncio.to_thread(self.store.save_cursor, cursor)

    async def ingest_thread_delta(
        self,
        thread_id: str,
        delta: ConversationDelta,
    ) -> ThreadLtmIngestResult:
        """把一个 thread 的增量事实写进长期记忆.

        处理流程: 切窗口 → 逐窗口 (提取 → embedding → 存储).

        失败策略:
        - 单窗口失败: 记录 FailedWindowRecord, 跳过继续处理后续窗口.
        - 失败记录本身写不进去: 立刻返回 advance_cursor=False, 阻止游标前进.
        - 部分窗口失败: 游标仍然前进, 通过 has_failures=True 告知调用方.
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
    """从增量窗口的 channel_scope 推导唯一 conversation_id.

    要求 delta 内所有 fact 属于同一个 conversation, 否则抛 ValueError.
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
    """按滑动窗口切分对话事实, 步长 = window_size - overlap_size."""

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
    """构造稳定的失败窗口主键: ``{conversation_id}:{first_fact_id}:{last_fact_id}``."""

    if not fact_ids:
        raise ValueError("fact_ids is required")
    return f"{conversation_id}:{fact_ids[0]}:{fact_ids[-1]}"


__all__ = [
    "LtmWritePort",
    "FactWindow",
    "LongTermMemoryWriteStore",
    "build_failed_window_id",
    "derive_conversation_id_from_delta",
    "slice_fact_windows",
]
