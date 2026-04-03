"""test_scheduler 测试 RuntimeScheduler 核心调度功能.

覆盖: store CRUD, scheduler 注册/取消/触发, 持久化恢复, misfire 策略.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from acabot.runtime.scheduler import (
    CronSchedule,
    IntervalSchedule,
    MisfirePolicy,
    OneShotSchedule,
    RuntimeScheduler,
    ScheduledTaskInfo,
    SQLiteScheduledTaskStore,
)
from acabot.runtime.scheduler.contracts import ScheduledTaskRow


# region fixtures


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteScheduledTaskStore:
    """创建临时 store 实例."""
    s = SQLiteScheduledTaskStore(tmp_path / "sched.db")
    yield s  # type: ignore[misc]
    s.close()


@pytest.fixture()
def scheduler() -> RuntimeScheduler:
    """创建纯内存模式 (无 store) 的调度器."""
    return RuntimeScheduler()


def _make_row(
    task_id: str = "t1",
    owner: str = "test",
    schedule_type: str = "interval",
    schedule_spec: dict | None = None,
    misfire_policy: MisfirePolicy = "skip",
    next_fire_at: float | None = None,
    enabled: bool = True,
    metadata: dict | None = None,
) -> ScheduledTaskRow:
    """辅助构造 ScheduledTaskRow."""
    now = time.time()
    return ScheduledTaskRow(
        task_id=task_id,
        owner=owner,
        schedule_type=schedule_type,
        schedule_spec=schedule_spec or {"interval_seconds": 60},
        misfire_policy=misfire_policy,
        next_fire_at=next_fire_at or (now + 3600),
        enabled=enabled,
        created_at=now,
        updated_at=now,
        metadata=metadata or {},
    )


# endregion


# region store tests


async def test_store_upsert_and_list(store: SQLiteScheduledTaskStore) -> None:
    """upsert 一个 ScheduledTaskRow, list_enabled 返回它."""
    row = _make_row()
    await store.upsert(row)
    rows = await store.list_enabled()
    assert len(rows) == 1
    assert rows[0].task_id == "t1"


async def test_store_delete(store: SQLiteScheduledTaskStore) -> None:
    """upsert 后 delete, list_enabled 返回空."""
    await store.upsert(_make_row())
    deleted = await store.delete("t1")
    assert deleted is True
    assert await store.list_enabled() == []


async def test_store_delete_by_owner(store: SQLiteScheduledTaskStore) -> None:
    """upsert 两个不同 owner 的任务, delete_by_owner 只删对应 owner 的."""
    await store.upsert(_make_row(task_id="a1", owner="alice"))
    await store.upsert(_make_row(task_id="b1", owner="bob"))
    deleted_ids = await store.delete_by_owner("alice")
    assert deleted_ids == ["a1"]
    remaining = await store.list_enabled()
    assert len(remaining) == 1
    assert remaining[0].owner == "bob"


async def test_store_update_next_fire_at(store: SQLiteScheduledTaskStore) -> None:
    """upsert 后 update, list_enabled 中 next_fire_at 已更新."""
    await store.upsert(_make_row(next_fire_at=100.0))
    await store.update_next_fire_at("t1", 200.0)
    rows = await store.list_enabled()
    assert rows[0].next_fire_at == 200.0


async def test_store_disable(store: SQLiteScheduledTaskStore) -> None:
    """upsert 后 disable, list_enabled 不再返回该任务."""
    await store.upsert(_make_row())
    await store.disable("t1")
    assert await store.list_enabled() == []


async def test_store_upsert_replaces_existing(store: SQLiteScheduledTaskStore) -> None:
    """对同一 task_id upsert 两次, list_enabled 只有一条最新的."""
    await store.upsert(_make_row(owner="old"))
    await store.upsert(_make_row(owner="new"))
    rows = await store.list_enabled()
    assert len(rows) == 1
    assert rows[0].owner == "new"


# endregion


# region scheduler core tests


async def test_register_and_list(scheduler: RuntimeScheduler) -> None:
    """register 一个 interval 任务, list_tasks 返回它."""
    called = False

    async def cb() -> None:
        nonlocal called
        called = True

    await scheduler.register(
        task_id="t1",
        owner="test",
        schedule=IntervalSchedule(seconds=60),
        callback=cb,
    )
    tasks = scheduler.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].task_id == "t1"


async def test_cancel_returns_true_for_existing(scheduler: RuntimeScheduler) -> None:
    """register 后 cancel 返回 True."""

    async def cb() -> None:
        pass

    await scheduler.register(
        task_id="t1", owner="test", schedule=IntervalSchedule(seconds=60), callback=cb
    )
    assert await scheduler.cancel("t1") is True
    assert scheduler.list_tasks() == []


async def test_cancel_returns_false_for_nonexistent(scheduler: RuntimeScheduler) -> None:
    """cancel 不存在的 task_id 返回 False."""
    assert await scheduler.cancel("nope") is False


async def test_unregister_by_owner(scheduler: RuntimeScheduler) -> None:
    """register 两个同 owner 的任务, unregister_by_owner 全部取消."""

    async def cb() -> None:
        pass

    await scheduler.register(
        task_id="a", owner="alice", schedule=IntervalSchedule(seconds=60), callback=cb
    )
    await scheduler.register(
        task_id="b", owner="alice", schedule=IntervalSchedule(seconds=60), callback=cb
    )
    removed = await scheduler.unregister_by_owner("alice")
    assert sorted(removed) == ["a", "b"]
    assert scheduler.list_tasks() == []


async def test_interval_fires_callback(scheduler: RuntimeScheduler) -> None:
    """register interval=0.05s 的任务, start, 等 0.15s, 验证 callback 至少被调用 2 次."""
    count = 0

    async def cb() -> None:
        nonlocal count
        count += 1

    await scheduler.register(
        task_id="t1",
        owner="test",
        schedule=IntervalSchedule(seconds=0.05),
        callback=cb,
    )
    await scheduler.start()
    await asyncio.sleep(0.2)
    await scheduler.stop()
    assert count >= 2


async def test_one_shot_fires_once(scheduler: RuntimeScheduler) -> None:
    """register one_shot, start, 等待, 验证 callback 只被调用 1 次."""
    count = 0

    async def cb() -> None:
        nonlocal count
        count += 1

    await scheduler.register(
        task_id="t1",
        owner="test",
        schedule=OneShotSchedule(fire_at=time.time() + 0.05),
        callback=cb,
    )
    await scheduler.start()
    await asyncio.sleep(0.2)
    await scheduler.stop()
    assert count == 1


async def test_cron_validates_expression(scheduler: RuntimeScheduler) -> None:
    """register 无效 cron 表达式, 期望 ValueError."""

    async def cb() -> None:
        pass

    with pytest.raises(ValueError, match="Invalid cron"):
        await scheduler.register(
            task_id="t1",
            owner="test",
            schedule=CronSchedule(cron_expr="invalid cron expr"),
            callback=cb,
        )


async def test_cron_fires_callback(scheduler: RuntimeScheduler) -> None:
    """测试 cron 任务经过 worker_loop 正确触发."""
    count = 0

    async def cb() -> None:
        nonlocal count
        count += 1

    # 注册 cron 任务 (每分钟触发), 然后手动调整 next_fire_at 使其很快触发
    await scheduler.register(
        task_id="t1",
        owner="test",
        schedule=CronSchedule(cron_expr="* * * * *"),
        callback=cb,
    )
    # 手动将 next_fire_at 设为 0.05s 后并重新入堆
    record = scheduler._tasks["t1"]
    if record.heap_entry is not None:
        record.heap_entry.cancelled = True
    record.next_fire_at = time.time() + 0.05
    entry = scheduler._enqueue("t1", record.next_fire_at)
    record.heap_entry = entry

    await scheduler.start()
    await asyncio.sleep(0.15)
    await scheduler.stop()
    assert count >= 1


async def test_interval_validates_positive(scheduler: RuntimeScheduler) -> None:
    """register seconds=0 或负数, 期望 ValueError."""

    async def cb() -> None:
        pass

    with pytest.raises(ValueError, match="positive"):
        await scheduler.register(
            task_id="t1",
            owner="test",
            schedule=IntervalSchedule(seconds=0),
            callback=cb,
        )

    with pytest.raises(ValueError, match="positive"):
        await scheduler.register(
            task_id="t2",
            owner="test",
            schedule=IntervalSchedule(seconds=-1),
            callback=cb,
        )


async def test_graceful_shutdown_waits_callbacks(scheduler: RuntimeScheduler) -> None:
    """register 一个 callback 内部 sleep 0.1s 的任务, start, stop 不 raise."""
    finished = False

    async def cb() -> None:
        nonlocal finished
        await asyncio.sleep(0.1)
        finished = True

    await scheduler.register(
        task_id="t1",
        owner="test",
        schedule=IntervalSchedule(seconds=0.01),
        callback=cb,
    )
    await scheduler.start()
    await asyncio.sleep(0.05)
    await scheduler.stop()
    # stop 应该等待正在执行的回调完成
    assert finished is True


async def test_callback_error_does_not_stop_scheduler(scheduler: RuntimeScheduler) -> None:
    """register 一个抛异常的 callback, 验证 scheduler 仍在运行."""
    good_count = 0

    async def bad_cb() -> None:
        raise RuntimeError("boom")

    async def good_cb() -> None:
        nonlocal good_count
        good_count += 1

    await scheduler.register(
        task_id="bad",
        owner="test",
        schedule=IntervalSchedule(seconds=0.05),
        callback=bad_cb,
    )
    await scheduler.register(
        task_id="good",
        owner="test",
        schedule=IntervalSchedule(seconds=0.05),
        callback=good_cb,
    )
    await scheduler.start()
    await asyncio.sleep(0.2)
    assert scheduler._started is True
    await scheduler.stop()
    assert good_count >= 2


# endregion


# region persistence tests


async def test_persist_task_survives_restart(tmp_path: Path) -> None:
    """persist=True 的任务在 scheduler 重启后仍存在."""
    db_path = tmp_path / "sched.db"
    store = SQLiteScheduledTaskStore(db_path)

    async def cb() -> None:
        pass

    sched1 = RuntimeScheduler(store=store)
    await sched1.start()
    await sched1.register(
        task_id="t1",
        owner="test",
        schedule=IntervalSchedule(seconds=60),
        callback=cb,
        persist=True,
    )
    await sched1.stop()
    store.close()

    # 重新打开 store 和 scheduler
    store2 = SQLiteScheduledTaskStore(db_path)
    sched2 = RuntimeScheduler(store=store2)
    await sched2.start()
    tasks = sched2.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].task_id == "t1"
    await sched2.stop()
    store2.close()


async def test_non_persist_task_lost_on_restart(tmp_path: Path) -> None:
    """persist=False 的任务在重启后丢失."""
    db_path = tmp_path / "sched.db"
    store = SQLiteScheduledTaskStore(db_path)

    async def cb() -> None:
        pass

    sched1 = RuntimeScheduler(store=store)
    await sched1.start()
    await sched1.register(
        task_id="t1",
        owner="test",
        schedule=IntervalSchedule(seconds=60),
        callback=cb,
        persist=False,
    )
    await sched1.stop()
    store.close()

    store2 = SQLiteScheduledTaskStore(db_path)
    sched2 = RuntimeScheduler(store=store2)
    await sched2.start()
    assert sched2.list_tasks() == []
    await sched2.stop()
    store2.close()


async def test_misfire_skip_advances_next_fire(tmp_path: Path) -> None:
    """next_fire_at 为过去时间的 cron 任务 (misfire=skip), 恢复后 next_fire_at > now."""
    db_path = tmp_path / "sched.db"
    store = SQLiteScheduledTaskStore(db_path)

    past = time.time() - 3600
    row = ScheduledTaskRow(
        task_id="t1",
        owner="test",
        schedule_type="cron",
        schedule_spec={"cron_expr": "* * * * *"},
        misfire_policy="skip",
        next_fire_at=past,
        enabled=True,
        created_at=past,
        updated_at=past,
    )
    await store.upsert(row)
    store.close()

    store2 = SQLiteScheduledTaskStore(db_path)
    sched = RuntimeScheduler(store=store2)
    await sched.start()
    tasks = sched.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].next_fire_at > time.time() - 1  # 应该在未来 (允许少许偏差)
    await sched.stop()
    store2.close()


async def test_misfire_fire_once_triggers_immediately(tmp_path: Path) -> None:
    """next_fire_at 为过去时间的 interval 任务 (misfire=fire_once), 注册回调后 callback 被调用."""
    db_path = tmp_path / "sched.db"
    store = SQLiteScheduledTaskStore(db_path)

    past = time.time() - 3600
    row = ScheduledTaskRow(
        task_id="t1",
        owner="test",
        schedule_type="interval",
        schedule_spec={"interval_seconds": 3600},
        misfire_policy="fire_once",
        next_fire_at=past,
        enabled=True,
        created_at=past,
        updated_at=past,
    )
    await store.upsert(row)
    store.close()

    count = 0

    async def cb() -> None:
        nonlocal count
        count += 1

    store2 = SQLiteScheduledTaskStore(db_path)
    sched = RuntimeScheduler(store=store2)
    await sched.start()

    # 重新注册以绑定 callback (保留恢复的 next_fire_at)
    await sched.register(
        task_id="t1",
        owner="test",
        schedule=IntervalSchedule(seconds=3600),
        callback=cb,
        persist=True,
        misfire_policy="fire_once",
    )

    await asyncio.sleep(0.15)
    await sched.stop()
    assert count >= 1
    store2.close()


# endregion
