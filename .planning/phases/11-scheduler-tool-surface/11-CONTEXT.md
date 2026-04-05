# Phase 11: Scheduler Tool Surface - Context

**Gathered:** 2026-04-05
**Status:** Ready for research

<domain>
## Phase Boundary

模型通过 `scheduler` builtin tool 自主管理定时任务（创建/查看/取消），任务绑定到触发会话。HTTP API 同步实现供 Phase 13 WebUI 使用。

</domain>

<decisions>
## Implementation Decisions

### Inherited from Phase 3a
- **D-01:** SQLite 持久化 — 复用 `runtime_data/acabot.db`，新建 `scheduled_tasks` 表
- **D-02:** `persist=True` 任务写入 DB，重启后恢复执行
- **D-03:** misfire 默认 `skip` 策略
- **D-04:** callback 为 async callable，不捕获 ToolExecutionContext
- **D-05:** 使用 `ScheduledMessageDispatcher` 中间层解耦 callback 和执行上下文

### Tool Schema — OpenClaw 风格
- **D-06:** 单个 `scheduler` 工具 + action enum (`create` / `list` / `cancel`)
- **D-07:** schedule 用 discriminated union，`kind` + `spec` 分离：
  ```json
  // create
  {
    "action": "create",
    "schedule": {
      "kind": "cron",
      "spec": { "expr": "0 9 * * *", "tz": "Asia/Shanghai" }
    },
    "schedule": {
      "kind": "interval",
      "spec": { "seconds": 3600 }
    },
    "schedule": {
      "kind": "one_shot",
      "spec": { "fire_at": 1712345678 }
    }
  }
  // list
  { "action": "list" }
  // cancel
  { "action": "cancel", "task_id": "abc123" }
  ```
- **D-08:** `task_id` 自动生成（UUID），创建成功后立即返回给模型
- **D-09:** `note` 字段可选（任务触发时发送的消息内容）

### HTTP API
- **D-10:** REST 路径：`GET/POST/DELETE /api/scheduler/tasks`
- **D-11:** Owner 绑定：`owner = conversation_id`（从 `ctx.target` 推导，即 `qq:group:<id>` 或 `qq:user:<id>`），代表 session/channel scope。HTTP API 用 `?owner=` query param（ThreadingHTTPServer 不暴露 headers）。注意：`thread_id` 是 runtime 内部执行线程标识，不参与 scheduler 权限模型。

### Callback 机制
- **D-12:** 使用 `ScheduledMessageDispatcher` 中间层
- **D-13:** 任务创建时 callback 闭包捕获 `conversation_id`（而非 ToolExecutionContext）
- **D-14:** 持久化恢复时 callback=None，通过 `ScheduledMessageDispatcher` 重建 callback
- **D-15:** 参考 `control_plane.py:post_notification()` 模式实现 dispatcher

### Claude's Discretion
- croniter 库（Phase 3a 已定）
- SQLite 表结构细节
- Tool handler error handling 方式
- `list` 返回字段是否包含 `created_at` / `last_fire_at`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Scheduler Infrastructure (Phase 3a)
- `src/acabot/runtime/scheduler/scheduler.py` — RuntimeScheduler 核心实现
- `src/acabot/runtime/scheduler/contracts.py` — ScheduleType 定义（CronSchedule/IntervalSchedule/OneShotSchedule）
- `src/acabot/runtime/scheduler/store.py` — SQLiteScheduledTaskStore 持久化
- `.planning/phases/3a-scheduler/3a-CONTEXT.md` — Phase 3a 完整决策

### Builtin Tool Pattern
- `src/acabot/runtime/builtin_tools/message.py` — BuiltinMessageToolSurface，action-based tool 参考
- `src/acabot/runtime/builtin_tools/__init__.py` — register_core_builtin_tools 入口
- `src/acabot/runtime/tool_broker/broker.py` — ToolBroker 注册/执行
- `src/acabot/agent/tool.py` — ToolSpec 定义

### HTTP API / Control Plane
- `src/acabot/runtime/control/control_plane.py` — `post_notification()` 模式（Callback dispatcher 参考实现）

### Reference Systems
- OpenClaw cron tool（单工具 + action enum，discriminated union schedule）
- AstrBot scheduler plugin（`create_future_task` / `delete_future_task` / `list_future_tasks`）

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `RuntimeScheduler.register/cancel/list_tasks/unregister_by_owner` — 完整任务管理 API
- `post_notification()` in `control_plane.py` — ScheduledMessageDispatcher 可复用此模式
- `Outbox.send_items()` — 消息发送入口
- `BuiltinMessageToolSurface` — action-based tool 注册模式

### Established Patterns
- ToolBroker.register_tool(source, ToolSpec, handler_fn)
- Action-based tool schema: `action` enum 字段 + action-specific 参数
- SQLite persistence with asyncio.Lock
- Discriminated union for schedule types

### Integration Points
- `register_core_builtin_tools()` — 新增 scheduler surface 注册入口
- Control Plane HTTP router — 新增 /api/scheduler/tasks 路由
- Bootstrap — 构造并注入 ScheduledMessageDispatcher

</code_context>

<specifics>
## Specific Ideas

- OpenClaw 风格 action enum：`create` / `list` / `cancel`（非完整的 add/list/remove/update/run/wake）
- AstrBot `note` 字段类比：任务触发时发送给用户的通知内容
- cron timezone 支持：默认 `Asia/Shanghai`

</specifics>

<deferred>
## Deferred Ideas

None — all gray areas resolved.

</deferred>

---

*Phase: 11-scheduler-tool-surface*
*Context gathered: 2026-04-05*
