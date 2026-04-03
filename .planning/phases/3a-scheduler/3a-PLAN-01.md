# Phase 3a Wave 1: Core Scheduler

**Requirements:** SCHED-01, SCHED-02, SCHED-03, SCHED-04, SCHED-05, SCHED-06

## Overview

构建 RuntimeScheduler 核心: contracts, SQLite store, 调度主循环, 单元测试.
完成后 scheduler 可独立运行 (不依赖 plugin/app 集成), 支持 cron/interval/one-shot 调度, 持久化恢复, 任务取消, 优雅关闭.

---

## Task 1: 新增 croniter 依赖

**文件:** `pyproject.toml`

**操作:** 修改

**内容:**
- 在 `[project] dependencies` 列表中添加 `"croniter>=2.0.0"`

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "from croniter import croniter; print(croniter.is_valid('0 9 * * *'))"
```

---

## Task 2: 创建 contracts.py

**文件:** `src/acabot/runtime/scheduler/contracts.py`

**操作:** 新建

**内容:**

定义以下类型:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MisfirePolicy = Literal["skip", "fire_once"]

@dataclass(frozen=True, slots=True)
class CronSchedule:
    """Cron 表达式调度.

    Attributes:
        cron_expr: 标准 5 段 cron 表达式 (分 时 日 月 周).
    """
    cron_expr: str

@dataclass(frozen=True, slots=True)
class IntervalSchedule:
    """固定间隔调度.

    Attributes:
        seconds: 间隔秒数 (float, 支持亚秒但精度不保证).
    """
    seconds: float

@dataclass(frozen=True, slots=True)
class OneShotSchedule:
    """一次性延迟执行.

    Attributes:
        fire_at: 触发时间 (Unix timestamp float).
    """
    fire_at: float

ScheduleType = CronSchedule | IntervalSchedule | OneShotSchedule

@dataclass(frozen=True, slots=True)
class ScheduledTaskInfo:
    """任务的只读快照, 供外部查询.

    Attributes:
        task_id: 任务唯一标识.
        owner: 注册来源标识.
        schedule: 调度配置.
        persist: 是否持久化.
        misfire_policy: misfire 策略.
        next_fire_at: 下次触发时间 (Unix timestamp).
        enabled: 是否启用.
        metadata: 扩展元数据.
    """
    task_id: str
    owner: str
    schedule: ScheduleType
    persist: bool
    misfire_policy: MisfirePolicy
    next_fire_at: float
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class ScheduledTaskRow:
    """DB 行到内存的映射. 内部使用.

    Attributes:
        task_id: 任务 ID.
        owner: 注册来源.
        schedule_type: "cron" | "interval" | "one_shot".
        schedule_spec: JSON 反序列化后的 dict.
        misfire_policy: misfire 策略.
        next_fire_at: 下次触发时间.
        enabled: 是否启用.
        created_at: 创建时间.
        updated_at: 最近更新时间.
        metadata: 扩展元数据.
    """
    task_id: str
    owner: str
    schedule_type: str
    schedule_spec: dict[str, Any]
    misfire_policy: MisfirePolicy
    next_fire_at: float
    enabled: bool
    created_at: float
    updated_at: float
    metadata: dict[str, Any] = field(default_factory=dict)
```

辅助函数:

```python
def schedule_to_type_and_spec(schedule: ScheduleType) -> tuple[str, dict[str, Any]]:
    """把 ScheduleType union 转换为 (schedule_type, schedule_spec) 用于 DB 存储."""
    # CronSchedule -> ("cron", {"cron_expr": ...})
    # IntervalSchedule -> ("interval", {"interval_seconds": ...})
    # OneShotSchedule -> ("one_shot", {"fire_at": ...})

def spec_to_schedule(schedule_type: str, schedule_spec: dict[str, Any]) -> ScheduleType:
    """从 DB 的 (schedule_type, schedule_spec) 恢复 ScheduleType."""
```

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "from acabot.runtime.scheduler.contracts import CronSchedule, IntervalSchedule, OneShotSchedule, ScheduledTaskInfo; print('OK')"
```

---

## Task 3: 创建 `__init__.py`

**文件:** `src/acabot/runtime/scheduler/__init__.py`

**操作:** 新建

**内容:**
- 模块 docstring: "runtime.scheduler 提供轻量级异步定时任务调度器."
- 从 `contracts` 导出: `CronSchedule`, `IntervalSchedule`, `OneShotSchedule`, `ScheduleType`, `ScheduledTaskInfo`, `MisfirePolicy`
- 从 `scheduler` 导出: `RuntimeScheduler`
- 从 `store` 导出: `SQLiteScheduledTaskStore`
- `__all__` 列表包含所有公共导出

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "from acabot.runtime.scheduler import CronSchedule, RuntimeScheduler, SQLiteScheduledTaskStore; print('OK')"
```
(此验证在 Task 4 和 Task 5 完成后才能通过)

---

## Task 4: 创建 store.py

**文件:** `src/acabot/runtime/scheduler/store.py`

**操作:** 新建

**内容:**

`SQLiteScheduledTaskStore` 继承 `_SQLiteStoreBase` (从 `acabot.runtime.storage.sqlite_stores` 导入):

```python
class SQLiteScheduledTaskStore(_SQLiteStoreBase):
    """SQLite 持久化的定时任务存储."""
```

**构造函数:**
- `__init__(self, db_path: str | Path)` -- 调用 `super().__init__(db_path)`, 然后执行建表 DDL

**DDL (在 `__init__` 中执行):**
```sql
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    task_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    schedule_spec TEXT NOT NULL,
    misfire_policy TEXT NOT NULL DEFAULT 'skip',
    next_fire_at REAL NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_fire
    ON scheduled_tasks(enabled, next_fire_at);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_owner
    ON scheduled_tasks(owner);
```

**方法清单 (全部 async, 内部使用 `self._lock`):**

1. `async def upsert(self, row: ScheduledTaskRow) -> None`
   - INSERT OR REPLACE 完整行
   - schedule_spec 和 metadata 用 `_encode_json` 序列化

2. `async def delete(self, task_id: str) -> bool`
   - DELETE WHERE task_id=?, 返回是否删除了行

3. `async def delete_by_owner(self, owner: str) -> list[str]`
   - DELETE WHERE owner=?, 返回被删除的 task_id 列表
   - 先 SELECT task_id 再 DELETE (获取被删除的 ID)

4. `async def update_next_fire_at(self, task_id: str, next_fire_at: float) -> None`
   - UPDATE scheduled_tasks SET next_fire_at=?, updated_at=? WHERE task_id=?

5. `async def disable(self, task_id: str) -> None`
   - UPDATE scheduled_tasks SET enabled=0, updated_at=? WHERE task_id=?

6. `async def list_enabled(self) -> list[ScheduledTaskRow]`
   - SELECT * FROM scheduled_tasks WHERE enabled=1 ORDER BY next_fire_at
   - 解码 schedule_spec 和 metadata_json
   - 返回 ScheduledTaskRow 列表

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.scheduler.store import SQLiteScheduledTaskStore
store = SQLiteScheduledTaskStore('/tmp/test_sched.db')
print('Store created OK')
store.close()
"
```

---

## Task 5: 创建 scheduler.py

**文件:** `src/acabot/runtime/scheduler/scheduler.py`

**操作:** 新建

**内容:**

### 5.1 内部 heapq entry

```python
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
```

### 5.2 内部任务记录

```python
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
```

### 5.3 RuntimeScheduler 类

```python
class RuntimeScheduler:
    """轻量级 asyncio 定时任务调度器.

    支持 cron / interval / one-shot 三种调度类型.
    使用 heapq + asyncio.Event 实现精确唤醒.
    """
```

**构造函数:**
```python
def __init__(self, *, store: SQLiteScheduledTaskStore | None = None) -> None:
```

**实例属性:**
- `_store: SQLiteScheduledTaskStore | None` -- 持久化 store (可选, None 时不支持 persist)
- `_tasks: dict[str, _TaskRecord]` -- task_id -> 任务记录
- `_heap: list[_HeapEntry]` -- heapq 管理的触发时间优先队列
- `_wake_event: asyncio.Event` -- 唤醒主循环
- `_worker_task: asyncio.Task[None] | None` -- 主循环 task
- `_running_callbacks: set[asyncio.Task[None]]` -- 正在执行的回调 task 集合
- `_started: bool` -- 是否已启动
- `_stopping: bool` -- 是否正在停机
- `logger = logging.getLogger("acabot.runtime.scheduler")`

**公共方法:**

1. **`async def start(self) -> None`**
   - 检查 `_started`, 防止重复启动
   - 调用 `_recover_persisted_tasks()` 恢复持久化任务
   - 创建 `_worker_task = asyncio.create_task(self._worker_loop())`
   - 设置 `_started = True`

2. **`async def stop(self) -> None`**
   - 设置 `_stopping = True`
   - `_wake_event.set()` 唤醒主循环
   - `await self._worker_task` 等待主循环退出
   - `await asyncio.gather(*self._running_callbacks, return_exceptions=True)` 等待所有回调完成
   - 清理 `_running_callbacks`, 重置 `_started`, `_stopping`

3. **`async def register(self, *, task_id, owner, schedule, callback, persist=False, misfire_policy="skip", metadata=None) -> None`**
   - 验证 schedule 合法性:
     - CronSchedule: `croniter.is_valid(cron_expr)`, 否则 raise `ValueError`
     - IntervalSchedule: `seconds > 0`, 否则 raise `ValueError`
     - OneShotSchedule: `fire_at` 必须是正数, 否则 raise `ValueError`
   - 如果 `task_id` 已存在, 更新 (取消旧 heap entry, 重新入堆). 这支持持久化任务恢复时重新绑定 callback
   - 计算 `next_fire_at`:
     - CronSchedule: `croniter(cron_expr, start_time=time.time()).get_next(float)`
     - IntervalSchedule: `time.time() + seconds`
     - OneShotSchedule: `fire_at` 直接使用
     - 特殊: 如果 task_id 已存在于 `_tasks` 且旧 `next_fire_at` 仍在未来, 保留旧值 (持久化恢复场景)
   - 构造 `_TaskRecord`, 存入 `_tasks`
   - 如果 `persist=True` 且 `_store is not None`: 调用 `_store.upsert()`
   - 入堆: `heapq.heappush(self._heap, entry)`, 设置 `record.heap_entry = entry`
   - `_wake_event.set()` 唤醒主循环

4. **`async def cancel(self, task_id: str) -> bool`**
   - 查找 `_tasks[task_id]`, 不存在返回 False
   - 标记 `heap_entry.cancelled = True` (lazy deletion)
   - 从 `_tasks` 移除
   - 如果 persist: 调用 `_store.delete(task_id)`
   - `_wake_event.set()` 唤醒主循环
   - 返回 True

5. **`async def unregister_by_owner(self, owner: str) -> list[str]`**
   - 遍历 `_tasks`, 找出所有 `record.owner == owner` 的 task_id
   - 对每个调用 `cancel()`
   - 如果 `_store is not None`: 调用 `_store.delete_by_owner(owner)` (批量清理, 兜底)
   - 返回被取消的 task_id 列表

6. **`def list_tasks(self) -> list[ScheduledTaskInfo]`**
   - 遍历 `_tasks.values()`, 构造 `ScheduledTaskInfo` 列表返回

**私有方法:**

7. **`async def _worker_loop(self) -> None`**
   - 主循环, 直到 `_stopping`:
     - 如果 `_heap` 为空: `self._wake_event.clear()`, `await self._wake_event.wait()`, continue
     - 查看 `self._heap[0]`:
       - 如果 `cancelled`: `heapq.heappop`, continue
       - 计算 `delay = entry.fire_at - time.time()`
       - 如果 `delay > 0`: `self._wake_event.clear()`, `try: await asyncio.wait_for(self._wake_event.wait(), timeout=delay) except asyncio.TimeoutError: pass`, continue (回到循环顶部重新检查)
       - `delay <= 0`: pop entry, 执行触发逻辑
     - 触发逻辑:
       - 从 `_tasks` 取 `record`, 如果不存在 (已被 cancel) 则 continue
       - 调用 `_fire_task(record)`
       - 计算并设置 next_fire_at, 重新入堆 (cron/interval), 或标记完成 (one_shot)

8. **`def _fire_task(self, record: _TaskRecord) -> None`**
   - **首先检查 `record.callback is None`**: 如果是则 `logger.warning("Skipping task with no callback: task_id=%s", record.task_id)`, 直接 return (持久化任务恢复后 callback 未重新绑定的情况)
   - `task = asyncio.create_task(self._execute_callback(record))`, 加入 `_running_callbacks`
   - 添加 done_callback 从 `_running_callbacks` 中移除

9. **`async def _execute_callback(self, record: _TaskRecord) -> None`**
   - `try: await record.callback() except Exception: logger.exception("task_id=%s", record.task_id)`

10. **`def _compute_next_fire(self, record: _TaskRecord, after: float) -> float | None`**
    - CronSchedule: `croniter(cron_expr, start_time=after).get_next(float)`
    - IntervalSchedule: `after + seconds`
    - OneShotSchedule: 返回 `None` (一次性, 不重复)

11. **`def _enqueue(self, task_id: str, fire_at: float) -> _HeapEntry`**
    - 创建 `_HeapEntry(fire_at, task_id)`, `heapq.heappush(self._heap, entry)`, 返回 entry

12. **`async def _recover_persisted_tasks(self) -> None`**
    - 如果 `_store is None`: 直接返回
    - 调用 `_store.list_enabled()` 获取所有启用的持久化任务
    - 对每个 row:
      - 恢复 `ScheduleType` (从 `schedule_type` + `schedule_spec`)
      - `now = time.time()`
      - 如果 `row.next_fire_at < now`:
        - one_shot + skip: `_store.disable(task_id)`, 跳过
        - one_shot + fire_once: 设 `next_fire_at = now` (立即触发, 后续 worker loop 处理)
        - cron/interval + skip: 推进到下一个 >= now 的触发时间, `_store.update_next_fire_at()`
        - cron/interval + fire_once: 设 `next_fire_at = now` (补触发一次, 之后正常调度)
      - 构造 `_TaskRecord` (callback 设为 None -- 持久化任务恢复后 callback 为空)
      - 入堆
      - 日志记录恢复数量
    - 注意: callback=None 的任务在触发时检查 callback is None, 如果是则 log warning 并跳过

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.scheduler import RuntimeScheduler, SQLiteScheduledTaskStore
store = SQLiteScheduledTaskStore('/tmp/test_sched2.db')
scheduler = RuntimeScheduler(store=store)
print('RuntimeScheduler created OK')
store.close()
"
```

---

## Task 6: 创建单元测试

**文件:** `tests/test_scheduler.py`

**操作:** 新建

**测试用例清单 (全部 async, 使用 pytest-asyncio):**

### 6.1 Store 测试

- **`test_store_upsert_and_list`**: upsert 一个 ScheduledTaskRow, list_enabled 返回它
- **`test_store_delete`**: upsert 后 delete, list_enabled 返回空
- **`test_store_delete_by_owner`**: upsert 两个不同 owner 的任务, delete_by_owner 只删对应 owner 的
- **`test_store_update_next_fire_at`**: upsert 后 update, list_enabled 中 next_fire_at 已更新
- **`test_store_disable`**: upsert 后 disable, list_enabled 不再返回该任务
- **`test_store_upsert_replaces_existing`**: 对同一 task_id upsert 两次, list_enabled 只有一条最新的

使用 `/tmp` 目录下的临时 db 文件 (用 pytest `tmp_path` fixture).

### 6.2 Scheduler 核心测试

使用 `store=None` (纯内存模式) 简化测试:

- **`test_register_and_list`**: register 一个 interval 任务, list_tasks 返回它
- **`test_cancel_returns_true_for_existing`**: register 后 cancel 返回 True
- **`test_cancel_returns_false_for_nonexistent`**: cancel 不存在的 task_id 返回 False
- **`test_unregister_by_owner`**: register 两个同 owner 的任务, unregister_by_owner 全部取消
- **`test_interval_fires_callback`**: register interval=0.05s 的任务, start, 等 0.15s, 验证 callback 至少被调用 2 次, stop
- **`test_one_shot_fires_once`**: register one_shot(fire_at=time.time()+0.05), start, 等 0.15s, 验证 callback 只被调用 1 次, stop
- **`test_cron_validates_expression`**: register 无效 cron 表达式, 期望 ValueError
- **`test_cron_fires_callback`**: register cron=`* * * * *` (每分钟触发, 但测试中 mock time 使 next_fire_at 接近 now), 或使用 `croniter` 预计算出一个 0.1s 后触发的时间窗口. 简化做法: register 后手动设 `record.next_fire_at = time.time() + 0.05`, 重新入堆, start, 等 0.15s, 验证 callback 被调用至少 1 次. 这测试 cron 任务经过 worker_loop 正确触发的完整路径
- **`test_interval_validates_positive`**: register seconds=0 或负数, 期望 ValueError
- **`test_graceful_shutdown_waits_callbacks`**: register 一个 callback 内部 sleep 0.1s 的任务 (interval=0.01), start, 等 0.05s, stop, 验证 stop 不会 raise (callback 正常结束)
- **`test_callback_error_does_not_stop_scheduler`**: register 一个抛异常的 callback (interval=0.05), start, 等 0.15s, 验证 scheduler 仍在运行 (_started=True), stop

### 6.3 持久化测试

- **`test_persist_task_survives_restart`**: 用 store 创建 scheduler, register persist=True 的 interval 任务, stop. 创建新的 scheduler (同一 store), start, 验证 list_tasks 包含该任务
- **`test_non_persist_task_lost_on_restart`**: 同上但 persist=False, 重启后 list_tasks 为空
- **`test_misfire_skip_advances_next_fire`**: 在 store 中插入 next_fire_at 为过去时间的 cron 任务 (misfire=skip), 新建 scheduler + start, 验证恢复后 next_fire_at > now
- **`test_misfire_fire_once_triggers_immediately`**: 在 store 中插入 next_fire_at 为过去时间的 interval 任务 (misfire=fire_once), 注册回调后 start, 等 0.1s, 验证 callback 被调用至少一次

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -m pytest tests/test_scheduler.py -v
```

---

## Task 7: 更新 runtime `__init__.py` 导出

**文件:** `src/acabot/runtime/__init__.py`

**操作:** 修改

**内容:**
- 添加 scheduler 相关导出到 facade:
  - `from .scheduler import RuntimeScheduler, CronSchedule, IntervalSchedule, OneShotSchedule, ScheduleType, ScheduledTaskInfo, SQLiteScheduledTaskStore, MisfirePolicy`
- 添加到 `__all__` (如果存在)

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "from acabot.runtime import RuntimeScheduler, CronSchedule; print('OK')"
```

---

## Execution Order

```
Task 1 (pyproject.toml) -- 无依赖
Task 2 (contracts.py)   -- 无依赖
Task 3 (__init__.py)     -- 依赖 Task 2, 4, 5
Task 4 (store.py)        -- 依赖 Task 2
Task 5 (scheduler.py)    -- 依赖 Task 1, 2, 4
Task 6 (tests)           -- 依赖 Task 1-5
Task 7 (runtime __init__) -- 依赖 Task 3
```

推荐顺序: Task 1 -> Task 2 -> Task 4 -> Task 5 -> Task 3 -> Task 7 -> Task 6

---

## Final Verification

全部 task 完成后执行:

```bash
# 1. 导入检查
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.scheduler import (
    RuntimeScheduler, SQLiteScheduledTaskStore,
    CronSchedule, IntervalSchedule, OneShotSchedule,
    ScheduleType, ScheduledTaskInfo, MisfirePolicy,
)
print('All imports OK')
"

# 2. 运行全部测试
cd /data/workspace/agent/AcaBot && python -m pytest tests/test_scheduler.py -v

# 3. 确认无新增 pyright 错误 (如果 pyright 可用)
cd /data/workspace/agent/AcaBot && python -m pyright src/acabot/runtime/scheduler/ --pythonversion 3.11 2>&1 | tail -5
```

---

*Phase: 3a-scheduler, Wave 1*
*Requirements: SCHED-01, SCHED-02, SCHED-03, SCHED-04, SCHED-05, SCHED-06*
