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
    """heapq 排序条目. lazy deletion 模式.

    Attributes:
        fire_at: 触发时间 (排序键).
        task_id: 任务 ID (不参与排序).
        cancelled: 是否已被标记取消 (不参与排序).
    """

    fire_at: float
    task_id: str = field(compare=False)
    cancelled: bool = field(default=False, compare=False)


@dataclass(slots=True)
class _TaskRecord:
    """运行时的完整任务记录.

    Attributes:
        task_id: 任务 ID.
        owner: 注册来源.
        schedule: 调度配置.
        callback: 异步回调.
        persist: 是否持久化.
        misfire_policy: misfire 策略.
        next_fire_at: 下次触发时间.
        enabled: 是否启用.
        metadata: 扩展元数据.
        heap_entry: 当前堆中的条目引用 (用于 lazy cancel).
    """

    task_id: str
    owner: str
    schedule: ScheduleType
    callback: Callable[[], Awaitable[None]] | None
    persist: bool
    misfire_policy: MisfirePolicy
    next_fire_at: float
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    heap_entry: _HeapEntry | None = None


# endregion


class RuntimeScheduler:
    """轻量级 asyncio 定时任务调度器.

    支持 cron / interval / one-shot 三种调度类型.
    使用 heapq + asyncio.Event 实现精确唤醒.
    """

    def __init__(self, *, store: SQLiteScheduledTaskStore | None = None) -> None:
        """初始化调度器.

        Args:
            store: 可选的持久化 store. 为 None 时不支持 persist.
        """

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
        """启动调度器主循环.

        恢复持久化任务并创建 worker 协程.
        """

        if self._started:
            logger.warning("Scheduler already started, ignoring duplicate start()")
            return

        await self._recover_persisted_tasks()
        await self._rebind_persisted_callbacks()
        self._worker_task = asyncio.create_task(self._worker_loop())
        self._started = True
        logger.info("Scheduler started")

    async def stop(self) -> None:
        """优雅关闭调度器.

        等待 worker 退出并等所有正在执行的回调完成.
        """

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
        """注册一个定时任务.

        如果 task_id 已存在则更新 (取消旧 heap entry, 重新入堆).
        支持持久化任务恢复时重新绑定 callback.

        Args:
            task_id: 任务唯一标识.
            owner: 注册来源标识.
            schedule: 调度配置.
            callback: 异步回调函数.
            persist: 是否持久化到 store.
            misfire_policy: 过期未触发时的处理策略.
            metadata: 扩展元数据.
        """

        # 验证 schedule 合法性
        self._validate_schedule(schedule)

        existing = self._tasks.get(task_id)

        # 计算 next_fire_at
        if existing is not None:
            # 任务已存在 (持久化恢复或重复注册): 保留旧的 next_fire_at, 重新入堆
            next_fire_at = existing.next_fire_at
            if existing.heap_entry is not None:
                existing.heap_entry.cancelled = True
        else:
            next_fire_at = self._compute_initial_fire(schedule)

        record = _TaskRecord(
            task_id=task_id,
            owner=owner,
            schedule=schedule,
            callback=callback,
            persist=persist,
            misfire_policy=misfire_policy,
            next_fire_at=next_fire_at,
            metadata=metadata or {},
        )
        self._tasks[task_id] = record

        # 持久化
        if persist and self._store is not None:
            stype, sspec = schedule_to_type_and_spec(schedule)
            now = time.time()
            await self._store.upsert(ScheduledTaskRow(
                task_id=task_id,
                owner=owner,
                schedule_type=stype,
                schedule_spec=sspec,
                misfire_policy=misfire_policy,
                next_fire_at=next_fire_at,
                enabled=True,
                created_at=now,
                updated_at=now,
                metadata=metadata or {},
            ))

        # 入堆
        entry = self._enqueue(task_id, next_fire_at)
        record.heap_entry = entry

        self._wake_event.set()
        logger.debug("Registered task: task_id=%s, owner=%s, next_fire_at=%.3f", task_id, owner, next_fire_at)

    async def cancel(self, task_id: str) -> bool:
        """取消一个定时任务.

        Args:
            task_id: 待取消的任务 ID.

        Returns:
            是否成功取消 (task_id 不存在时返回 False).
        """

        record = self._tasks.pop(task_id, None)
        if record is None:
            return False

        # lazy deletion: 标记 heap entry 为已取消
        if record.heap_entry is not None:
            record.heap_entry.cancelled = True

        if record.persist and self._store is not None:
            await self._store.delete(task_id)

        self._wake_event.set()
        logger.debug("Cancelled task: task_id=%s", task_id)
        return True

    async def unregister_by_owner(self, owner: str) -> list[str]:
        """按 owner 批量取消定时任务.

        Args:
            owner: 注册来源标识.

        Returns:
            被取消的 task_id 列表.
        """

        task_ids = [
            tid for tid, rec in self._tasks.items()
            if rec.owner == owner
        ]
        for tid in task_ids:
            await self.cancel(tid)

        # 兜底: 批量清理 store 中可能遗留的记录
        if self._store is not None:
            await self._store.delete_by_owner(owner)

        return task_ids

    def list_tasks(self) -> list[ScheduledTaskInfo]:
        """列出所有已注册的任务快照.

        Returns:
            ScheduledTaskInfo 列表.
        """

        return [
            ScheduledTaskInfo(
                task_id=rec.task_id,
                owner=rec.owner,
                schedule=rec.schedule,
                persist=rec.persist,
                misfire_policy=rec.misfire_policy,
                next_fire_at=rec.next_fire_at,
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
        """调度主循环.

        不断从 heap 中取出最近需要触发的任务, 等待到触发时间后执行.
        使用 asyncio.Event + wait_for 实现精确唤醒.
        """

        while not self._stopping:
            if not self._heap:
                self._wake_event.clear()
                await self._wake_event.wait()
                continue

            entry = self._heap[0]

            # lazy deletion: 跳过已取消的条目
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

            # 触发时间到达, pop 并执行
            heapq.heappop(self._heap)

            record = self._tasks.get(entry.task_id)
            if record is None:
                # 已被 cancel, 跳过
                continue

            self._fire_task(record)

            # 计算下次触发时间
            next_fire = self._compute_next_fire(record, time.time())
            if next_fire is not None:
                record.next_fire_at = next_fire
                new_entry = self._enqueue(record.task_id, next_fire)
                record.heap_entry = new_entry

                # 持久化更新 next_fire_at
                if record.persist and self._store is not None:
                    await self._store.update_next_fire_at(record.task_id, next_fire)
            else:
                # one-shot 任务, 执行后移除
                self._tasks.pop(record.task_id, None)
                if record.persist and self._store is not None:
                    await self._store.disable(record.task_id)

    # endregion

    # region callback execution

    def _fire_task(self, record: _TaskRecord) -> None:
        """触发一个任务的回调.

        Args:
            record: 待触发的任务记录.
        """

        if record.callback is None:
            logger.warning(
                "Skipping task with no callback: task_id=%s", record.task_id
            )
            return

        task = asyncio.create_task(self._execute_callback(record))
        self._running_callbacks.add(task)
        task.add_done_callback(self._running_callbacks.discard)

    async def _execute_callback(self, record: _TaskRecord) -> None:
        """安全执行回调, 捕获异常并记录日志.

        Args:
            record: 任务记录.
        """

        try:
            if record.callback is not None:
                await record.callback()
        except Exception:
            logger.exception(
                "Callback error: task_id=%s", record.task_id
            )

    # endregion

    # region scheduling helpers

    @staticmethod
    def _validate_schedule(schedule: ScheduleType) -> None:
        """验证调度配置的合法性.

        Args:
            schedule: 待验证的调度配置.

        Raises:
            ValueError: 配置不合法时抛出.
        """

        if isinstance(schedule, CronSchedule):
            if not croniter.is_valid(schedule.cron_expr):
                raise ValueError(f"Invalid cron expression: {schedule.cron_expr!r}")
        elif isinstance(schedule, IntervalSchedule):
            if schedule.seconds <= 0:
                raise ValueError(
                    f"Interval seconds must be positive, got {schedule.seconds}"
                )
        elif isinstance(schedule, OneShotSchedule):
            if schedule.fire_at <= 0:
                raise ValueError(
                    f"OneShotSchedule fire_at must be positive, got {schedule.fire_at}"
                )

    @staticmethod
    def _compute_initial_fire(schedule: ScheduleType) -> float:
        """计算首次触发时间.

        Args:
            schedule: 调度配置.

        Returns:
            首次触发的 Unix timestamp.
        """

        if isinstance(schedule, CronSchedule):
            return float(croniter(schedule.cron_expr, start_time=time.time()).get_next(float))
        if isinstance(schedule, IntervalSchedule):
            return time.time() + schedule.seconds
        if isinstance(schedule, OneShotSchedule):
            return schedule.fire_at
        raise TypeError(f"Unknown schedule type: {type(schedule)}")

    @staticmethod
    def _compute_next_fire(record: _TaskRecord, after: float) -> float | None:
        """计算下次触发时间.

        Args:
            record: 任务记录.
            after: 基准时间 (通常是当前时间).

        Returns:
            下次触发的 Unix timestamp, one-shot 返回 None.
        """

        schedule = record.schedule
        if isinstance(schedule, CronSchedule):
            return float(croniter(schedule.cron_expr, start_time=after).get_next(float))
        if isinstance(schedule, IntervalSchedule):
            return after + schedule.seconds
        if isinstance(schedule, OneShotSchedule):
            return None
        raise TypeError(f"Unknown schedule type: {type(schedule)}")

    def _enqueue(self, task_id: str, fire_at: float) -> _HeapEntry:
        """创建 heap entry 并入堆.

        Args:
            task_id: 任务 ID.
            fire_at: 触发时间.

        Returns:
            新创建的 _HeapEntry.
        """

        entry = _HeapEntry(fire_at=fire_at, task_id=task_id)
        heapq.heappush(self._heap, entry)
        return entry

    # endregion

    # region persistence recovery

    async def _recover_persisted_tasks(self) -> None:
        """从 store 恢复持久化的定时任务.

        处理 misfire 策略: skip 时推进到下一个触发时间, fire_once 时立即触发.
        恢复后 callback 为 None, 需要通过 register() 重新绑定.
        """

        if self._store is None:
            return

        rows = await self._store.list_enabled()
        if not rows:
            return

        now = time.time()
        recovered = 0

        for row in rows:
            schedule = spec_to_schedule(row.schedule_type, row.schedule_spec)
            next_fire_at = row.next_fire_at

            if next_fire_at < now:
                # misfire 处理
                if isinstance(schedule, OneShotSchedule):
                    if row.misfire_policy == "skip":
                        await self._store.disable(row.task_id)
                        continue
                    else:
                        # fire_once: 立即触发
                        next_fire_at = now
                else:
                    # cron / interval
                    if row.misfire_policy == "skip":
                        # 推进到下一个 >= now 的触发时间
                        next_fire_at = self._advance_to_future(schedule, now)
                        await self._store.update_next_fire_at(row.task_id, next_fire_at)
                    else:
                        # fire_once: 立即补触发一次
                        next_fire_at = now

            record = _TaskRecord(
                task_id=row.task_id,
                owner=row.owner,
                schedule=schedule,
                callback=None,
                persist=True,
                misfire_policy=row.misfire_policy,
                next_fire_at=next_fire_at,
                enabled=row.enabled,
                metadata=row.metadata,
            )
            self._tasks[row.task_id] = record

            entry = self._enqueue(row.task_id, next_fire_at)
            record.heap_entry = entry
            recovered += 1

        if recovered > 0:
            logger.info("Recovered %d persisted tasks from store", recovered)

    @staticmethod
    def _advance_to_future(schedule: ScheduleType, now: float) -> float:
        """推进调度到未来的下一个触发时间.

        Args:
            schedule: 调度配置.
            now: 当前时间.

        Returns:
            下一个 >= now 的触发 timestamp.
        """

        if isinstance(schedule, CronSchedule):
            return float(croniter(schedule.cron_expr, start_time=now).get_next(float))
        if isinstance(schedule, IntervalSchedule):
            return now + schedule.seconds
        raise TypeError(f"Cannot advance schedule type: {type(schedule)}")

    # endregion
