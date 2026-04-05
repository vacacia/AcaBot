# Architecture Research

**Domain:** AcaBot v1.1 生产可用性收尾 -- scheduler tool 暴露、群聊 bug 修复、WebUI 优化、LTM 迁移
**Researched:** 2026-04-05
**Confidence:** HIGH

## 现有架构总览

```
┌────────────────────────────────────────────────────────────────────────┐
│                        NapCat Gateway (OneBot v11)                      │
│  napcat.py: WS server → translate(raw) → StandardEvent                │
├────────────────────────────────────────────────────────────────────────┤
│                     RuntimeApp.handle_event(event)                      │
│                              │                                          │
│                              v                                          │
│                     RuntimeRouter.route(event)                          │
│              SessionRuntime: facts → session → surface →               │
│              routing → admission → context → persistence →             │
│              extraction → computer → RouteDecision                     │
├────────────────────────────────────────────────────────────────────────┤
│                     ThreadPipeline.run(ctx)                             │
│                              │                                          │
│       ┌──────────────────────┼──────────────────────┐                  │
│       v                      v                      v                  │
│  MemoryBroker          AgentRuntime           PluginRuntimeHost         │
│  (working/sticky/     (LLM call via           (hook dispatch,         │
│   LTM retrieval)      litellm + tools)         tool registration)     │
│       │                      │                                          │
│       └──────────┬───────────┘                                          │
│                  v                                                      │
│            ToolBroker.execute()                                          │
│  ┌──────────┬──────────┬──────────┬──────────┐                         │
│  │ message  │ computer │ skills   │ plugins  │ ...                     │
│  └──────────┴──────────┴──────────┴──────────┘                         │
│                  │                                                      │
│                  v                                                      │
│             Outbox → Gateway.send(Action)                               │
├────────────────────────────────────────────────────────────────────────┤
│                     Infrastructure Layer                                │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐               │
│  │ RuntimeScheduler│ │ LTM Ingestor  │ │ Computer       │               │
│  │ (heap+asyncio) │ │ (windowed)    │ │ (Host/Docker)  │               │
│  └───────────────┘  └───────────────┘  └───────────────┘               │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐               │
│  │ SQLite Stores │ │ LanceDB LTM    │ │ PluginReconciler│              │
│  │ (runs/events/ │ │ (vectors+meta) │ │ (Package/Spec/  │              │
│  │  messages/sched)│                 │ │  Status)        │              │
│  └───────────────┘  └───────────────┘  └───────────────┘               │
├────────────────────────────────────────────────────────────────────────┤
│                     Control Plane + WebUI                               │
│  RuntimeControlPlane → RuntimeHttpApiServer (ThreadingHTTPServer)       │
│                              │                                          │
│                              v                                          │
│              Vue 3 SPA (static files, port 8765)                        │
└────────────────────────────────────────────────────────────────────────┘
```

## 新功能的架构集成分析

### 1. 群聊 "仅回复 @ 和引用" Bug 修复

**现状分析:**

消息路由链路: `napcat.py._translate_message()` → `StandardEvent` → `SessionRuntime.build_facts()` → `resolve_admission()`

关键字段:
- `mentions_self`: 在 `napcat.py:218` 计算, `self_user_id in mentioned_user_ids`
- `reply_targets_self`: 在 `napcat.py:219-222` 计算, 依赖 `reply_reference.sender_user_id`
- `targets_self`: 在 `napcat.py:251-256` 计算, 是前两者的并集

`session_runtime.py:448-454` 中的 surface 选择逻辑:
```python
if facts.mentions_self:
    return ["message.mention", "message.plain"]
if facts.reply_targets_self:
    return ["message.reply_to_bot", "message.plain"]
```

**可能故障点:**

| 位置 | 可能原因 | 检查方式 |
|------|---------|---------|
| `napcat.py:222` | `reply_reference.sender_user_id` 为空字符串, 导致 `reply_targets_self` 永远为 False | 检查 OneBot reply segment 的 `user_id` 字段是否被 NapCat 正确填充 |
| `napcat.py:217-218` | `self._self_id` 为 None (连接生命周期问题), 导致 `mentions_self` 为 False | 检查 `_self_id` 在消息到达时是否已从 `get_login_info` 获取 |
| `onebot_message.py:29` | reply segment 的 `data["user_id"]` 或 `data["qq"]` 字段名与 NapCat 实际输出不匹配 | 添加日志对比实际 raw_event 中 reply segment 的 data 内容 |
| session 配置 | admission domain 的 `mode` 设置不是 `respond`, 导致即使命中也走 `silent_drop` 或 `ambient` | 检查群聊 session 的 admission surface 配置 |

**涉及组件 (修改范围):**

| 组件 | 修改类型 | 说明 |
|------|---------|------|
| `gateway/napcat.py` | 可能修改 | 修复 `reply_reference.sender_user_id` 提取逻辑或 `_self_id` 获取时序 |
| `gateway/onebot_message.py` | 可能修改 | 确保 reply segment 的 `user_id` 字段提取覆盖 NapCat 变体 |
| `control/session_runtime.py` | 可能无需修改 | surface 选择逻辑本身正确, 问题在上游 |
| `runtime/contracts.py` (EventFacts) | 可能无需修改 | 字段定义本身正确 |

**不需要新组件。** 这是 bug 修复, 不是架构变更。

---

### 2. 模型可用的 Scheduler Tool

**现状分析:**

RuntimeScheduler 已有完整的 cron/interval/one-shot 支持 + SQLite 持久化。当前仅被 `app.py` 用于 LTM 备份任务和插件 unload 清理。核心 API:
- `register(task_id, owner, schedule, callback, persist, metadata)`
- `cancel(task_id)`
- `unregister_by_owner(owner)`
- `list_tasks()` → `list[ScheduledTaskInfo]`

ToolBroker 的工具注册机制:
- `register_tool(spec: ToolSpec, handler: ToolHandler, source, metadata)`
- 工具对模型可见性通过 `agent.enabled_tools` 控制
- 执行时通过 `ToolExecutionContext` 传递 run context

**新组件需求:**

```
+--------------------------------------------------------------+
| 新组件: builtin_tools/scheduler.py                            |
|                                                              |
| 功能:                                                         |
|   - register_schedule: 模型创建定时任务                       |
|     参数: schedule_type, schedule_spec, message,              |
|           conversation_id (可选, 绑定会话)                    |
|   - list_schedules: 模型查看自己的定时任务                     |
|   - cancel_schedule: 模型取消定时任务                         |
|                                                              |
| 注册到: ToolBroker (source="builtin:scheduler")               |
| 回调: 触发时通过 Outbox 发送通知到绑定会话                     |
|                                                              |
| 关键设计决策:                                                  |
|   - owner 字段使用 "tool:scheduler:{run_id}" 或               |
|     "tool:scheduler:{conversation_id}" 来追踪来源             |
|   - 触发回调需要 conversation_id 来路由消息                   |
|   - metadata 存储 conversation_id + 原始 message 内容        |
+--------------------------------------------------------------+
```

**数据流 (创建定时任务):**

```
模型调用 scheduler tool (register_schedule)
    |
    v
ToolBroker.execute() -> scheduler tool handler
    |
    +-- 从 ToolExecutionContext 提取:
    |   - conversation_id (从 metadata.channel_scope)
    |   - agent_id (用于回复时选择 agent)
    |   - owner 标识
    |
    +-- 验证 schedule 参数合法性
    |
    +-- RuntimeScheduler.register(
    |       task_id = "sched:{uuid}",
    |       owner = "tool:scheduler:{conversation_id}",
    |       schedule = 解析后的 ScheduleType,
    |       callback = 异步发送消息的闭包,
    |       persist = True,
    |       metadata = { conversation_id, message, agent_id }
    |   )
    |
    +-- 返回 ToolResult(task_id, schedule 信息)
```

**数据流 (定时任务触发):**

```
RuntimeScheduler._worker_loop() 触发
    |
    v
callback() 执行
    |
    +-- 从闭包/metadata 获取 conversation_id, message
    |
    +-- 构建 OutboxItem (action_type=SEND_MESSAGE_INTENT)
    |   - 需要从 conversation_id 推导 thread_id
    |   - 需要获取 session 配置来确定 agent
    |
    +-- Outbox.send_items() -> Gateway.send()
```

**核心挑战:**

1. **回调中的 session 路由**: 定时任务触发时没有 StandardEvent, 需要从 conversation_id 推导出 session 配置和 agent_id。复用 `control_plane.post_notification()` 的模式。
2. **持久化任务恢复**: RuntimeScheduler 恢复持久化任务时 callback 为 None, 需要通过 owner 前缀 + metadata 重建回调。
3. **会话绑定**: 一个定时任务绑定到特定 conversation_id, 任务触发时回复到该会话。

**涉及组件:**

| 组件 | 修改类型 | 说明 |
|------|---------|------|
| `builtin_tools/scheduler.py` | **新建** | scheduler tool 实现, 注册到 ToolBroker |
| `runtime/app.py` | 修改 | 启动时注册 scheduler tool, 恢复持久化任务时重建回调 |
| `scheduler/scheduler.py` | 可能修改 | `register()` 的 callback 需要支持闭包捕获, 或在 `_recover_persisted_tasks` 时提供回调重建接口 |
| agent 配置 | 修改 | agent 的 enabled_tools 需要包含 scheduler 工具名 |

---

### 3. 插件侧 Scheduler 使用

**现状分析:**

`PluginRuntimeHost.__init__` 已接收 `scheduler: RuntimeScheduler | None`。插件通过 `RuntimePluginContext` 获得 runtime 服务。

**不需要新组件。** 需要在 `RuntimePluginContext` 上暴露 scheduler API, 并提供文档/示例。

**涉及组件:**

| 组件 | 修改类型 | 说明 |
|------|---------|------|
| `plugin_protocol.py` | 修改 | RuntimePluginContext 添加 scheduler 属性或方法 |
| `plugin_runtime_host.py` | 修改 | 在构建 plugin context 时注入 scheduler |
| 文档/示例 | **新建** | 插件使用 scheduler 的文档和示例代码 |

---

### 4. WebUI Scheduler 管理页面

**现状分析:**

WebUI 是 Vue 3 SPA, 通过 `RuntimeHttpApiServer` 的 REST API 与后端通信。当前 sidebar 导航: 首页 / 记忆 / 模型供应商 / 模型 / 提示词 / 插件 / 技能 / 子代理 / 会话 / 系统 / 日志。

**新组件需求:**

```
+--------------------------------------------------------------+
| 后端: RuntimeControlPlane 新方法                              |
|                                                              |
|   list_scheduled_tasks() -> list[ScheduledTaskInfo]          |
|   cancel_scheduled_task(task_id) -> bool                     |
|   trigger_scheduled_task(task_id) -> dict (立即触发)          |
|                                                              |
| 后端: http_api.py 新路由                                     |
|   GET  /api/scheduler/tasks                                  |
|   POST /api/scheduler/tasks/{task_id}/cancel                 |
|   POST /api/scheduler/tasks/{task_id}/trigger                |
|                                                              |
| 前端: webui/src/views/SchedulerView.vue                      |
|   - 表格展示所有定时任务                                      |
|   - 列: task_id, owner, schedule, next_fire_at, enabled     |
|   - 操作: 取消、立即触发                                      |
|   - 自动刷新 (轮询 next_fire_at)                             |
|                                                              |
| 前端: webui/src/components/AppSidebar.vue                    |
|   - 添加 /config/scheduler 路由链接                          |
+--------------------------------------------------------------+
```

**涉及组件:**

| 组件 | 修改类型 | 说明 |
|------|---------|------|
| `control/control_plane.py` | 修改 | 添加 scheduler 相关方法 |
| `control/http_api.py` | 修改 | 添加 scheduler API 路由 |
| `webui/src/views/SchedulerView.vue` | **新建** | 定时任务管理页面 |
| `webui/src/components/AppSidebar.vue` | 修改 | 添加导航项 |
| `webui/src/router/index.ts` | 修改 | 添加路由 |

---

### 5. WebUI 可用性优化

这是渐进改进, 不涉及新架构组件。具体优化点需要在实现阶段确定, 但架构层面需要确认:

- SWR 缓存已在 v1.0 落地 (用于 plugin scanning, log retrieval, session data loading)
- HTTP API 响应格式统一为 `{ ok: bool, data: ... }`
- 静态文件从 `src/acabot/webui/` 提供

**无需新组件。** 属于现有组件的渐进优化。

---

### 6-7. AstrBot 历史迁移到 LTM

**现状分析:**

LTM 写入管线:
```
OutboxProjection -> LongTermMemoryIngestor.mark_dirty(thread_id)
    -> worker_loop -> ConversationFactReader.get_thread_delta()
    -> LtmWritePort.ingest_thread_delta()
    -> 切窗口 -> extract_window (LLM) -> embed (model) -> upsert (LanceDB)
```

写入依赖:
- `ConversationFactReader`: 从 `ChannelEventStore` + `MessageStore` 读增量事实
- `LtmWindowExtractor`: LLM 调用提取结构化记忆
- `LtmEntryEmbeddingClient`: 生成 embedding 向量
- `LongTermMemoryWriteStore`: LanceDB 读写

LTM 对象结构 (`MemoryEntry`):
- `entry_id`, `conversation_id`, `topic`, `lossless_restatement`
- `keywords`, `persons`, `entities`, `location`, `time_point`
- `provenance.fact_ids`

**新组件需求:**

```
+--------------------------------------------------------------+
| 新组件: migrations/astrbot_history_import.py                  |
|                                                              |
| 功能:                                                        |
|   1. 解析 AstrBot 历史数据 (JSON/SQLite 格式)                |
|   2. 转换为 ConversationFact 格式                            |
|   3. 通过 LongTermMemoryWritePort 写入 LTM                  |
|   4. 验证检索效果 (keyword/structured search)                |
|                                                              |
| 触发方式:                                                     |
|   - WebUI 按钮触发 (HTTP API)                                |
|   - 或 CLI 命令                                              |
|                                                              |
| 关键设计:                                                    |
|   - 不走 LongTermMemoryIngestor (那是实时管线)               |
|   - 直接调 LtmWritePort.ingest_thread_delta()               |
|   - 或直接构造 MemoryEntry + embedding 写入 LanceDB          |
|   - conversation_id 映射: AstrBot 群号/用户号 -> AcaBot      |
|     的 "qq:group:{group_id}" / "qq:user:{user_id}" 格式     |
+--------------------------------------------------------------+
```

**数据流 (迁移):**

```
AstrBot 历史数据文件 (JSON/SQLite)
    |
    v
解析器: 提取 (timestamp, sender, content, conversation_id)
    |
    +-- conversation_id 映射:
    |   AstrBot "group:{gid}" -> "qq:group:{gid}"
    |   AstrBot "private:{uid}" -> "qq:user:{uid}"
    |
    +-- 批量转换为 ConversationFact 列表
    |   (需要伪造 source_id, thread_id 等)
    |
    +-- 按 conversation_id 分组
    |
    +-- 对每个 conversation_id:
    |   构建 ConversationDelta(facts=...)
    |   LtmWritePort.ingest_thread_delta()
    |       -> 切窗口 -> LLM 提取 -> embedding -> LanceDB
    |
    +-- 验证: keyword_search / structured_search
    +-- 记录 cursor (可选, 用于断点续传)
```

**涉及组件:**

| 组件 | 修改类型 | 说明 |
|------|---------|------|
| `migrations/astrbot_history_import.py` | **新建** | AstrBot 数据解析和导入逻辑 |
| `control/control_plane.py` | 修改 | 添加 import_astrbot_history() 方法 |
| `control/http_api.py` | 修改 | 添加 POST /api/migrations/astrbot-import 路由 |
| `webui/src/views/LtmConfigView.vue` | 修改 | 添加 "导入 AstrBot 历史" 按钮 + 进度显示 |

---

## 架构模式

### Pattern 1: Tool 注册模式

**What:** 新功能通过 builtin tool 注册到 ToolBroker, 使模型可以直接调用
**When to use:** 需要让 LLM agent 使用某种 runtime 能力时
**Trade-offs:** + 模型自主决定何时使用 / - 模型可能误用, 需要谨慎设计参数

**Example:**
```python
# builtin_tools/scheduler.py
def register_scheduler_tool(tool_broker: ToolBroker, scheduler: RuntimeScheduler) -> None:
    tool_broker.register_tool(
        spec=ToolSpec(
            name="scheduler",
            description="创建和管理定时任务...",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"enum": ["create", "list", "cancel"]},
                    "schedule_type": {"enum": ["cron", "interval", "one_shot"]},
                    # ...
                },
            },
        ),
        handler=SchedulerToolHandler(scheduler),
        source="builtin:scheduler",
    )
```

### Pattern 2: Control Plane 透传模式

**What:** WebUI 需要的操作通过 ControlPlane 方法暴露, HTTP API 薄层转发
**When to use:** WebUI 需要访问 runtime 内部状态时
**Trade-offs:** + 单一入口, 方便审计 / - ControlPlane 会越来越大

**Example:**
```python
# control_plane.py
async def list_scheduled_tasks(self) -> list[dict[str, Any]]:
    if self.app.scheduler is None:
        return []
    return [
        {
            "task_id": t.task_id,
            "owner": t.owner,
            "schedule_type": type(t.schedule).__name__,
            "next_fire_at": t.next_fire_at,
            "enabled": t.enabled,
        }
        for t in self.app.scheduler.list_tasks()
    ]

# http_api.py
if segments == ["scheduler", "tasks"] and method == "GET":
    return self._ok(self._await(self.control_plane.list_scheduled_tasks()))
```

### Pattern 3: 消息注入模式

**What:** 定时任务触发时通过构建 OutboxItem + SEND_MESSAGE_INTENT 发送消息
**When to use:** 需要在非 event 驱动的时机发送消息 (定时触发、通知等)
**Trade-offs:** + 复用现有发送管线 / - 需要 mock 一部分 context

**参考实现:** `control_plane.py:post_notification()` 已经实现了这个模式。scheduler tool 的回调可以复用相同的方式:
1. 从 metadata 取 conversation_id
2. 构建 EventSource + Action(SEND_MESSAGE_INTENT)
3. 通过 Outbox.send_items() 发送

---

## 反模式

### 反模式 1: 直接在 Scheduler 回调中调 Gateway

**What people do:** 在 scheduler callback 中直接调用 `gateway.send()`
**Why it's wrong:** 绕过 Outbox 的统一发送管线, 丢失审计记录、thread 更新、attachment 处理
**Do this instead:** 通过 Outbox.send_items() 走标准发送路径

### 反模式 2: Scheduler Tool 不做权限限制

**What people do:** scheduler tool 暴露所有 schedule 操作给模型
**Why it's wrong:** 模型可能创建大量无意义任务, 或取消插件/system 的关键任务
**Do this instead:** 限制模型只能管理 owner 前缀为 "tool:scheduler:" 的任务, 不能查看/修改插件或 system 的任务

### 反模式 3: 迁移不验证

**What people do:** 导入数据后直接宣布完成
**Why it's wrong:** LLM 提取可能失败, embedding 可能不准确, 检索可能返回垃圾结果
**Do this instead:** 导入后自动运行 search-test 验证检索质量, 提供删除+重导入的能力

---

## 建议构建顺序

基于依赖关系和影响范围:

```
Phase 1: 群聊 Bug 修复 (P1, 最高优先级)
  +-- 不依赖任何其他新功能
  +-- 修改范围小 (Gateway 层事件解析)
  +-- 修复后立即可验证 (生产环境直接测试)
  +-- 需要: 先定位根因 (可能需要添加 debug 日志)

Phase 2: Scheduler Tool 核心 (P2)
  +-- 依赖: RuntimeScheduler 已就绪 (已满足)
  +-- 新建: builtin_tools/scheduler.py
  +-- 修改: app.py (注册 scheduler tool)
  +-- 修改: scheduler.py (恢复持久化任务的回调重建)
  +-- 可独立测试 (通过 synthetic event 调用)

Phase 3: 插件侧 Scheduler (P2, 与 Phase 2 并行可行)
  +-- 依赖: Phase 2 的 scheduler tool 模式确立
  +-- 修改: plugin_protocol.py, plugin_runtime_host.py
  +-- 文档/示例

Phase 4: WebUI Scheduler 管理 (P3)
  +-- 依赖: Phase 2 完成
  +-- 后端: control_plane.py + http_api.py
  +-- 前端: SchedulerView.vue + router + sidebar
  +-- 可与 Phase 5 并行

Phase 5: WebUI 可用性优化 (P3, 与 Phase 4 并行)
  +-- 不依赖其他新功能
  +-- 现有组件的渐进优化
  +-- 需要具体 UX 痛点列表

Phase 6: AstrBot 历史提取 (P6)
  +-- 不依赖 Phase 2-5
  +-- 新建: migrations/astrbot_history_import.py
  +-- 修改: control_plane.py + http_api.py (导入入口)
  +-- 需要先研究 AstrBot 数据格式

Phase 7: LTM 导入验证 (P7)
  +-- 依赖: Phase 6 完成
  +-- 验证检索效果
  +-- 修复数据质量问题
```

**依赖关系图:**

```
Phase 1 (群聊 bug)
  +-- 无依赖, 最高优先级

Phase 2 (scheduler tool) ---- Phase 3 (plugin scheduler)
       |
       v
Phase 4 (WebUI scheduler) ---- Phase 5 (WebUI 优化)

Phase 6 (AstrBot 提取) ---- Phase 7 (LTM 验证)
```

---

## 扩展性考虑

| 关注点 | 当前 (单操作者) | 未来可能的扩展点 |
|--------|----------------|-----------------|
| Scheduler 回调中的 session 路由 | 硬编码从 conversation_id 推导 | 如果支持多平台需要 platform-aware 的路由 |
| LTM 导入的 conversation_id 映射 | AstrBot 到 AcaBot 格式转换 | 如果需要从其他 bot 框架导入, 需要可插拔的映射器 |
| WebUI 定时任务管理 | 只读 + 取消/触发 | 如果需要 WebUI 创建任务, 需要 schedule 参数的 UI 构建 |
| 模型创建的任务数量 | 无硬上限 | 应该加 quota 限制, 防止模型创建过多任务 |

---

## 组件边界总结

### 新建组件

| 组件 | 职责 | 通信方式 |
|------|------|---------|
| `builtin_tools/scheduler.py` | 模型可用的 scheduler tool surface | 注册到 ToolBroker, 调用 RuntimeScheduler |
| `webui/src/views/SchedulerView.vue` | 定时任务管理页面 | 通过 HTTP API 与后端通信 |
| `migrations/astrbot_history_import.py` | AstrBot 数据导入 | 调用 LtmWritePort 写入 |

### 修改组件

| 组件 | 修改内容 | 影响范围 |
|------|---------|---------|
| `gateway/napcat.py` | 修复 reply/mention 检测 | 群聊消息路由 |
| `gateway/onebot_message.py` | 可能修复 reply segment 解析 | 群聊消息解析 |
| `runtime/app.py` | 注册 scheduler tool, 重建持久化回调 | 启动流程 |
| `scheduler/scheduler.py` | 提供回调重建接口 | 持久化恢复 |
| `plugin_protocol.py` | 暴露 scheduler 到 plugin context | 插件 API |
| `plugin_runtime_host.py` | 注入 scheduler | 插件加载 |
| `control/control_plane.py` | scheduler + migration 方法 | WebUI API |
| `control/http_api.py` | scheduler + migration 路由 | WebUI API |
| `webui/src/components/AppSidebar.vue` | 添加 scheduler 导航 | WebUI 导航 |
| `webui/src/router/index.ts` | 添加 scheduler 路由 | WebUI 路由 |
| `webui/src/views/LtmConfigView.vue` | 添加导入按钮 | WebUI LTM 页面 |

### 数据流变更

**现有数据流 (不变):**
```
Gateway -> Router -> Pipeline -> ToolBroker -> Outbox -> Gateway
```

**新增数据流 1: Scheduler Tool**
```
模型调用 -> ToolBroker -> scheduler tool handler -> RuntimeScheduler.register()
                                                          |
                                                    定时触发时
                                                          |
                                                          v
                                          构建通知 -> Outbox -> Gateway
```

**新增数据流 2: AstrBot Migration**
```
WebUI 按钮 -> HTTP API -> ControlPlane -> astrbot_history_import
                                                |
                                                v
                                    LtmWritePort.ingest_thread_delta()
                                                |
                                                v
                                          切窗口 -> LLM 提取 -> embedding -> LanceDB
```

---

## Sources

- 代码审查: `src/acabot/runtime/scheduler/` 完整模块 (contracts.py, scheduler.py, store.py)
- 代码审查: `src/acabot/runtime/tool_broker/broker.py` 完整实现
- 代码审查: `src/acabot/runtime/control/control_plane.py` 完整实现
- 代码审查: `src/acabot/runtime/control/http_api.py` 完整实现
- 代码审查: `src/acabot/gateway/napcat.py` 消息解析逻辑 (_translate_message)
- 代码审查: `src/acabot/gateway/onebot_message.py` 消息段解析
- 代码审查: `src/acabot/runtime/memory/long_term_memory/` LTM 管线 (contracts, storage, write_port)
- 代码审查: `src/acabot/runtime/memory/long_term_ingestor.py` LTM 编排器
- 代码审查: `src/acabot/runtime/plugin_runtime_host.py` 插件宿主
- 代码审查: `src/acabot/runtime/router.py` + `control/session_runtime.py` 路由逻辑
- 代码审查: `src/acabot/types/event.py` StandardEvent 定义
- 代码审查: `webui/src/components/AppSidebar.vue` 导航结构
- 代码审查: `.planning/PROJECT.md` 项目上下文

---
*Architecture research for: AcaBot v1.1 生产可用性收尾*
*Researched: 2026-04-05*
