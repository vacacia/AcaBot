"""runtime.sqlite_stores 提供 thread 和 run 的 SQLite 实现.

目前只有两类持久化:
- ThreadStore
- RunStore

MessageStore 仍独立实现.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import RunRecord, RunStep, ThreadRecord
from .stores import RunStore, ThreadStore


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
                    step_type,
                    status,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    step.step_id,
                    step.run_id,
                    step.step_type,
                    step.status,
                    self._encode_json(step.payload),
                    step.created_at,
                ),
            )
            self._conn.commit()

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
