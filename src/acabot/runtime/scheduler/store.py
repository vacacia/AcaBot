"""scheduler.store 提供定时任务的 SQLite 持久化存储.

使用与 runtime.storage.sqlite_stores 相同的 _SQLiteStoreBase 基类,
同步 sqlite3 + asyncio.Lock 模式.
"""

from __future__ import annotations

import time
from pathlib import Path

from acabot.runtime.storage.sqlite_stores import _SQLiteStoreBase

from .contracts import ScheduledTaskRow


class SQLiteScheduledTaskStore(_SQLiteStoreBase):
    """SQLite 持久化的定时任务存储."""

    def __init__(self, db_path: str | Path) -> None:
        """初始化 SQLiteScheduledTaskStore.

        Args:
            db_path: SQLite 数据库文件路径.
        """

        super().__init__(db_path)
        self._ensure_schema()

    # region public methods

    async def upsert(self, row: ScheduledTaskRow) -> None:
        """插入或替换一条定时任务记录.

        Args:
            row: 待写入的 ScheduledTaskRow.
        """

        async with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO scheduled_tasks (
                    task_id,
                    owner,
                    schedule_type,
                    schedule_spec,
                    misfire_policy,
                    next_fire_at,
                    enabled,
                    created_at,
                    updated_at,
                    last_fired_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.task_id,
                    row.owner,
                    row.schedule_type,
                    self._encode_json(row.schedule_spec),
                    row.misfire_policy,
                    row.next_fire_at,
                    1 if row.enabled else 0,
                    row.created_at,
                    row.updated_at,
                    row.last_fired_at,
                    self._encode_json(row.metadata),
                ),
            )
            self._conn.commit()

    async def delete(self, task_id: str) -> bool:
        """删除一条定时任务记录."""

        async with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM scheduled_tasks WHERE task_id = ?",
                (task_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    async def delete_by_owner(self, owner: str) -> list[str]:
        """按 owner 批量删除定时任务."""

        async with self._lock:
            rows = self._conn.execute(
                "SELECT task_id FROM scheduled_tasks WHERE owner = ?",
                (owner,),
            ).fetchall()
            task_ids = [str(row["task_id"]) for row in rows]
            if task_ids:
                self._conn.execute(
                    "DELETE FROM scheduled_tasks WHERE owner = ?",
                    (owner,),
                )
                self._conn.commit()
            return task_ids

    async def update_schedule_state(
        self,
        task_id: str,
        *,
        next_fire_at: float | None,
        enabled: bool,
        last_fired_at: float | None = None,
    ) -> None:
        """更新任务的调度状态."""

        async with self._lock:
            self._conn.execute(
                """
                UPDATE scheduled_tasks
                SET next_fire_at = ?, enabled = ?, updated_at = ?, last_fired_at = COALESCE(?, last_fired_at)
                WHERE task_id = ?
                """,
                (next_fire_at, 1 if enabled else 0, time.time(), last_fired_at, task_id),
            )
            self._conn.commit()

    async def update_next_fire_at(self, task_id: str, next_fire_at: float | None) -> None:
        """更新任务的 next_fire_at 与 updated_at."""

        async with self._lock:
            self._conn.execute(
                "UPDATE scheduled_tasks SET next_fire_at = ?, updated_at = ? WHERE task_id = ?",
                (next_fire_at, time.time(), task_id),
            )
            self._conn.commit()

    async def enable(self, task_id: str, *, next_fire_at: float) -> bool:
        """启用一个定时任务并写入新的 next_fire_at."""

        async with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE scheduled_tasks
                SET enabled = 1, next_fire_at = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (next_fire_at, time.time(), task_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    async def disable(self, task_id: str, *, next_fire_at: float | None = None) -> bool:
        """禁用一个定时任务."""

        async with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE scheduled_tasks
                SET enabled = 0, next_fire_at = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (next_fire_at, time.time(), task_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    async def list_enabled(self) -> list[ScheduledTaskRow]:
        """列出所有启用的定时任务, 按 next_fire_at 升序排列."""

        async with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    task_id,
                    owner,
                    schedule_type,
                    schedule_spec,
                    misfire_policy,
                    next_fire_at,
                    enabled,
                    created_at,
                    updated_at,
                    last_fired_at,
                    metadata_json
                FROM scheduled_tasks
                WHERE enabled = 1
                ORDER BY next_fire_at
                """,
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    async def list_all(self) -> list[ScheduledTaskRow]:
        """列出所有定时任务, 包括 disabled tombstone."""

        async with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    task_id,
                    owner,
                    schedule_type,
                    schedule_spec,
                    misfire_policy,
                    next_fire_at,
                    enabled,
                    created_at,
                    updated_at,
                    last_fired_at,
                    metadata_json
                FROM scheduled_tasks
                ORDER BY created_at DESC, task_id DESC
                """,
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    # endregion

    # region private methods

    def _ensure_schema(self) -> None:
        """初始化 scheduled_tasks 表结构."""

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                task_id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                schedule_type TEXT NOT NULL,
                schedule_spec TEXT NOT NULL,
                misfire_policy TEXT NOT NULL DEFAULT 'skip',
                next_fire_at REAL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_fired_at REAL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_fire
                ON scheduled_tasks(enabled, next_fire_at)
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_owner
                ON scheduled_tasks(owner)
            """
        )
        self._ensure_column("next_fire_at", "REAL")
        self._ensure_column("last_fired_at", "REAL")
        self._conn.commit()

    def _ensure_column(self, name: str, definition: str) -> None:
        columns = {
            str(row["name"]): str(row["type"])
            for row in self._conn.execute("PRAGMA table_info(scheduled_tasks)").fetchall()
        }
        if name in columns:
            return
        self._conn.execute(f"ALTER TABLE scheduled_tasks ADD COLUMN {name} {definition}")

    def _row_to_record(self, row) -> ScheduledTaskRow:
        return ScheduledTaskRow(
            task_id=str(row["task_id"]),
            owner=str(row["owner"]),
            schedule_type=str(row["schedule_type"]),
            schedule_spec=dict(self._decode_json(row["schedule_spec"])),
            misfire_policy=str(row["misfire_policy"]),  # type: ignore[arg-type]
            next_fire_at=None if row["next_fire_at"] is None else float(row["next_fire_at"]),
            enabled=bool(row["enabled"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            last_fired_at=None if row["last_fired_at"] is None else float(row["last_fired_at"]),
            metadata=dict(self._decode_json(row["metadata_json"])),
        )

    # endregion
