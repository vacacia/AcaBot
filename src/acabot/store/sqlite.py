"""SQLiteMessageStore — 基于 aiosqlite 的消息持久化存储, 单表 WAL 模式.

使用的表:
    messages — 所有会话的聊天消息, 按 (session_key, timestamp) 索引.
        核心字段: session_key, role, content, timestamp
        发送者信息: sender_id, sender_name
        平台信息: message_id(用于撤回/回复引用)
        扩展: metadata_json(JSON, 存储富媒体/tool_call 等结构化数据)

query_raw 安全说明:
    封装时, 应再加一层清洗.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from .base import BaseMessageStore, StoredMessage

logger = logging.getLogger("acabot.store.sqlite")

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp INTEGER NOT NULL DEFAULT 0,
    sender_id TEXT NOT NULL DEFAULT '',
    sender_name TEXT NOT NULL DEFAULT '',
    message_id TEXT NOT NULL DEFAULT '',
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages(session_key, timestamp);
"""


class SQLiteMessageStore(BaseMessageStore):
    """SQLite 消息存储.

    Args:
        db_path: 数据库文件路径, 默认 "data/db/acabot.db".
    """

    def __init__(self, db_path: str = "data/db/acabot.db") -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """连接数据库, 启用 WAL 模式, 建表."""
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(_CREATE_TABLE)
        await self._db.commit()
        logger.info(f"SQLiteMessageStore initialized: {self.db_path}")

    async def close(self) -> None:
        """关闭数据库连接."""
        if self._db:
            await self._db.close()

    def _ensure_db(self) -> aiosqlite.Connection:
        """获取数据库连接, 未初始化时抛出 RuntimeError."""
        if not self._db:
            raise RuntimeError(
                "SQLiteMessageStore not initialized — call await store.initialize() first"
            )
        return self._db

    async def save(self, msg: StoredMessage) -> None:
        """持久化一条消息. metadata 序列化为 JSON."""
        db = self._ensure_db()
        await db.execute(
            "INSERT INTO messages"
            " (session_key, role, content, timestamp,"
            "  sender_id, sender_name, message_id, metadata_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg.session_key, msg.role, msg.content, msg.timestamp,
                msg.sender_id, msg.sender_name, msg.message_id,
                json.dumps(msg.metadata) if msg.metadata else None,
            ),
        )
        await db.commit()

    async def get_messages(
        self,
        session_key: str,
        limit: int | None = None,
        since: int | None = None,
    ) -> list[StoredMessage]:
        """查询指定会话的消息, 按时间正序返回.

        Args:
            session_key: 会话标识, 如 "qq:group:123".
            limit: 最多返回条数, None 不限制.
            since: 只返回 timestamp > since 的消息.
        """
        db = self._ensure_db()

        cols = "role, content, timestamp, sender_id, sender_name, message_id, metadata_json"

        if since is not None:
            cursor = await db.execute(
                f"SELECT {cols} FROM messages"
                " WHERE session_key = ? AND timestamp > ?"
                " ORDER BY timestamp ASC",
                (session_key, since),
            )
        elif limit is not None:
            cursor = await db.execute(
                f"SELECT {cols} FROM ("
                f"  SELECT {cols} FROM messages"
                "   WHERE session_key = ? ORDER BY timestamp DESC LIMIT ?"
                ") ORDER BY timestamp ASC",
                (session_key, limit),
            )
        else:
            cursor = await db.execute(
                f"SELECT {cols} FROM messages"
                " WHERE session_key = ? ORDER BY timestamp ASC",
                (session_key,),
            )

        return [self._row_to_msg(r, session_key) for r in await cursor.fetchall()]

    async def query_raw(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """通用只读查询, 只允许单条 SELECT. 封装为 tool 时需额外清洗.

        Raises:
            ValueError: 非 SELECT 语句或包含多条语句.
        """
        db = self._ensure_db()

        stripped = sql.strip().upper()
        if not stripped.startswith("SELECT"):
            raise ValueError("query_raw only allows SELECT statements")
        if ";" in sql:
            raise ValueError("query_raw does not allow multiple statements")

        cursor = await db.execute(sql, params)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return [dict(zip(columns, row)) for row in await cursor.fetchall()]

    def _row_to_msg(self, row: Any, session_key: str) -> StoredMessage:
        """数据库行 → StoredMessage.

        列顺序对应 get_messages 中的 cols:
            role, content, timestamp, sender_id, sender_name, message_id, metadata_json
        """
        role, content, ts, sender_id, sender_name, message_id, meta_json = row
        return StoredMessage(
            session_key=session_key,
            role=role,
            content=content,
            timestamp=ts,
            sender_id=sender_id,
            sender_name=sender_name,
            message_id=message_id,
            metadata=json.loads(meta_json) if meta_json else {},
        )
