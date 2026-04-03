# Phase 3a: Scheduler - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver a lightweight asyncio scheduler supporting cron, interval, and one-shot tasks with persistence, plugin lifecycle binding, and graceful shutdown. This is pure runtime infrastructure — no UI, no user-facing features.

</domain>

<decisions>
## Implementation Decisions

### 持久化策略
- **D-01:** 使用 SQLite 存储, 复用现有 `runtime_data/acabot.db`, 新建 `scheduled_tasks` 表
- **D-02:** 每个任务有 `persist` 开关 — `persist=True` 的任务写入 DB, 重启后恢复; `persist=False` 的任务仅在内存中, 重启后消失
- **D-03:** Per-task misfire policy: 先实现 `skip` 和 `fire_once` 两种策略, 默认 `skip`. `skip` = 跳过错过的触发到下一次; `fire_once` = 重启后补执行一次

### 回调形态
- **D-04:** 任务回调为 async callable (coroutine function). 插件注册时传入回调函数. v2 扩展 (schedule-triggered agent runs) 可以包装 agent run 为一个 coroutine
- **D-05:** 任务回调报错时 log error + 继续调度, 不影响其他任务. 与 Phase 2 插件错误隔离原则一致

### 注册 API
- **D-06:** 统一 `register()` 方法: `scheduler.register(task_id, owner, schedule, callback, persist=False, misfire='skip')`. `schedule` 参数为 union type (`CronSchedule | IntervalSchedule | OneShotSchedule`)

### Claude's Discretion
- croniter 作为 cron 解析库 (轻量, 纯 Python)
- SQLite 表结构设计 (字段定义)
- Scheduler 内部 loop 实现细节 (sleep 精度, next_fire_time 计算)
- 测试策略和 mock 方式

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 依赖的 Phase 2 产物
- `src/acabot/runtime/plugins/plugin_runtime_host.py` — PluginRuntimeHost, 提供 unload lifecycle hook. Scheduler 的 `unregister_by_owner` 需要与 plugin unload 事件集成
- `src/acabot/runtime/plugins/plugin_protocol.py` — RuntimePlugin protocol 定义

### RuntimeApp 生命周期
- `src/acabot/runtime/app.py` — start()/stop() 方法, scheduler 需要在 start 后启动, stop 时最先关闭

### 现有 SQLite 存储模式
- `src/acabot/runtime/storage/sqlite_stores.py` — SQLite store 实现模式 (DDL, asyncio.Lock, CRUD 方法)
- `src/acabot/runtime/storage/stores.py` — Store ABC 定义

### Bootstrap 集成
- `src/acabot/runtime/bootstrap/__init__.py` — DI 组装点, 需要构造 Scheduler 并注入

### 现有异步任务模式
- `src/acabot/runtime/memory/long_term_ingestor.py` — 现有 background worker 模式参考 (asyncio.Event + worker loop)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `sqlite_stores.py` — SQLite CRUD 模式, DDL inline 定义, asyncio.Lock 保护
- `long_term_ingestor.py` — Background async worker 模式 (asyncio.Event 信号 + worker loop)
- `RuntimeComponents` dataclass — 新增 scheduler 字段

### Established Patterns
- DI via constructor injection + factory in bootstrap/
- `asyncio.Lock` for thread-safe mutations
- `logging.getLogger("acabot.runtime.scheduler")` for module-level logger
- Graceful shutdown via `asyncio.Event` + signal handlers

### Integration Points
- `bootstrap/__init__.py` — 构造 Scheduler, 传入 DB path
- `app.py` start() — scheduler.start() 在其他组件启动后调用
- `app.py` stop() — scheduler.stop() 在其他组件停止前调用 (最先关闭)
- `plugin_runtime_host.py` unload — 触发 scheduler.unregister_by_owner(plugin_id)

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

- SCHED-V2-01: Schedule-triggered agent runs — v2 需求, v1 的 async callable 接口设计需兼容未来扩展
- SCHED-V2-02: WebUI 定时任务管理页面 — v2 需求

</deferred>

---

*Phase: 3a-scheduler*
*Context gathered: 2026-04-03*
