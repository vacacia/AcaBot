"""runtime.memory.long_term_memory.storage 集中管理 LanceDB 持久化.

这个模块只负责 Core SimpleMem 的存储层:
- 建表
- `MemoryEntry` 读写
- 词法检索
- 结构检索
- `ThreadLtmCursor` 读写
- failed window 读写

第一版实现保持简单:
- 全部状态都写进单一 LanceDB 目录
- 更新路径采用整表重写, 先把正确行为跑通
- LanceDB 的细节都收口在这个文件里, 不泄漏给上层
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import math

import lancedb
import pyarrow as pa

from ..long_term_ingestor import ThreadLtmCursor
from .contracts import FailedWindowRecord, MemoryEntry, MemoryProvenance


# region helpers
def _quote_sql_text(value: str) -> str:
    """把字符串转成可放进 LanceDB 过滤表达式的字面量.

    Args:
        value: 原始字符串.

    Returns:
        适合 SQL-like 过滤表达式的字符串字面量.
    """

    return str(value or "").replace("\\", "\\\\").replace("'", "''")


def _normalize_text(value: str | None) -> str:
    """清理一个可选文本字段.

    Args:
        value: 原始文本.

    Returns:
        去掉首尾空白后的结果.
    """

    return str(value or "").strip()


def _build_lexical_text(entry: MemoryEntry) -> str:
    """把 entry 的词法检索真源拼成一段字符串.

    Args:
        entry: 当前长期记忆对象.

    Returns:
        词法检索用的拼接文本.
    """

    parts = [entry.topic, entry.lossless_restatement, *entry.keywords]
    return " ".join(part for part in parts if _normalize_text(part))


def _entry_table_schema() -> pa.Schema:
    """返回长期记忆主表 schema.

    Returns:
        `memory_entries` 的 Arrow schema.
    """

    return pa.schema(
        [
            pa.field("entry_id", pa.string()),
            pa.field("conversation_id", pa.string()),
            pa.field("created_at", pa.int64()),
            pa.field("updated_at", pa.int64()),
            pa.field("extractor_version", pa.string()),
            pa.field("topic", pa.string()),
            pa.field("lossless_restatement", pa.string()),
            pa.field("lexical_text", pa.string()),
            pa.field("keywords", pa.list_(pa.string())),
            pa.field("time_point", pa.string()),
            pa.field("time_interval_start", pa.string()),
            pa.field("time_interval_end", pa.string()),
            pa.field("location", pa.string()),
            pa.field("persons", pa.list_(pa.string())),
            pa.field("entities", pa.list_(pa.string())),
            pa.field("provenance_fact_ids", pa.list_(pa.string())),
            pa.field("has_vector", pa.bool_()),
            pa.field("vector", pa.list_(pa.float32())),
        ]
    )


def _cursor_table_schema() -> pa.Schema:
    """返回写入游标表 schema.

    Returns:
        `thread_cursors` 的 Arrow schema.
    """

    return pa.schema(
        [
            pa.field("thread_id", pa.string()),
            pa.field("last_event_id", pa.int64()),
            pa.field("last_message_id", pa.int64()),
            pa.field("updated_at", pa.int64()),
        ]
    )


def _failed_window_table_schema() -> pa.Schema:
    """返回失败窗口表 schema.

    Returns:
        `failed_windows` 的 Arrow schema.
    """

    return pa.schema(
        [
            pa.field("window_id", pa.string()),
            pa.field("conversation_id", pa.string()),
            pa.field("thread_id", pa.string()),
            pa.field("fact_ids", pa.list_(pa.string())),
            pa.field("error", pa.string()),
            pa.field("retry_count", pa.int64()),
            pa.field("first_failed_at", pa.int64()),
            pa.field("last_failed_at", pa.int64()),
        ]
    )


def _entry_to_record(entry: MemoryEntry, *, vector: list[float] | None) -> dict[str, Any]:
    """把 `MemoryEntry` 转成 LanceDB 行.

    Args:
        entry: 当前长期记忆对象.

    Returns:
        可写入 LanceDB 的行字典.
    """

    return {
        "entry_id": entry.entry_id,
        "conversation_id": entry.conversation_id,
        "created_at": int(entry.created_at),
        "updated_at": int(entry.updated_at),
        "extractor_version": entry.extractor_version,
        "topic": entry.topic,
        "lossless_restatement": entry.lossless_restatement,
        "lexical_text": _build_lexical_text(entry),
        "keywords": list(entry.keywords),
        "time_point": entry.time_point,
        "time_interval_start": entry.time_interval_start,
        "time_interval_end": entry.time_interval_end,
        "location": entry.location,
        "persons": list(entry.persons),
        "entities": list(entry.entities),
        "provenance_fact_ids": list(entry.provenance.fact_ids),
        "has_vector": vector is not None,
        "vector": [float(value) for value in list(vector or [])] if vector is not None else None,
    }


def _record_to_entry(record: dict[str, Any]) -> MemoryEntry:
    """把 LanceDB 行还原成 `MemoryEntry`.

    Args:
        record: LanceDB 返回的字典.

    Returns:
        还原后的长期记忆对象.
    """

    return MemoryEntry(
        entry_id=str(record.get("entry_id", "") or ""),
        conversation_id=str(record.get("conversation_id", "") or ""),
        created_at=int(record.get("created_at", 0) or 0),
        updated_at=int(record.get("updated_at", 0) or 0),
        extractor_version=str(record.get("extractor_version", "") or ""),
        topic=str(record.get("topic", "") or ""),
        lossless_restatement=str(record.get("lossless_restatement", "") or ""),
        keywords=[str(item) for item in list(record.get("keywords", []) or [])],
        time_point=record.get("time_point"),
        time_interval_start=record.get("time_interval_start"),
        time_interval_end=record.get("time_interval_end"),
        location=record.get("location"),
        persons=[str(item) for item in list(record.get("persons", []) or [])],
        entities=[str(item) for item in list(record.get("entities", []) or [])],
        provenance=MemoryProvenance(
            fact_ids=[str(item) for item in list(record.get("provenance_fact_ids", []) or [])]
        ),
    )


def _entry_payload_changed(existing_row: dict[str, Any], incoming_row: dict[str, Any]) -> bool:
    """判断两条 entry 行在正式字段上是否发生了实质变化.

    Args:
        existing_row: 已有行.
        incoming_row: 新行.

    Returns:
        发生实质变化返回 True, 否则返回 False.
    """

    tracked_keys = (
        "conversation_id",
        "extractor_version",
        "topic",
        "lossless_restatement",
        "lexical_text",
        "keywords",
        "time_point",
        "time_interval_start",
        "time_interval_end",
        "location",
        "persons",
        "entities",
        "provenance_fact_ids",
    )
    return any(existing_row.get(key) != incoming_row.get(key) for key in tracked_keys)


def _merge_entry_record(
    existing_row: dict[str, Any] | None,
    incoming_row: dict[str, Any],
) -> dict[str, Any]:
    """把一条新 entry 行合并进当前主表快照.

    Args:
        existing_row: 已有行, 不存在时为 None.
        incoming_row: 新写入行.

    Returns:
        合并后的结果行.
    """

    if existing_row is None:
        return dict(incoming_row)
    if not _entry_payload_changed(existing_row, incoming_row):
        if not bool(existing_row.get("has_vector", False)) and bool(incoming_row.get("has_vector", False)):
            merged_row = dict(existing_row)
            merged_row["vector"] = list(incoming_row.get("vector", []) or [])
            merged_row["has_vector"] = True
            return merged_row
        return dict(existing_row)
    if int(existing_row.get("updated_at", 0) or 0) > int(incoming_row.get("updated_at", 0) or 0):
        return dict(existing_row)
    merged_row = dict(incoming_row)
    merged_row["created_at"] = int(existing_row.get("created_at", incoming_row.get("created_at", 0)) or 0)
    return merged_row


def _cursor_to_record(cursor: ThreadLtmCursor) -> dict[str, Any]:
    """把游标对象转成 LanceDB 行.

    Args:
        cursor: 当前 thread 游标.

    Returns:
        可写入 LanceDB 的行字典.
    """

    return {
        "thread_id": cursor.thread_id,
        "last_event_id": cursor.last_event_id,
        "last_message_id": cursor.last_message_id,
        "updated_at": int(cursor.updated_at),
    }


def _record_to_cursor(record: dict[str, Any]) -> ThreadLtmCursor:
    """把 LanceDB 行还原成游标对象.

    Args:
        record: LanceDB 返回的字典.

    Returns:
        还原后的写入游标.
    """

    return ThreadLtmCursor(
        thread_id=str(record.get("thread_id", "") or ""),
        last_event_id=record.get("last_event_id"),
        last_message_id=record.get("last_message_id"),
        updated_at=int(record.get("updated_at", 0) or 0),
    )


def _failed_window_to_record(record: FailedWindowRecord) -> dict[str, Any]:
    """把失败窗口对象转成 LanceDB 行.

    Args:
        record: 当前失败窗口对象.

    Returns:
        可写入 LanceDB 的行字典.
    """

    return {
        "window_id": record.window_id,
        "conversation_id": record.conversation_id,
        "thread_id": record.thread_id,
        "fact_ids": list(record.fact_ids),
        "error": record.error,
        "retry_count": int(record.retry_count),
        "first_failed_at": int(record.first_failed_at),
        "last_failed_at": int(record.last_failed_at),
    }


def _record_to_failed_window(record: dict[str, Any]) -> FailedWindowRecord:
    """把 LanceDB 行还原成失败窗口对象.

    Args:
        record: LanceDB 返回的字典.

    Returns:
        还原后的失败窗口对象.
    """

    return FailedWindowRecord(
        window_id=str(record.get("window_id", "") or ""),
        conversation_id=str(record.get("conversation_id", "") or ""),
        thread_id=str(record.get("thread_id", "") or ""),
        fact_ids=[str(item) for item in list(record.get("fact_ids", []) or [])],
        error=str(record.get("error", "") or ""),
        retry_count=int(record.get("retry_count", 0) or 0),
        first_failed_at=int(record.get("first_failed_at", 0) or 0),
        last_failed_at=int(record.get("last_failed_at", 0) or 0),
    )


def _time_overlaps(
    *,
    query_start: str | None,
    query_end: str | None,
    entry_time_point: str | None,
    entry_interval_start: str | None,
    entry_interval_end: str | None,
) -> bool:
    """判断 query 时间范围与 entry 时间范围是否有交集.

    Args:
        query_start: 查询侧开始边界.
        query_end: 查询侧结束边界.
        entry_time_point: entry 的单点时间.
        entry_interval_start: entry 的区间开始边界.
        entry_interval_end: entry 的区间结束边界.

    Returns:
        有交集返回 True, 否则返回 False.
    """

    if not _normalize_text(query_start) and not _normalize_text(query_end):
        return True
    if entry_time_point:
        if query_start and entry_time_point < query_start:
            return False
        if query_end and entry_time_point > query_end:
            return False
        return True
    normalized_entry_start = entry_interval_start or ""
    normalized_entry_end = entry_interval_end or ""
    normalized_query_start = query_start or ""
    normalized_query_end = query_end or ""
    if normalized_query_end and normalized_entry_start and normalized_entry_start > normalized_query_end:
        return False
    if normalized_query_start and normalized_entry_end and normalized_entry_end < normalized_query_start:
        return False
    return True


# endregion


# region storage
class LanceDbLongTermMemoryStore:
    """LanceDbLongTermMemoryStore 表示 Core SimpleMem 的单一存储实现.

    Attributes:
        root_dir (Path): LanceDB 数据目录.
    """

    def __init__(self, root_dir: str | Path) -> None:
        """初始化 LanceDB 存储层.

        Args:
            root_dir: LanceDB 根目录.
        """

        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self.root_dir))
        self._entries = self._ensure_table("memory_entries", _entry_table_schema())
        self._entries.create_fts_index("lexical_text", replace=True)
        self._cursors = self._ensure_table("thread_cursors", _cursor_table_schema())
        self._failed_windows = self._ensure_table("failed_windows", _failed_window_table_schema())

    def upsert_entries(
        self,
        entries: list[MemoryEntry],
        *,
        vectors: list[list[float]] | None = None,
    ) -> None:
        """把一批 entry 写入主表.

        Args:
            entries: 待写入的长期记忆对象列表.
            vectors: 预留给向量列的并行向量列表. 当前版本先不落表.
        """

        _ = vectors
        current_rows = {
            str(row.get("entry_id", "") or ""): row
            for row in self._entries.to_arrow().to_pylist()
        }
        vector_rows = list(vectors or [])
        for index, entry in enumerate(entries):
            incoming_row = _entry_to_record(
                entry,
                vector=vector_rows[index] if index < len(vector_rows) else None,
            )
            current_rows[entry.entry_id] = _merge_entry_record(
                current_rows.get(entry.entry_id),
                incoming_row,
            )
        self._normalize_entry_vectors(list(current_rows.values()))
        self._rewrite_entries_table(list(current_rows.values()))

    def get_entry(self, entry_id: str) -> MemoryEntry | None:
        """按 `entry_id` 读取一条 entry.

        Args:
            entry_id: 目标 entry 主键.

        Returns:
            对应的长期记忆对象, 如果不存在则返回 None.
        """

        rows = (
            self._entries.search()
            .where(f"entry_id = '{_quote_sql_text(entry_id)}'")
            .limit(1)
            .to_list()
        )
        if not rows:
            return None
        return _record_to_entry(rows[0])

    def keyword_search(
        self,
        query_text: str,
        *,
        conversation_id: str,
        limit: int,
    ) -> list[MemoryEntry]:
        """执行词法检索.

        Args:
            query_text: 词法查询文本.
            conversation_id: 目标对话容器.
            limit: 返回条数上限.

        Returns:
            命中的长期记忆对象列表.
        """

        if not _normalize_text(query_text):
            return []
        rows = (
            self._entries.search(query_text, query_type="fts")
            .where(f"conversation_id = '{_quote_sql_text(conversation_id)}'")
            .limit(limit)
            .to_list()
        )
        return [_record_to_entry(row) for row in rows]

    def semantic_search(
        self,
        query_vector: list[float],
        *,
        conversation_id: str,
        limit: int,
    ) -> list[MemoryEntry]:
        """执行向量语义检索.

        Args:
            query_vector: 查询向量.
            conversation_id: 目标对话容器.
            limit: 返回条数上限.

        Returns:
            命中的长期记忆对象列表.
        """

        normalized_query = [float(value) for value in list(query_vector or [])]
        if not normalized_query:
            return []
        rows = (
            self._entries.search()
            .where(f"conversation_id = '{_quote_sql_text(conversation_id)}'")
            .limit(10_000)
            .to_list()
        )
        scored_rows: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            vector = [float(value) for value in list(row.get("vector", []) or [])]
            if not bool(row.get("has_vector", False)):
                continue
            if not vector or len(vector) != len(normalized_query):
                continue
            score = _cosine_similarity(normalized_query, vector)
            scored_rows.append((score, row))
        scored_rows.sort(
            key=lambda item: (item[0], int(item[1].get("updated_at", 0) or 0)),
            reverse=True,
        )
        return [_record_to_entry(row) for _score, row in scored_rows[:limit]]

    def structured_search(
        self,
        *,
        conversation_id: str,
        persons: list[str],
        entities: list[str],
        location: str | None,
        time_range: tuple[str | None, str | None] | None,
        limit: int,
    ) -> list[MemoryEntry]:
        """执行结构字段检索.

        Args:
            conversation_id: 目标对话容器.
            persons: 要求命中的人物列表.
            entities: 要求命中的实体列表.
            location: 可选地点条件.
            time_range: 可选时间区间条件.
            limit: 返回条数上限.

        Returns:
            命中的长期记忆对象列表.
        """

        rows = (
            self._entries.search()
            .where(f"conversation_id = '{_quote_sql_text(conversation_id)}'")
            .limit(10_000)
            .to_list()
        )
        normalized_persons = {_normalize_text(item) for item in list(persons or []) if _normalize_text(item)}
        normalized_entities = {_normalize_text(item) for item in list(entities or []) if _normalize_text(item)}
        normalized_location = _normalize_text(location) or None
        query_start, query_end = time_range or (None, None)

        matched: list[MemoryEntry] = []
        for row in rows:
            entry = _record_to_entry(row)
            if normalized_persons and not normalized_persons.issubset(set(entry.persons)):
                continue
            if normalized_entities and not normalized_entities.issubset(set(entry.entities)):
                continue
            if normalized_location and _normalize_text(entry.location) != normalized_location:
                continue
            if not _time_overlaps(
                query_start=query_start,
                query_end=query_end,
                entry_time_point=entry.time_point,
                entry_interval_start=entry.time_interval_start,
                entry_interval_end=entry.time_interval_end,
            ):
                continue
            matched.append(entry)

        matched.sort(key=lambda item: item.updated_at, reverse=True)
        return matched[:limit]

    def save_cursor(self, cursor: ThreadLtmCursor) -> None:
        """保存一个 thread 的写入游标.

        Args:
            cursor: 待保存游标.
        """

        current_rows = {
            str(row.get("thread_id", "") or ""): row
            for row in self._cursors.to_arrow().to_pylist()
        }
        current_rows[cursor.thread_id] = _cursor_to_record(cursor)
        self._rewrite_table(
            table_name="thread_cursors",
            schema=_cursor_table_schema(),
            rows=list(current_rows.values()),
        )
        self._cursors = self._db.open_table("thread_cursors")

    def load_cursor(self, thread_id: str) -> ThreadLtmCursor | None:
        """读取一个 thread 的写入游标.

        Args:
            thread_id: 目标 thread.

        Returns:
            当前游标, 如果不存在则返回 None.
        """

        rows = (
            self._cursors.search()
            .where(f"thread_id = '{_quote_sql_text(thread_id)}'")
            .limit(1)
            .to_list()
        )
        if not rows:
            return None
        return _record_to_cursor(rows[0])

    def save_failed_window(self, record: FailedWindowRecord) -> None:
        """保存一个失败窗口.

        Args:
            record: 待保存的失败窗口对象.
        """

        current_rows = {
            str(row.get("window_id", "") or ""): row
            for row in self._failed_windows.to_arrow().to_pylist()
        }
        current_rows[record.window_id] = _failed_window_to_record(record)
        self._rewrite_table(
            table_name="failed_windows",
            schema=_failed_window_table_schema(),
            rows=list(current_rows.values()),
        )
        self._failed_windows = self._db.open_table("failed_windows")

    def list_failed_windows(self, conversation_id: str) -> list[FailedWindowRecord]:
        """列出一个对话容器下的失败窗口.

        Args:
            conversation_id: 目标对话容器.

        Returns:
            对应的失败窗口列表.
        """

        rows = (
            self._failed_windows.search()
            .where(f"conversation_id = '{_quote_sql_text(conversation_id)}'")
            .limit(10_000)
            .to_list()
        )
        items = [_record_to_failed_window(row) for row in rows]
        items.sort(key=lambda item: item.last_failed_at, reverse=True)
        return items

    def load_failed_window(self, window_id: str) -> FailedWindowRecord | None:
        """按 `window_id` 读取一个失败窗口.

        Args:
            window_id: 目标失败窗口主键.

        Returns:
            对应的失败窗口对象, 不存在则返回 None.
        """

        rows = (
            self._failed_windows.search()
            .where(f"window_id = '{_quote_sql_text(window_id)}'")
            .limit(1)
            .to_list()
        )
        if not rows:
            return None
        return _record_to_failed_window(rows[0])

    def _ensure_table(self, table_name: str, schema: pa.Schema):
        """确保一个 LanceDB 表存在.

        Args:
            table_name: 表名.
            schema: 目标 schema.

        Returns:
            对应的 LanceDB table 对象.
        """

        return self._db.create_table(
            table_name,
            schema=schema,
            exist_ok=True,
        )

    def _rewrite_entries_table(self, rows: list[dict[str, Any]]) -> None:
        """整表重写长期记忆主表并刷新 FTS 索引.

        Args:
            rows: 当前全量 entry 行数据.
        """

        self._rewrite_table(
            table_name="memory_entries",
            schema=_entry_table_schema(),
            rows=rows,
        )
        self._entries = self._db.open_table("memory_entries")
        self._entries.create_fts_index("lexical_text", replace=True)

    def _normalize_entry_vectors(self, rows: list[dict[str, Any]]) -> None:
        """把 entry 行里的向量列规范到同一维度.

        Args:
            rows: 当前全量 entry 行数据.
        """

        target_dim = 0
        for row in rows:
            vector = [float(value) for value in list(row.get("vector", []) or [])]
            if vector:
                target_dim = len(vector)
                break
        if target_dim <= 0:
            target_dim = 1
        for row in rows:
            vector = [float(value) for value in list(row.get("vector", []) or [])]
            if vector and len(vector) != target_dim:
                raise ValueError("all vectors in memory_entries must share one dimension")
            if vector:
                row["vector"] = vector
                row["has_vector"] = True
                continue
            row["vector"] = [0.0] * target_dim
            row["has_vector"] = False

    def _rewrite_table(
        self,
        *,
        table_name: str,
        schema: pa.Schema,
        rows: list[dict[str, Any]],
    ) -> None:
        """用当前全量行数据整表重写一个 LanceDB 表.

        Args:
            table_name: 目标表名.
            schema: 对应 schema.
            rows: 全量行数据.
        """

        table_data = pa.Table.from_pylist(list(rows), schema=schema)
        self._db.create_table(
            table_name,
            data=table_data,
            schema=schema,
            mode="overwrite",
        )


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    """计算两条向量的余弦相似度.

    Args:
        left: 左侧向量.
        right: 右侧向量.

    Returns:
        余弦相似度分数.
    """

    numerator = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


# endregion


__all__ = ["LanceDbLongTermMemoryStore"]
