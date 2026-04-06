"""scheduler.scheduler 提供 RuntimeScheduler 核心调度引擎.

使用 heapq + asyncio.Event 实现精确唤醒的轻量级异步定时任务调度器,
支持 cron / interval / one-shot 三种调度类型, 持久化恢复, 优雅关闭.
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any

from croniter import croniter

from .contracts import (
    CronSchedule,
    IntervalSchedule,
    MisfirePolicy,
    OneShotSchedule,
    ScheduleType,
    ScheduledTaskInfo,
    ScheduledTaskRow,
    schedule_to_type_and_spec,
    spec_to_schedule,
)
from .store import SQLiteScheduledTaskStore

logger = logging.getLogger("acabot.runtime.scheduler")


# region internal data structures


@dataclass(order=True)
class _HeapEntry:
    """heapq 排序条目. lazy deletion 模式."""

    fire_at: float
    task_id: str = field(compare=False)
    cancelled: bool = field(default=False, compare=False)


@dataclass(slots=True)
class _TaskRecord:
    """运行时的完整任务记录."""

    task_id: str
    owner: str
    schedule: ScheduleType
    callback: Callable[[], Awaitable[None]] | None
    persist: bool
    misfire_policy: MisfirePolicy
    next_fire_at: float | None
    created_at: float
    updated_at: float
    last_fired_at: float | None = None
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    heap_entry: _HeapEntry | None = None


# endregion


class RuntimeScheduler:
    """轻量级 asyncio 定时任务调度器."""

    def __init__(self, *, store: SQLiteScheduledTaskStore | None = None) -> None:
        self._store = store
        self._tasks: dict[str, _TaskRecord] = {}
        self._heap: list[_HeapEntry] = []
        self._wake_event = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._running_callbacks: set[asyncio.Task[None]] = set()
        self._callback_resolver: Callable[[ScheduledTaskInfo], Awaitable[Callable[[], Awaitable[None]] | None] | Callable[[], Awaitable[None]] | None] | None = None
        self._started = False
        self._stopping = False

    # region public lifecycle

    async def start(self) -> None:
        """启动调度器主循环."""

        if self._started:
            logger.warning("Scheduler already started, ignoring duplicate start()")
            return

        await self._recover_persisted_tasks()
        await self._rebind_persisted_callbacks()
        self._worker_task = asyncio.create_task(self._worker_loop())
        self._started = True
        logger.info("Scheduler started")

    async def stop(self) -> None:
        """优雅关闭调度器."""

        if not self._started:
            return

        self._stopping = True
        self._wake_event.set()

        if self._worker_task is not None:
            await self._worker_task
            self._worker_task = None

        if self._running_callbacks:
            await asyncio.gather(*self._running_callbacks, return_exceptions=True)
            self._running_callbacks.clear()

        self._started = False
        self._stopping = False
        logger.info("Scheduler stopped")

    def set_callback_resolver(
        self,
        resolver: Callable[[ScheduledTaskInfo], Awaitable[Callable[[], Awaitable[None]] | None] | Callable[[], Awaitable[None]] | None],
    ) -> None:
        """设置持久化任务恢复后的 callback 重建器."""

        self._callback_resolver = resolver

    # endregion

    # region public task management

    async def register(
        self,
        *,
        task_id: str,
        owner: str,
        schedule: ScheduleType,
        callback: Callable[[], Awaitable[None]],
        persist: bool = False,
        misfire_policy: MisfirePolicy = "skip",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册一个定时任务."""

        self._validate_schedule(schedule)
        existing = self._tasks.get(task_id)

        if existing is not None and existing.heap_entry is not None:
            existing.heap_entry.cancelled = True

        next_fire_at = (
            existing.next_fire_at
            if existing is not None and existing.next_fire_at is not None
            else self._compute_initial_fire(schedule)
        )
        now = time.time()
        record = _TaskRecord(
            task_id=task_id,
            owner=owner,
            schedule=schedule,
            callback=callback,
            persist=persist,
            misfire_policy=misfire_policy,
            next_fire_at=next_fire_at,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            last_fired_at=existing.last_fired_at if existing is not None else None,
            enabled=True,
            metadata=metadata or {},
        )
        self._tasks[task_id] = record

        if persist and self._store is not None:
            stype, sspec = schedule_to_type_and_spec(schedule)
            await self._store.upsert(
                ScheduledTaskRow(
                    task_id=task_id,
                    owner=owner,
                    schedule_type=stype,
                    schedule_spec=sspec,
                    misfire_policy=misfire_policy,
                    next_fire_at=next_fire_at,
                    enabled=True,
                    created_at=record.created_at,
                    updated_at=now,
                    last_fired_at=record.last_fired_at,
                    metadata=metadata or {},
                )
            )

        entry = self._enqueue(task_id, next_fire_at)
        record.heap_entry = entry
        self._wake_event.set()
        logger.debug("Registered task: task_id=%s, owner=%s, next_fire_at=%.3f", task_id, owner, next_fire_at)

    async def cancel(self, task_id: str) -> bool:
        """取消一个定时任务."""

        record = self._tasks.pop(task_id, None)
        if record is None:
            return False

        if record.heap_entry is not None:
            record.heap_entry.cancelled = True

        if record.persist and self._store is not None:
            await self._store.delete(task_id)

        self._wake_event.set()
        logger.debug("Cancelled task: task_id=%s", task_id)
        return True

    async def disable(self, task_id: str) -> bool:
        """暂停一个任务, 保留记录但不再触发."""

        record = self._tasks.get(task_id)
        if record is None:
            return False
        if not record.enabled:
            return True

        if record.heap_entry is not None:
            record.heap_entry.cancelled = True
            record.heap_entry = None
        record.enabled = False
        record.next_fire_at = None
        record.updated_at = time.time()

        if record.persist and self._store is not None:
            await self._store.disable(task_id, next_fire_at=None)

        self._wake_event.set()
        logger.debug("Disabled task: task_id=%s", task_id)
        return True

    async def enable(self, task_id: str) -> bool:
        """恢复一个已暂停任务."""

        record = self._tasks.get(task_id)
        if record is None:
            return False
        if record.enabled:
            return True

        next_fire_at = self._compute_resumed_fire(record, time.time())
        record.enabled = True
        record.next_fire_at = next_fire_at
        record.updated_at = time.time()
        entry = self._enqueue(task_id, next_fire_at)
        record.heap_entry = entry

        if record.persist and self._store is not None:
            await self._store.enable(task_id, next_fire_at=next_fire_at)

        self._wake_event.set()
        logger.debug("Enabled task: task_id=%s next_fire_at=%.3f", task_id, next_fire_at)
        return True

    async def unregister_by_owner(self, owner: str) -> list[str]:
        """按 owner 批量取消定时任务."""

        task_ids = [tid for tid, rec in self._tasks.items() if rec.owner == owner]
        for tid in task_ids:
            await self.cancel(tid)

        if self._store is not None:
            await self._store.delete_by_owner(owner)

        return task_ids

    def list_tasks(self) -> list[ScheduledTaskInfo]:
        """列出所有已注册的任务快照."""

        return [
            ScheduledTaskInfo(
                task_id=rec.task_id,
                owner=rec.owner,
                schedule=rec.schedule,
                persist=rec.persist,
                misfire_policy=rec.misfire_policy,
                next_fire_at=rec.next_fire_at,
                created_at=rec.created_at,
                updated_at=rec.updated_at,
                last_fired_at=rec.last_fired_at,
                enabled=rec.enabled,
                metadata=rec.metadata,
            )
            for rec in self._tasks.values()
        ]

    # endregion

    async def _rebind_persisted_callbacks(self) -> None:
        """为恢复出的持久化任务重建 callback."""

        resolver = self._callback_resolver
        if resolver is None:
            return

        for task in self.list_tasks():
            record = self._tasks.get(task.task_id)
            if record is None or record.callback is not None:
                continue
            callback = resolver(task)
            if isawaitable(callback):
                callback = await callback
            record.callback = callback

    # region worker loop

    async def _worker_loop(self) -> None:
        """调度主循环."""

        while not self._stopping:
            if not self._heap:
                self._wake_event.clear()
                await self._wake_event.wait()
                continue

            entry = self._heap[0]
            if entry.cancelled:
                heapq.heappop(self._heap)
                continue

            delay = entry.fire_at - time.time()
            if delay > 0:
                self._wake_event.clear()
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                continue

            heapq.heappop(self._heap)
            record = self._tasks.get(entry.task_id)
            if record is None or not record.enabled:
                continue

            fired_at = time.time()
            record.last_fired_at = fired_at
            record.updated_at = fired_at
            self._fire_task(record)

            next_fire = self._compute_next_fire(record, fired_at)
            if next_fire is not None:
                record.next_fire_at = next_fire
                record.updated_at = fired_at
                new_entry = self._enqueue(record.task_id, next_fire)
                record.heap_entry = new_entry
                if record.persist and self._store is not None:
                    await self._store.update_schedule_state(
                        record.task_id,
                        next_fire_at=next_fire,
                        enabled=True,
                        last_fired_at=fired_at,
                    )
            else:
                record.enabled = False
                record.next_fire_at = None
                record.heap_entry = None
                if record.persist and self._store is not None:
                    await self._store.update_schedule_state(
                        record.task_id,
                        next_fire_at=None,
                        enabled=False,
                        last_fired_at=fired_at,
                    )

    # endregion

    # region callback execution

    def _fire_task(self, record: _TaskRecord) -> None:
        """触发一个任务的回调."""

        if record.callback is None:
            logger.warning("Skipping task with no callback: task_id=%s", record.task_id)
            return

        task = asyncio.create_task(self._execute_callback(record))
        self._running_callbacks.add(task)
        task.add_done_callback(self._running_callbacks.discard)

    async def _execute_callback(self, record: _TaskRecord) -> None:
        """安全执行回调, 捕获异常并记录日志."""

        try:
            if record.callback is not None:
                await record.callback()
        except Exception:
            logger.exception("Callback error: task_id=%s", record.task_id)

    # endregion

    # region scheduling helpers

    @staticmethod
    def _validate_schedule(schedule: ScheduleType) -> None:
        if isinstance(schedule, CronSchedule):
            if not croniter.is_valid(schedule.cron_expr):
                raise ValueError(f"Invalid cron expression: {schedule.cron_expr!r}")
        elif isinstance(schedule, IntervalSchedule):
            if schedule.seconds <= 0:
                raise ValueError(f"Interval seconds must be positive, got {schedule.seconds}")
        elif isinstance(schedule, OneShotSchedule):
            if schedule.fire_at <= 0:
                raise ValueError(f"OneShotSchedule fire_at must be positive, got {schedule.fire_at}")

    @staticmethod
    def _compute_initial_fire(schedule: ScheduleType) -> float:
        if isinstance(schedule, CronSchedule):
            return float(croniter(schedule.cron_expr, start_time=time.time()).get_next(float))
        if isinstance(schedule, IntervalSchedule):
            return time.time() + schedule.seconds
        if isinstance(schedule, OneShotSchedule):
            return schedule.fire_at
        raise TypeError(f"Unknown schedule type: {type(schedule)}")

    @staticmethod
    def _compute_next_fire(record: _TaskRecord, after: float) -> float | None:
        schedule = record.schedule
        if isinstance(schedule, CronSchedule):
            return float(croniter(schedule.cron_expr, start_time=after).get_next(float))
        if isinstance(schedule, IntervalSchedule):
            return after + schedule.seconds
        if isinstance(schedule, OneShotSchedule):
            return None
        raise TypeError(f"Unknown schedule type: {type(schedule)}")

    @staticmethod
    def _compute_resumed_fire(record: _TaskRecord, now: float) -> float:
        schedule = record.schedule
        if isinstance(schedule, CronSchedule):
            return float(croniter(schedule.cron_expr, start_time=now).get_next(float))
        if isinstance(schedule, IntervalSchedule):
            return now + schedule.seconds
        if isinstance(schedule, OneShotSchedule):
            if schedule.fire_at <= now:
                raise ValueError("expired one_shot task cannot be resumed")
            return schedule.fire_at
        raise TypeError(f"Unknown schedule type: {type(schedule)}")

    def _enqueue(self, task_id: str, fire_at: float) -> _HeapEntry:
        entry = _HeapEntry(fire_at=fire_at, task_id=task_id)
        heapq.heappush(self._heap, entry)
        return entry

    # endregion

    # region persistence recovery

    async def _recover_persisted_tasks(self) -> None:
        """从 store 恢复持久化的定时任务."""

        if self._store is None:
            return

        rows = await self._store.list_all()
        if not rows:
            return

        now = time.time()
        recovered = 0

        for row in rows:
            if row.task_id in self._tasks:
                continue

            schedule = spec_to_schedule(row.schedule_type, row.schedule_spec)
            next_fire_at = row.next_fire_at
            enabled = row.enabled

            if enabled and next_fire_at is not None and next_fire_at < now:
                if isinstance(schedule, OneShotSchedule):
                    if row.misfire_policy == "skip":
                        enabled = False
                        next_fire_at = None
                        await self._store.disable(row.task_id, next_fire_at=None)
                    else:
                        next_fire_at = now
                else:
                    if row.misfire_policy == "skip":
                        next_fire_at = self._advance_to_future(schedule, now)
                        await self._store.enable(row.task_id, next_fire_at=next_fire_at)
                    else:
                        next_fire_at = now
            elif enabled and next_fire_at is None:
                next_fire_at = self._compute_resumed_fire(
                    _TaskRecord(
                        task_id=row.task_id,
                        owner=row.owner,
                        schedule=schedule,
                        callback=None,
                        persist=True,
                        misfire_policy=row.misfire_policy,
                        next_fire_at=None,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        last_fired_at=row.last_fired_at,
                        enabled=True,
                        metadata=row.metadata,
                    ),
                    now,
                )
                await self._store.enable(row.task_id, next_fire_at=next_fire_at)

            record = _TaskRecord(
                task_id=row.task_id,
                owner=row.owner,
                schedule=schedule,
                callback=None,
                persist=True,
                misfire_policy=row.misfire_policy,
                next_fire_at=next_fire_at if enabled else None,
                created_at=row.created_at,
                updated_at=row.updated_at,
                last_fired_at=row.last_fired_at,
                enabled=enabled,
                metadata=row.metadata,
            )
            self._tasks[row.task_id] = record

            if enabled and next_fire_at is not None:
                entry = self._enqueue(row.task_id, next_fire_at)
                record.heap_entry = entry
            recovered += 1

        if recovered > 0:
            logger.info("Recovered %d persisted tasks from store", recovered)

    @staticmethod
    def _advance_to_future(schedule: ScheduleType, now: float) -> float:
        if isinstance(schedule, CronSchedule):
            return float(croniter(schedule.cron_expr, start_time=now).get_next(float))
        if isinstance(schedule, IntervalSchedule):
            return now + schedule.seconds
        raise TypeError(f"Cannot advance schedule type: {type(schedule)}")

    # endregion
