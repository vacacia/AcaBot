# Phase 3a Scheduler — Research

## 1. croniter 库 API 研究

### 1.1 基本信息

- **PyPI**: `croniter` (当前稳定版 >= 2.0)
- **License**: MIT
- **依赖**: 仅 `python-dateutil`
- **Python 版本**: 支持 3.7+, 与项目 3.11+ 兼容

### 1.2 核心 API

```python
from croniter import croniter
from datetime import datetime

# 创建迭代器, base 是起始时间
cron = croniter("0 9 * * *", base=datetime.now())

# get_next(ret_type) — 返回下一次触发时间
next_fire: float = cron.get_next(float)       # Unix timestamp
next_fire: datetime = cron.get_next(datetime)  # datetime 对象

# 每次调用 get_next() 内部游标会前进, 连续调用得到连续的触发时间

# 验证表达式合法性
croniter.is_valid("0 9 * * MON-FRI")  # True
croniter.is_valid("invalid")           # False

# 检查某个时间是否匹配 cron 表达式
croniter.match("*/5 * * * *", datetime(2025, 1, 1, 0, 5))  # True

# 重置游标
cron.set_current(datetime.now())
```

### 1.3 对 Scheduler 的使用方式

计算 next_fire_at 的模式:

```python
def compute_next_fire(cron_expr: str, after: float) -> float:
    """计算 cron 表达式在 after 之后的下一次触发时间."""
    cron = croniter(cron_expr, start_time=after)
    return cron.get_next(float)  # 返回 Unix timestamp float
```

关键点:
- 每次只需要一个 `croniter` 实例, 用完即弃, 不需要长期持有
- `start_time` 接受 `float` (Unix timestamp) 或 `datetime`
- 返回值用 `float` 最方便, 与 `time.time()` 直接比较
- **验证**: 注册时用 `croniter.is_valid()` 提前校验, 避免运行时出错

### 1.4 新增依赖

需要在 `pyproject.toml` 添加:
```toml
"croniter>=2.0.0",
```

以及在 Dockerfile / Dockerfile.lite 确认 `croniter` 通过 pip install 安装 (它跟随 pyproject.toml 所以自动包含).

---

## 2. asyncio 调度循环设计

### 2.1 方案对比

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **A: sleep-to-next** | 每次 sleep 到最近任务的 fire_time | 简单, CPU 几乎零开销 | 新任务注册时需唤醒循环 |
| **B: 固定间隔轮询** | 每 N 秒扫一遍待触发任务 | 实现极简 | 精度受限于间隔, 浪费 CPU |
| **C: heapq + asyncio.Event** | heapq 管理 fire_time, Event 唤醒 | 精确, O(log n) 插入 | 实现稍复杂 |

### 2.2 推荐方案: C (heapq + asyncio.Event)

结合 AcaBot 现有模式 (LongTermMemoryIngestor 的 `asyncio.Event` + worker loop), 推荐:

```
主循环:
  1. 从 heapq 取 heap[0] 的 fire_time
  2. 计算 delay = fire_time - now
  3. 如果 delay > 0: 等待 min(delay, wake_event) — 用 asyncio.wait_for 或 Event.wait(timeout=delay)
  4. 如果 delay <= 0: 执行回调, 计算下次 fire_time, 重新入堆
  5. 如果堆空: 等待 wake_event (无限等待直到有新任务注册)
```

唤醒机制:
- `register()` 时 `self._wake_event.set()` — 新任务可能比当前堆顶更早
- `cancel()` 时 `self._wake_event.set()` — 堆顶可能被取消, 需要跳过
- `stop()` 时 `self._wake_event.set()` — 通知循环退出

### 2.3 heapq 数据结构

```python
@dataclass(order=True)
class _ScheduledEntry:
    fire_at: float                    # heapq 排序键
    task_id: str = field(compare=False)
    cancelled: bool = field(default=False, compare=False)
```

- 取消时不从堆中移除 (lazy deletion), 只标记 `cancelled=True`
- 弹出时检查 cancelled, 跳过已取消的条目
- 这是标准的 heapq cancellation 模式, 避免 O(n) 查找

### 2.4 回调执行模式

回调是 async callable, 用 `asyncio.create_task` 包装:

```python
async def _fire_task(self, task: ScheduledTask) -> None:
    try:
        await task.callback()
    except Exception:
        logger.exception("Scheduled task callback failed: task_id=%s", task.task_id)
    # 回调失败不影响调度继续 (SCHED-05 要求)
```

关键决策: **串行 vs 并行执行回调**
- 推荐 **fire-and-forget** (`asyncio.create_task`), 不阻塞调度循环
- 但需要在 `stop()` 时 gather 所有 pending callback tasks
- 这与 LongTermMemoryIngestor 的处理方式一致

---

## 3. SQLite 持久化 Schema 设计

### 3.1 复用现有数据库

按 D-01 决策, 复用 `runtime_data/acabot.db`. 现有 `_SQLiteStoreBase` 提供:
- 目录创建 (`db_path.parent.mkdir`)
- WAL 模式 (`PRAGMA journal_mode=WAL`)
- `asyncio.Lock` 并发保护
- JSON 编解码辅助方法

新的 `SQLiteScheduledTaskStore` 继承 `_SQLiteStoreBase`, 与其他 store 共享同一个 db_path.

**注意**: 当前每个 store 各自创建独立的 `sqlite3.Connection`. 这意味着即使 db_path 相同, 连接也是独立的. WAL 模式下这是安全的 (多 reader 并发, writer 串行). Scheduler store 沿用同样模式即可.

### 3.2 表结构

```sql
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    task_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,              -- 注册来源标识 (如 "plugin:xxx" 或 "system")
    schedule_type TEXT NOT NULL,      -- "cron" | "interval" | "one_shot"
    schedule_spec TEXT NOT NULL,      -- JSON: cron_expr / interval_seconds / fire_at
    misfire_policy TEXT NOT NULL DEFAULT 'skip',  -- "skip" | "fire_once"
    next_fire_at REAL NOT NULL,       -- Unix timestamp (float), 下次触发时间
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

### 3.3 字段说明

- **task_id**: 调用者提供或自动生成, 用于 cancel/查询
- **owner**: 用于 `unregister_by_owner()`, 插件卸载时按 owner 批量清理
- **schedule_type**: 枚举 `"cron" | "interval" | "one_shot"`
- **schedule_spec**: JSON 字符串, 不同类型存不同内容:
  - cron: `{"cron_expr": "0 9 * * *"}`
  - interval: `{"interval_seconds": 300}`
  - one_shot: `{"fire_at": 1712345678.0}`
- **misfire_policy**: 重启后发现 next_fire_at 已过期时的策略
- **next_fire_at**: 浮点 Unix timestamp, 是调度循环的排序键
- **enabled**: 软删除/暂停支持
- **metadata_json**: 扩展字段, 存储任务描述等

### 3.4 持久化 vs 内存任务

按 D-02 决策, `persist` 标志控制:
- `persist=True`: 写入 SQLite, 重启后从 DB 恢复
- `persist=False`: 仅内存中的 dict + heapq 条目, 重启后丢失

内存任务和持久化任务共享同一个 heapq 调度循环, 区别仅在于是否写入 DB.

### 3.5 Misfire 恢复策略 (D-03)

重启时加载 DB 中 `enabled=1` 的任务:

```python
async def _recover_tasks(self) -> None:
    persisted = await self._store.list_enabled_tasks()
    now = time.time()
    for row in persisted:
        if row.schedule_type == "one_shot" and row.next_fire_at < now:
            if row.misfire_policy == "fire_once":
                # 立即触发一次, 然后标记完成
                await self._fire_and_complete(row)
            else:
                # skip: 过期的 one_shot 直接禁用
                await self._store.disable(row.task_id)
            continue
        if row.next_fire_at < now:
            if row.misfire_policy == "fire_once":
                # 立即触发一次, 然后推进到下一个正常时间
                await self._fire_once_and_reschedule(row, now)
            else:
                # skip: 直接推进到下一个 >= now 的触发时间
                next_fire = self._compute_next_fire(row, now)
                await self._store.update_next_fire(row.task_id, next_fire)
        # 入堆
        self._enqueue(row.task_id, row.next_fire_at)
```

---

## 4. Plugin 生命周期绑定 (SCHED-07)

### 4.1 现有卸载流程

`PluginRuntimeHost.unload_plugin()` (L257-313) 的流程:
1. `ToolBroker.unregister_source(source)` — 按 source 标签清理工具
2. 注销 model targets
3. `plugin.teardown()` — 插件自身清理
4. 移除 hooks, 重建 registry
5. 从已加载集合移除

### 4.2 Scheduler 集成点

在 `unload_plugin()` 步骤 1 之后 (或之前), 增加:

```python
# 1.5 注销定时任务
if self._scheduler is not None:
    cancelled = await self._scheduler.unregister_by_owner(f"plugin:{plugin_id}")
    if cancelled:
        logger.info("Plugin scheduled tasks cancelled: plugin=%s count=%s", plugin_id, len(cancelled))
```

### 4.3 owner 命名约定

与 ToolBroker 的 `source` 保持一致:
- 插件: `"plugin:{plugin_id}"` (如 `"plugin:napcat_tools"`)
- 系统内置: `"system"` 或 `"builtin:{name}"`
- 手动注册: 调用者自行指定

### 4.4 注入方式

`PluginRuntimeHost.__init__` 新增可选参数:

```python
def __init__(
    self,
    tool_broker: ToolBroker,
    model_target_catalog: MutableModelTargetCatalog | None = None,
    scheduler: RuntimeScheduler | None = None,  # 新增
) -> None:
```

保持向后兼容: `scheduler=None` 时 unload 跳过定时任务清理.

### 4.5 插件注册定时任务

插件通过 `RuntimePluginContext` 获取 scheduler:

```python
@dataclass
class RuntimePluginContext:
    # ... 现有字段 ...
    scheduler: RuntimeScheduler | None = None  # 新增
```

插件在 `setup()` 中注册任务:

```python
class MyPlugin(RuntimePlugin):
    async def setup(self, ctx: RuntimePluginContext) -> None:
        if ctx.scheduler:
            await ctx.scheduler.register(
                task_id="my_plugin:daily_cleanup",
                owner=f"plugin:{self.name}",
                schedule=CronSchedule(cron_expr="0 3 * * *"),
                callback=self._daily_cleanup,
                persist=True,
            )
```

---

## 5. RuntimeApp 生命周期集成 (SCHED-08)

### 5.1 现有 start/stop 顺序

**start()** (app.py L119-141):
1. `recover_active_runs()`
2. `plugin_reconciler.reconcile_all()`
3. `long_term_memory_ingestor.start()`
4. `install()` (注册 event handler)
5. `gateway.start()`

**stop()** (app.py L143-165):
1. `gateway.stop()`
2. `plugin_runtime_host.teardown_all()`
3. `long_term_memory_ingestor.stop()`

### 5.2 Scheduler 插入位置

**start()**: 在 `long_term_memory_ingestor.start()` 之后, `gateway.start()` 之前:

```python
async def start(self) -> None:
    await self.recover_active_runs()
    if self.plugin_reconciler is not None:
        await self.plugin_reconciler.reconcile_all()
    try:
        if self.long_term_memory_ingestor is not None:
            await self.long_term_memory_ingestor.start()
        if self.scheduler is not None:
            await self.scheduler.start()  # <-- 新增
        self.install()
        await self.gateway.start()
    except Exception:
        # 反向清理
        if self.scheduler is not None:
            try:
                await self.scheduler.stop()
            except Exception:
                logger.exception("Failed to stop scheduler after gateway start failure")
        if self.long_term_memory_ingestor is not None:
            ...
```

**stop()**: 在 `gateway.stop()` 之后, `plugin_runtime_host.teardown_all()` 之前:

```python
async def stop(self) -> None:
    stop_error = None
    try:
        await self.gateway.stop()
    except Exception as exc:
        stop_error = exc
    # Scheduler 在 plugin teardown 之前停止 — 这样 plugin teardown
    # 中不会有新的定时任务触发
    if self.scheduler is not None:
        try:
            await self.scheduler.stop()
        except Exception as exc:
            logger.exception("Failed to stop scheduler during shutdown")
            if stop_error is None:
                stop_error = exc
    if self.plugin_runtime_host is not None:
        ...
```

理由:
- start 时 scheduler 在 plugin reconcile 之后启动, 这样插件注册的任务都已就绪
- stop 时 scheduler 在 plugin teardown 之前停止, 防止 teardown 期间任务还在触发

### 5.3 Bootstrap 集成

在 `build_runtime_components()` 中:

```python
from ..scheduler import RuntimeScheduler, SQLiteScheduledTaskStore

# 创建 store
scheduler_store = SQLiteScheduledTaskStore(db_path=runtime_db_path)

# 创建 scheduler
runtime_scheduler = RuntimeScheduler(store=scheduler_store)

# 注入到 PluginRuntimeHost
runtime_plugin_host = PluginRuntimeHost(
    tool_broker=runtime_tool_broker,
    model_target_catalog=runtime_model_registry_manager.target_catalog,
    scheduler=runtime_scheduler,
)

# 注入到 RuntimeApp
app = RuntimeApp(
    ...,
    scheduler=runtime_scheduler,
)

# 注入到 RuntimeComponents
# (需要在 RuntimeComponents dataclass 新增 scheduler 字段)
```

---

## 6. Graceful Shutdown 设计 (SCHED-06)

### 6.1 停机流程

```python
async def stop(self) -> None:
    if not self._started:
        return
    self._stopping = True
    self._wake_event.set()  # 唤醒主循环让它检查 _stopping

    # 等待主循环退出
    if self._worker_task is not None:
        await self._worker_task
        self._worker_task = None

    # 等待所有正在执行的回调完成
    if self._running_callbacks:
        await asyncio.gather(*self._running_callbacks, return_exceptions=True)
        self._running_callbacks.clear()

    self._started = False
    self._stopping = False
```

### 6.2 与 LongTermMemoryIngestor 对比

模式完全一致:
- `_started` / `_stopping` 双标志
- `asyncio.Event` 唤醒
- worker loop 每次迭代检查 `_stopping`
- stop() 等待 worker_task 完成

额外增加: `_running_callbacks` 列表跟踪 fire-and-forget 的 callback tasks, stop 时 gather.

---

## 7. 公共 API 设计草案

### 7.1 Schedule 类型 (D-06)

```python
@dataclass(frozen=True, slots=True)
class CronSchedule:
    cron_expr: str

@dataclass(frozen=True, slots=True)
class IntervalSchedule:
    seconds: float

@dataclass(frozen=True, slots=True)
class OneShotSchedule:
    fire_at: float  # Unix timestamp

ScheduleType = CronSchedule | IntervalSchedule | OneShotSchedule
```

### 7.2 RuntimeScheduler 主接口

```python
class RuntimeScheduler:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def register(
        self,
        *,
        task_id: str,
        owner: str,
        schedule: ScheduleType,
        callback: Callable[[], Awaitable[None]],
        persist: bool = False,
        misfire_policy: Literal["skip", "fire_once"] = "skip",
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def cancel(self, task_id: str) -> bool: ...
    async def unregister_by_owner(self, owner: str) -> list[str]: ...
    def list_tasks(self) -> list[ScheduledTaskInfo]: ...
```

### 7.3 回调签名

```python
# 最简形式: 无参 async callable
Callable[[], Awaitable[None]]
```

对于持久化任务, callback 不可序列化. 恢复策略:
- 持久化任务在重启后不自动恢复回调
- 需要注册者 (插件/系统) 在 `setup()` / `start()` 时重新注册 callback
- DB 只保存 schedule 元数据, 不保存 callback
- 恢复时: 加载 DB 中的 task 元数据 + 计算 next_fire_at, 但标记为 "pending_callback"
- 注册者重新 `register()` 同一个 task_id 时, 合并已有的 schedule 状态 + 新的 callback

这是一个关键设计决策: **DB 存储调度状态, 内存存储回调引用. 两者通过 task_id 关联.**

---

## 8. 文件布局

```
src/acabot/runtime/scheduler/
    __init__.py          # 公共 API 导出
    contracts.py         # CronSchedule, IntervalSchedule, OneShotSchedule, ScheduledTaskInfo
    scheduler.py         # RuntimeScheduler 主类
    store.py             # SQLiteScheduledTaskStore
```

---

## 9. 依赖总结

| 变更 | 文件 |
|------|------|
| 新增 `croniter>=2.0.0` | `pyproject.toml` |
| 新增 `scheduled_tasks` 表 | `src/acabot/runtime/scheduler/store.py` |
| 新增 `RuntimeScheduler` | `src/acabot/runtime/scheduler/scheduler.py` |
| 修改 `PluginRuntimeHost` | 新增 `scheduler` 参数, `unload_plugin()` 增加清理步骤 |
| 修改 `RuntimePluginContext` | 新增 `scheduler` 字段 |
| 修改 `RuntimeApp` | 新增 `scheduler` 参数, `start()/stop()` 增加调度器生命周期 |
| 修改 `RuntimeComponents` | 新增 `scheduler` 字段 |
| 修改 `build_runtime_components()` | 创建并注入 scheduler |

---

## 10. 风险和注意事项

1. **回调不可序列化**: 持久化任务重启后需要注册者重新绑定 callback. 如果注册者没有重新 register, 任务会留在 DB 但不会触发. 需要在日志中明确标记这种情况.

2. **时钟漂移**: croniter 基于系统时钟. Docker 容器内时钟通常与宿主机同步, 但如果容器暂停/恢复, 可能出现时间跳跃. misfire_policy 可以缓解这个问题.

3. **并发安全**: 调度循环是单 task, 注册/取消通过 asyncio 协作式并发保护 (单线程事件循环). 不需要额外的锁. SQLite 操作沿用 `asyncio.Lock` 模式.

4. **croniter 版本兼容**: `croniter>=2.0.0` 放弃了 Python 2 支持, API 更稳定. 需要确认 uv.lock 中的版本解析.

5. **精度**: asyncio sleep 精度通常在毫秒级, 对于 cron (分钟级) 和 interval (秒级) 场景完全足够.
