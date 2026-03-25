"""runtime.sqlite_stores 提供 runtime store 的 SQLite 实现.

目前覆盖五类持久化:
- ChannelEventStore
- MemoryStore
- MessageStore
- ThreadStore
- RunStore
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from ..contracts import (
    ChannelEventRecord,
    MemoryItem,
    MessageRecord,
    RunRecord,
    RunStep,
    SequencedChannelEventRecord,
    SequencedMessageRecord,
    ThreadRecord,
)
from .stores import ChannelEventStore, MemoryStore, MessageStore, RunStore, ThreadStore


# region base
class _SQLiteStoreBase:
    """SQLite store 的共享基础设施.

    这个基类负责:
    - 创建数据库目录
    - 初始化 SQLite 连接
    - 设置基础 PRAGMA
    """

    def __init__(self, db_path: str | Path) -> None:
        """初始化 SQLite 连接.

        Args:
            db_path: SQLite 数据库文件路径.
        """

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

    def close(self) -> None:
        """关闭 SQLite 连接."""

        self._conn.close()

    @staticmethod
    def _encode_json(value: Any) -> str:
        """把 Python 对象编码成 JSON 字符串.

        Args:
            value: 待编码的 Python 对象.

        Returns:
            对应的 JSON 文本.
        """

        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode_json(raw: str | None) -> Any:
        """把 JSON 字符串解码成 Python 对象.

        Args:
            raw: 原始 JSON 文本.

        Returns:
            解码后的 Python 对象. 空值时返回空 dict.
        """

        if not raw:
            return {}
        return json.loads(raw)


# endregion


# region thread store
class SQLiteThreadStore(_SQLiteStoreBase, ThreadStore):
    """基于 SQLite 的 ThreadStore."""

    def __init__(self, db_path: str | Path) -> None:
        """初始化 SQLiteThreadStore.

        Args:
            db_path: SQLite 数据库文件路径.
        """

        super().__init__(db_path)
        self._ensure_schema()

    async def get(self, thread_id: str) -> ThreadRecord | None:
        """按 thread_id 获取 thread 持久化记录.

        Args:
            thread_id: 目标 thread_id.

        Returns:
            命中的 ThreadRecord, 或 None.
        """

        async with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    thread_id,
                    channel_scope,
                    thread_kind,
                    working_messages_json,
                    working_summary,
                    last_event_at,
                    metadata_json
                FROM threads
                WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=str(row["thread_id"]),
            channel_scope=str(row["channel_scope"]),
            thread_kind=str(row["thread_kind"]),
            working_messages=list(self._decode_json(row["working_messages_json"])),
            working_summary=str(row["working_summary"]),
            last_event_at=int(row["last_event_at"]),
            metadata=dict(self._decode_json(row["metadata_json"])),
        )

    async def upsert(self, thread: ThreadRecord) -> None:
        """插入或更新一条 thread 持久化记录.

        Args:
            thread: 待写入的 ThreadRecord.
        """

        async with self._lock:
            self._conn.execute(
                """
                INSERT INTO threads (
                    thread_id,
                    channel_scope,
                    thread_kind,
                    working_messages_json,
                    working_summary,
                    last_event_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    channel_scope = excluded.channel_scope,
                    thread_kind = excluded.thread_kind,
                    working_messages_json = excluded.working_messages_json,
                    working_summary = excluded.working_summary,
                    last_event_at = excluded.last_event_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    thread.thread_id,
                    thread.channel_scope,
                    thread.thread_kind,
                    self._encode_json(thread.working_messages),
                    thread.working_summary,
                    thread.last_event_at,
                    self._encode_json(thread.metadata),
                ),
            )
            self._conn.commit()

    async def list_threads(self, *, limit: int | None = None) -> list[ThreadRecord]:
        """按最近活跃时间倒序列出 threads."""

        sql = """
            SELECT
                thread_id,
                channel_scope,
                thread_kind,
                working_messages_json,
                working_summary,
                last_event_at,
                metadata_json
            FROM threads
            ORDER BY last_event_at DESC, thread_id ASC
        """
        params: list[object] = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        async with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [
            ThreadRecord(
                thread_id=str(row["thread_id"]),
                channel_scope=str(row["channel_scope"]),
                thread_kind=str(row["thread_kind"]),
                working_messages=list(self._decode_json(row["working_messages_json"])),
                working_summary=str(row["working_summary"]),
                last_event_at=int(row["last_event_at"]),
                metadata=dict(self._decode_json(row["metadata_json"])),
            )
            for row in rows
        ]

    def _ensure_schema(self) -> None:
        """初始化 threads 表结构."""

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                thread_id TEXT PRIMARY KEY,
                channel_scope TEXT NOT NULL,
                thread_kind TEXT NOT NULL,
                working_messages_json TEXT NOT NULL,
                working_summary TEXT NOT NULL,
                last_event_at INTEGER NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        self._conn.commit()


# endregion


# region event store
class SQLiteChannelEventStore(_SQLiteStoreBase, ChannelEventStore):
    """基于 SQLite 的 ChannelEventStore."""

    def __init__(self, db_path: str | Path) -> None:
        """初始化 SQLiteChannelEventStore.

        Args:
            db_path: SQLite 数据库文件路径.
        """

        super().__init__(db_path)
        self._ensure_schema()

    async def save(self, event: ChannelEventRecord) -> None:
        """保存一条 ChannelEventRecord.

        Args:
            event: 待写入的 ChannelEventRecord.
        """

        async with self._lock:
            existing = self._load_existing_event(event.event_uid)
            if existing is not None:
                if existing != event:
                    raise ValueError(f"channel event '{event.event_uid}' already exists with different content")
                return
            self._conn.execute(
                """
                INSERT INTO channel_events (
                    event_uid,
                    thread_id,
                    actor_id,
                    channel_scope,
                    platform,
                    event_type,
                    message_type,
                    content_text,
                    payload_json,
                    timestamp,
                    run_id,
                    raw_message_id,
                    operator_id,
                    target_message_id,
                    metadata_json,
                    raw_event_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_uid,
                    event.thread_id,
                    event.actor_id,
                    event.channel_scope,
                    event.platform,
                    event.event_type,
                    event.message_type,
                    event.content_text,
                    self._encode_json(event.payload_json),
                    event.timestamp,
                    event.run_id,
                    event.raw_message_id,
                    event.operator_id,
                    event.target_message_id,
                    self._encode_json(event.metadata),
                    self._encode_json(event.raw_event),
                ),
            )
            self._conn.commit()

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
            thread_id: 目标 thread_id.
            limit: 最多返回多少条事件.
            since: 只返回晚于该时间戳的事件.
            event_types: 可选事件类型过滤列表.

        Returns:
            满足条件的 ChannelEventRecord 列表.
        """

        query = [
            """
            SELECT
                event_uid,
                thread_id,
                actor_id,
                channel_scope,
                platform,
                event_type,
                message_type,
                content_text,
                payload_json,
                timestamp,
                run_id,
                raw_message_id,
                operator_id,
                target_message_id,
                metadata_json,
                raw_event_json
            FROM channel_events
            WHERE thread_id = ?
            """
        ]
        params: list[object] = [thread_id]

        if since is not None:
            query.append("AND timestamp > ?")
            params.append(since)

        if event_types is not None:
            if not event_types:
                return []
            placeholders = ", ".join("?" for _ in event_types)
            query.append(f"AND event_type IN ({placeholders})")
            params.extend(event_types)

        if limit is None:
            query.append("ORDER BY timestamp ASC, event_uid ASC")
            async with self._lock:
                rows = self._conn.execute("\n".join(query), tuple(params)).fetchall()
            return [self._row_to_event(row) for row in rows]

        query.append("ORDER BY timestamp DESC, event_uid DESC")
        query.append("LIMIT ?")
        params.append(limit)
        async with self._lock:
            rows = self._conn.execute("\n".join(query), tuple(params)).fetchall()
        rows.reverse()
        return [self._row_to_event(row) for row in rows]

    async def get_thread_events_after_sequence(
        self,
        thread_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
        event_types: list[str] | None = None,
    ) -> list[SequencedChannelEventRecord]:
        """按 sequence 查询 thread 的事件增量.

        Args:
            thread_id: 目标 thread_id.
            after_sequence: 只返回大于该 sequence 的事件.
            limit: 最多返回多少条事件.
            event_types: 可选事件类型过滤列表.

        Returns:
            满足条件的带 sequence 事件列表.
        """

        query = [
            """
            SELECT
                rowid AS sequence_id,
                event_uid,
                thread_id,
                actor_id,
                channel_scope,
                platform,
                event_type,
                message_type,
                content_text,
                payload_json,
                timestamp,
                run_id,
                raw_message_id,
                operator_id,
                target_message_id,
                metadata_json,
                raw_event_json
            FROM channel_events
            WHERE thread_id = ?
            """
        ]
        params: list[object] = [thread_id]

        if after_sequence is not None:
            query.append("AND rowid > ?")
            params.append(after_sequence)

        if event_types is not None:
            if not event_types:
                return []
            placeholders = ", ".join("?" for _ in event_types)
            query.append(f"AND event_type IN ({placeholders})")
            params.extend(event_types)

        query.append("ORDER BY rowid ASC")
        if limit is not None:
            query.append("LIMIT ?")
            params.append(limit)

        async with self._lock:
            rows = self._conn.execute("\n".join(query), tuple(params)).fetchall()
        return [self._row_to_sequenced_event(row) for row in rows]

    def _ensure_schema(self) -> None:
        """初始化 channel_events 表结构."""

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS channel_events (
                event_uid TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                channel_scope TEXT NOT NULL,
                platform TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message_type TEXT NOT NULL,
                content_text TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                run_id TEXT,
                raw_message_id TEXT NOT NULL,
                operator_id TEXT,
                target_message_id TEXT,
                metadata_json TEXT NOT NULL,
                raw_event_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_events_thread_timestamp ON channel_events(thread_id, timestamp)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_events_run_id ON channel_events(run_id)"
        )
        self._conn.commit()

    def _row_to_event(self, row: sqlite3.Row) -> ChannelEventRecord:
        """把 SQLite 行对象转换成 ChannelEventRecord.

        Args:
            row: SQLite 查询返回的行对象.

        Returns:
            对应的 ChannelEventRecord.
        """

        return ChannelEventRecord(
            event_uid=str(row["event_uid"]),
            thread_id=str(row["thread_id"]),
            actor_id=str(row["actor_id"]),
            channel_scope=str(row["channel_scope"]),
            platform=str(row["platform"]),
            event_type=str(row["event_type"]),
            message_type=str(row["message_type"]),
            content_text=str(row["content_text"]),
            payload_json=dict(self._decode_json(row["payload_json"])),
            timestamp=int(row["timestamp"]),
            run_id=str(row["run_id"]) if row["run_id"] is not None else None,
            raw_message_id=str(row["raw_message_id"]),
            operator_id=str(row["operator_id"]) if row["operator_id"] is not None else None,
            target_message_id=(
                str(row["target_message_id"]) if row["target_message_id"] is not None else None
            ),
            metadata=dict(self._decode_json(row["metadata_json"])),
            raw_event=dict(self._decode_json(row["raw_event_json"])),
        )

    def _load_existing_event(self, event_uid: str) -> ChannelEventRecord | None:
        """读取一个已有的事件事实.

        Args:
            event_uid: 事件主键.

        Returns:
            已存在的事件记录; 如果还没有则返回 None.
        """

        row = self._conn.execute(
            """
            SELECT
                event_uid,
                thread_id,
                actor_id,
                channel_scope,
                platform,
                event_type,
                message_type,
                content_text,
                payload_json,
                timestamp,
                run_id,
                raw_message_id,
                operator_id,
                target_message_id,
                metadata_json,
                raw_event_json
            FROM channel_events
            WHERE event_uid = ?
            """,
            (event_uid,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_event(row)

    def _row_to_sequenced_event(self, row: sqlite3.Row) -> SequencedChannelEventRecord:
        """把 SQLite 行对象转换成带 sequence 的事件记录.

        Args:
            row: SQLite 查询返回的行对象.

        Returns:
            对应的带 sequence 事件记录.
        """

        return SequencedChannelEventRecord(
            sequence_id=int(row["sequence_id"]),
            record=self._row_to_event(row),
        )


# endregion


# region memory store
class SQLiteMemoryStore(_SQLiteStoreBase, MemoryStore):
    """基于 SQLite 的 MemoryStore."""

    def __init__(self, db_path: str | Path) -> None:
        """初始化 SQLiteMemoryStore.

        Args:
            db_path: SQLite 数据库文件路径.
        """

        super().__init__(db_path)
        self._ensure_schema()

    async def upsert(self, item: MemoryItem) -> None:
        """插入或更新一条长期记忆项.

        Args:
            item: 待写入的 MemoryItem.
        """

        async with self._lock:
            self._conn.execute(
                """
                INSERT INTO memory_items (
                    memory_id,
                    scope,
                    scope_key,
                    memory_type,
                    content,
                    edit_mode,
                    author,
                    confidence,
                    source_run_id,
                    source_event_id,
                    tags_json,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    scope = excluded.scope,
                    scope_key = excluded.scope_key,
                    memory_type = excluded.memory_type,
                    content = excluded.content,
                    edit_mode = excluded.edit_mode,
                    author = excluded.author,
                    confidence = excluded.confidence,
                    source_run_id = excluded.source_run_id,
                    source_event_id = excluded.source_event_id,
                    tags_json = excluded.tags_json,
                    metadata_json = excluded.metadata_json,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    item.memory_id,
                    item.scope,
                    item.scope_key,
                    item.memory_type,
                    item.content,
                    item.edit_mode,
                    item.author,
                    item.confidence,
                    item.source_run_id,
                    item.source_event_id,
                    self._encode_json(item.tags),
                    self._encode_json(item.metadata),
                    item.created_at,
                    item.updated_at,
                ),
            )
            self._conn.commit()

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

        query = [
            """
            SELECT
                memory_id,
                scope,
                scope_key,
                memory_type,
                content,
                edit_mode,
                author,
                confidence,
                source_run_id,
                source_event_id,
                tags_json,
                metadata_json,
                created_at,
                updated_at
            FROM memory_items
            WHERE scope = ?
              AND scope_key = ?
            """
        ]
        params: list[object] = [scope, scope_key]

        if memory_types:
            placeholders = ", ".join("?" for _ in memory_types)
            query.append(f"AND memory_type IN ({placeholders})")
            params.extend(memory_types)

        query.append("ORDER BY updated_at DESC, created_at DESC, memory_id DESC")
        if limit is not None:
            query.append("LIMIT ?")
            params.append(limit)

        async with self._lock:
            rows = self._conn.execute("\n".join(query), tuple(params)).fetchall()
        return [self._row_to_memory_item(row) for row in rows]

    async def delete(self, memory_id: str) -> bool:
        """按 memory_id 删除一条长期记忆项.

        Args:
            memory_id: 目标 memory_id.

        Returns:
            当前记忆是否存在并已删除.
        """

        async with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM memory_items WHERE memory_id = ?",
                (memory_id,),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def _ensure_schema(self) -> None:
        """初始化 memory_items 表结构."""

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_items (
                memory_id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                edit_mode TEXT NOT NULL,
                author TEXT NOT NULL,
                confidence REAL NOT NULL,
                source_run_id TEXT,
                source_event_id TEXT,
                tags_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_items_scope_updated ON memory_items(scope, scope_key, updated_at)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_items_type ON memory_items(memory_type)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_items_source_run ON memory_items(source_run_id)"
        )
        self._conn.commit()

    def _row_to_memory_item(self, row: sqlite3.Row) -> MemoryItem:
        """把 SQLite 行对象转换成 MemoryItem.

        Args:
            row: SQLite 查询返回的行对象.

        Returns:
            对应的 MemoryItem.
        """

        return MemoryItem(
            memory_id=str(row["memory_id"]),
            scope=str(row["scope"]),
            scope_key=str(row["scope_key"]),
            memory_type=str(row["memory_type"]),
            content=str(row["content"]),
            edit_mode=str(row["edit_mode"]),
            author=str(row["author"]),
            confidence=float(row["confidence"]),
            source_run_id=(
                None if row["source_run_id"] is None else str(row["source_run_id"])
            ),
            source_event_id=(
                None if row["source_event_id"] is None else str(row["source_event_id"])
            ),
            tags=list(self._decode_json(row["tags_json"])),
            metadata=dict(self._decode_json(row["metadata_json"])),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )


# endregion


# region message store
class SQLiteMessageStore(_SQLiteStoreBase, MessageStore):
    """基于 SQLite 的 MessageStore."""

    def __init__(self, db_path: str | Path) -> None:
        """初始化 SQLiteMessageStore.

        Args:
            db_path: SQLite 数据库文件路径.
        """

        super().__init__(db_path)
        self._ensure_schema()

    async def save(self, msg: MessageRecord) -> None:
        """保存一条 MessageRecord.

        Args:
            msg: 待写入的 MessageRecord.
        """

        async with self._lock:
            existing = self._load_existing_message(msg.message_uid)
            if existing is not None:
                if existing != msg:
                    raise ValueError(f"message '{msg.message_uid}' already exists with different content")
                return
            self._conn.execute(
                """
                INSERT INTO messages (
                    message_uid,
                    thread_id,
                    actor_id,
                    platform,
                    role,
                    content_text,
                    content_json,
                    timestamp,
                    run_id,
                    platform_message_id,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg.message_uid,
                    msg.thread_id,
                    msg.actor_id,
                    msg.platform,
                    msg.role,
                    msg.content_text,
                    self._encode_json(msg.content_json),
                    msg.timestamp,
                    msg.run_id,
                    msg.platform_message_id,
                    self._encode_json(msg.metadata),
                ),
            )
            self._conn.commit()

    async def get_thread_messages(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
        since: int | None = None,
    ) -> list[MessageRecord]:
        """按 thread 查询消息事实记录.

        Args:
            thread_id: 目标 thread_id.
            limit: 最多返回多少条消息.
            since: 只返回晚于该时间戳的消息.

        Returns:
            满足条件的 MessageRecord 列表.
        """

        query = [
            """
            SELECT
                message_uid,
                thread_id,
                actor_id,
                platform,
                role,
                content_text,
                content_json,
                timestamp,
                run_id,
                platform_message_id,
                metadata_json
            FROM messages
            WHERE thread_id = ?
            """
        ]
        params: list[object] = [thread_id]

        if since is not None:
            query.append("AND timestamp > ?")
            params.append(since)

        if limit is None:
            query.append("ORDER BY timestamp ASC, message_uid ASC")
            async with self._lock:
                rows = self._conn.execute(
                    "\n".join(query),
                    tuple(params),
                ).fetchall()
            return [self._row_to_message(row) for row in rows]

        query.append("ORDER BY timestamp DESC, message_uid DESC")
        query.append("LIMIT ?")
        params.append(limit)
        async with self._lock:
            rows = self._conn.execute(
                "\n".join(query),
                tuple(params),
            ).fetchall()
        rows.reverse()
        return [self._row_to_message(row) for row in rows]

    async def get_thread_messages_after_sequence(
        self,
        thread_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[SequencedMessageRecord]:
        """按 sequence 查询 thread 的消息增量.

        Args:
            thread_id: 目标 thread_id.
            after_sequence: 只返回大于该 sequence 的消息.
            limit: 最多返回多少条消息.

        Returns:
            满足条件的带 sequence 消息列表.
        """

        query = [
            """
            SELECT
                rowid AS sequence_id,
                message_uid,
                thread_id,
                actor_id,
                platform,
                role,
                content_text,
                content_json,
                timestamp,
                run_id,
                platform_message_id,
                metadata_json
            FROM messages
            WHERE thread_id = ?
            """
        ]
        params: list[object] = [thread_id]

        if after_sequence is not None:
            query.append("AND rowid > ?")
            params.append(after_sequence)

        query.append("ORDER BY rowid ASC")
        if limit is not None:
            query.append("LIMIT ?")
            params.append(limit)

        async with self._lock:
            rows = self._conn.execute("\n".join(query), tuple(params)).fetchall()
        return [self._row_to_sequenced_message(row) for row in rows]

    def _ensure_schema(self) -> None:
        """初始化 messages 表结构."""

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                message_uid TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                role TEXT NOT NULL,
                content_text TEXT NOT NULL,
                content_json TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                run_id TEXT,
                platform_message_id TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_thread_timestamp ON messages(thread_id, timestamp)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_run_id ON messages(run_id)"
        )
        self._conn.commit()

    def _row_to_message(self, row: sqlite3.Row) -> MessageRecord:
        """把 SQLite 行对象转换成 MessageRecord.

        Args:
            row: SQLite 查询返回的行对象.

        Returns:
            对应的 MessageRecord.
        """

        return MessageRecord(
            message_uid=str(row["message_uid"]),
            thread_id=str(row["thread_id"]),
            actor_id=str(row["actor_id"]),
            platform=str(row["platform"]),
            role=str(row["role"]),
            content_text=str(row["content_text"]),
            content_json=dict(self._decode_json(row["content_json"])),
            timestamp=int(row["timestamp"]),
            run_id=None if row["run_id"] is None else str(row["run_id"]),
            platform_message_id=str(row["platform_message_id"]),
            metadata=dict(self._decode_json(row["metadata_json"])),
        )

    def _load_existing_message(self, message_uid: str) -> MessageRecord | None:
        """读取一个已有的消息事实.

        Args:
            message_uid: 消息主键.

        Returns:
            已存在的消息记录; 如果还没有则返回 None.
        """

        row = self._conn.execute(
            """
            SELECT
                message_uid,
                thread_id,
                actor_id,
                platform,
                role,
                content_text,
                content_json,
                timestamp,
                run_id,
                platform_message_id,
                metadata_json
            FROM messages
            WHERE message_uid = ?
            """,
            (message_uid,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_message(row)

    def _row_to_sequenced_message(self, row: sqlite3.Row) -> SequencedMessageRecord:
        """把 SQLite 行对象转换成带 sequence 的消息记录.

        Args:
            row: SQLite 查询返回的行对象.

        Returns:
            对应的带 sequence 消息记录.
        """

        return SequencedMessageRecord(
            sequence_id=int(row["sequence_id"]),
            record=self._row_to_message(row),
        )


# endregion


# region run store
class SQLiteRunStore(_SQLiteStoreBase, RunStore):
    """基于 SQLite 的 RunStore."""

    def __init__(self, db_path: str | Path) -> None:
        """初始化 SQLiteRunStore.

        Args:
            db_path: SQLite 数据库文件路径.
        """

        super().__init__(db_path)
        self._ensure_schema()

    async def create_run(self, run: RunRecord) -> None:
        """创建一条新的 run 记录.

        Args:
            run: 待创建的 RunRecord.
        """

        async with self._lock:
            self._conn.execute(
                """
                INSERT INTO runs (
                    run_id,
                    thread_id,
                    actor_id,
                    agent_id,
                    trigger_event_id,
                    status,
                    started_at,
                    finished_at,
                    error,
                    approval_context_json,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.thread_id,
                    run.actor_id,
                    run.agent_id,
                    run.trigger_event_id,
                    run.status,
                    run.started_at,
                    run.finished_at,
                    run.error,
                    self._encode_json(run.approval_context),
                    self._encode_json(run.metadata),
                ),
            )
            self._conn.commit()

    async def get_run(self, run_id: str) -> RunRecord | None:
        """按 run_id 获取一条 run 记录.

        Args:
            run_id: 目标 run_id.

        Returns:
            命中的 RunRecord, 或 None.
        """

        async with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    run_id,
                    thread_id,
                    actor_id,
                    agent_id,
                    trigger_event_id,
                    status,
                    started_at,
                    finished_at,
                    error,
                    approval_context_json,
                    metadata_json
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    async def update_run(self, run: RunRecord) -> None:
        """更新一条已有的 run 记录.

        Args:
            run: 待更新的 RunRecord.
        """

        async with self._lock:
            self._conn.execute(
                """
                UPDATE runs
                SET
                    thread_id = ?,
                    actor_id = ?,
                    agent_id = ?,
                    trigger_event_id = ?,
                    status = ?,
                    started_at = ?,
                    finished_at = ?,
                    error = ?,
                    approval_context_json = ?,
                    metadata_json = ?
                WHERE run_id = ?
                """,
                (
                    run.thread_id,
                    run.actor_id,
                    run.agent_id,
                    run.trigger_event_id,
                    run.status,
                    run.started_at,
                    run.finished_at,
                    run.error,
                    self._encode_json(run.approval_context),
                    self._encode_json(run.metadata),
                    run.run_id,
                ),
            )
            self._conn.commit()

    async def list_active_runs(self, statuses: set[str]) -> list[RunRecord]:
        """按状态集合列出所有活跃 run.

        Args:
            statuses: 需要被视为活跃状态的 status 集合.

        Returns:
            所有活跃 RunRecord.
        """

        if not statuses:
            return []

        placeholders = ", ".join("?" for _ in statuses)
        async with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT
                    run_id,
                    thread_id,
                    actor_id,
                    agent_id,
                    trigger_event_id,
                    status,
                    started_at,
                    finished_at,
                    error,
                    approval_context_json,
                    metadata_json
                FROM runs
                WHERE status IN ({placeholders})
                ORDER BY started_at ASC
                """,
                tuple(statuses),
            ).fetchall()
        return [self._row_to_run(row) for row in rows]

    async def list_runs(
        self,
        *,
        limit: int | None = None,
        statuses: set[str] | None = None,
        thread_id: str | None = None,
    ) -> list[RunRecord]:
        """按条件列出 runs."""

        where = ["1 = 1"]
        params: list[object] = []
        if thread_id:
            where.append("thread_id = ?")
            params.append(thread_id)
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            where.append(f"status IN ({placeholders})")
            params.extend(sorted(statuses))
        sql = (
            """
            SELECT
                run_id,
                thread_id,
                actor_id,
                agent_id,
                trigger_event_id,
                status,
                started_at,
                finished_at,
                error,
                approval_context_json,
                metadata_json
            FROM runs
            WHERE
            """
            + " AND ".join(where)
            + " ORDER BY started_at DESC, run_id DESC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        async with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_run(row) for row in rows]

    async def append_step(self, step: RunStep) -> None:
        """追加一条 run step 审计记录.

        Args:
            step: 待追加的 RunStep.
        """

        async with self._lock:
            self._conn.execute(
                """
                INSERT INTO run_steps (
                    step_id,
                    run_id,
                    thread_id,
                    step_type,
                    status,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step.step_id,
                    step.run_id,
                    step.thread_id,
                    step.step_type,
                    step.status,
                    self._encode_json(step.payload),
                    step.created_at,
                ),
            )
            self._conn.commit()

    async def get_run_steps(
        self,
        run_id: str,
        *,
        limit: int | None = None,
        step_types: list[str] | None = None,
    ) -> list[RunStep]:
        where = ["run_id = ?"]
        params: list[object] = [run_id]
        if step_types:
            placeholders = ", ".join("?" for _ in step_types)
            where.append(f"step_type IN ({placeholders})")
            params.extend(step_types)
        sql = (
            "SELECT step_id, run_id, thread_id, step_type, status, payload_json, created_at "
            f"FROM run_steps WHERE {' AND '.join(where)} ORDER BY created_at ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        async with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_step(row) for row in rows]

    async def get_thread_steps(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
        step_types: list[str] | None = None,
    ) -> list[RunStep]:
        where = ["thread_id = ?"]
        params: list[object] = [thread_id]
        if step_types:
            placeholders = ", ".join("?" for _ in step_types)
            where.append(f"step_type IN ({placeholders})")
            params.extend(step_types)
        sql = (
            "SELECT step_id, run_id, thread_id, step_type, status, payload_json, created_at "
            f"FROM run_steps WHERE {' AND '.join(where)} ORDER BY created_at ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        async with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_step(row) for row in rows]

    def _ensure_schema(self) -> None:
        """初始化 runs 和 run_steps 表结构."""

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                trigger_event_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at INTEGER NOT NULL,
                finished_at INTEGER,
                error TEXT,
                approval_context_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_steps (
                step_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                step_type TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_status_started_at ON runs(status, started_at)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_run_steps_thread_created_at ON run_steps(thread_id, created_at)"
        )
        self._conn.commit()

    def _row_to_run(self, row: sqlite3.Row) -> RunRecord:
        """把 SQLite 行对象转换成 RunRecord.

        Args:
            row: SQLite 查询返回的行对象.

        Returns:
            对应的 RunRecord.
        """

        return RunRecord(
            run_id=str(row["run_id"]),
            thread_id=str(row["thread_id"]),
            actor_id=str(row["actor_id"]),
            agent_id=str(row["agent_id"]),
            trigger_event_id=str(row["trigger_event_id"]),
            status=str(row["status"]),
            started_at=int(row["started_at"]),
            finished_at=(
                None if row["finished_at"] is None else int(row["finished_at"])
            ),
            error=None if row["error"] is None else str(row["error"]),
            approval_context=dict(self._decode_json(row["approval_context_json"])),
            metadata=dict(self._decode_json(row["metadata_json"])),
        )

    def _row_to_step(self, row: sqlite3.Row) -> RunStep:
        return RunStep(
            step_id=str(row["step_id"]),
            run_id=str(row["run_id"]),
            thread_id=str(row["thread_id"]),
            step_type=str(row["step_type"]),
            status=str(row["status"]),
            payload=dict(self._decode_json(row["payload_json"])),
            created_at=int(row["created_at"]),
        )


# endregion
