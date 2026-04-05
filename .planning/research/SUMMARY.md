# Research Summary: AcaBot v1.1

**Milestone:** v1.1 生产可用性收尾 + LTM 迁移
**Synthesized:** 2026-04-05
**Confidence:** HIGH

---

## Executive Summary

**Zero new dependencies.** All v1.1 features build on v1.0 infrastructure. No new Python packages, no new npm packages.

---

## Key Findings

### 1. Group Chat Bug (P1, failing)

**Two independent root causes identified:**

- **Session-config hypothesis** (Features research): `session_runtime._surface_candidates()` 对普通群消息返回 `["message.plain"]`，而 session config 中 `message.plain` 的 admission 默认是 `respond`，导致 bot 回复所有消息。修复：改变 `message.plain` 在 group scene 的 admission 默认值或添加 `when: { scene: group, targets_self: false }` 条件。

- **NapCat gateway hypothesis** (Architecture research): `napcat.py:219-222` 计算 `reply_targets_self` 时依赖 `reply_reference.sender_user_id`，这个值来自 OneBot reply segment 的 `data["user_id"]` 或 `data["qq"]` 字段。如果 NapCat 版本变更导致字段为空或不正确，`reply_targets_self` 永远为 False。

**需要生产环境 debug 日志确认具体是哪一条。**

### 2. Scheduler Tool (P2)

**Existing infrastructure (v1.0):** `RuntimeScheduler` + `SQLiteScheduledTaskStore` + `ToolBroker` registration pattern — all complete.

**What to build:** `BuiltinSchedulerToolSurface` (~120 lines)，工具名 `scheduler`，action 参数：`create | list | cancel`。

**Critical design constraint:** Pitfall #1 — callback 不能捕获 `ToolExecutionContext`，需要 `ScheduledMessageDispatcher` 中间层在触发时重新构造 `RunContext`。

**HTTP API endpoints:**
- `GET /api/scheduler/tasks` — list tasks
- `POST /api/scheduler/tasks` — create task
- `DELETE /api/scheduler/tasks/{task_id}` — cancel
- `PATCH /api/scheduler/tasks/{task_id}/enabled` — pause/resume (需要新增 `set_enabled()` 方法)

### 3. Plugin Scheduler Usage (P2)

**Already exists:** `RuntimeScheduler.unregister_by_owner()` + Reconciler teardown path.

**What to add:** 注入 scheduler 引用到 plugin context + teardown hook wiring。约 20-30 行代码 + 文档示例。

### 4. WebUI Scheduler Page (P3)

**Pattern:** `SessionsView.vue` / `PluginsView.vue` 模式。No new npm packages.

**Backend:** 需要 `set_enabled(task_id, bool)` 方法（scheduler 目前只有 `cancel()` 硬删除）。

### 5. WebUI Usability (P3, failing)

**Specific issues:** "保存要有明显反馈，切换动画优雅" — 需要在 WebUI 代码中定位具体 failing 点。

### 6. AstrBot Migration (P6/P7)

**AstrBot data format:**
- `ConversationV2.content` — OpenAI-format message lists (JSON)
- `PlatformMessageHistory.content` — message chains (SQLite)
- Both stored in SQLite

**Migration path:** 用 `aiosqlite` 读取 AstrBot SQLite → 转换为 `ConversationDelta` → 走现有 `LtmWritePort.ingest_thread_delta()` 管线（sliding window → embed → LanceDB upsert）。

**Key open questions:**
- embedding model 必须与现有 LTM embedding model 一致
- conversation_id 格式映射（AstrBot `qq:group:12345` vs AcaBot 格式）
- group 消息是按 group 还是按 user 聚合？

**推荐：** CLI 工具（一次性批量迁移）+ WebUI 入口（未来增量迁移）

---

## Watch Out For

1. **Scheduler callback 生命周期** — 设计不好会导致消息发到错误会话或在错误时间发
2. **Group chat bug 两个可能根因** — session-config 修复后仍需验证 NapCat 层是否也有问题
3. **AstrBot conversation_id 映射** — 如果 group ID 字段名不匹配，历史消息会写入错误的 conversation

---

## Phase Order Recommendation

**主线 A（独立，可最先执行）：**
1. Phase 1: 群聊 bug 修复 (P1) — 独立于其他所有 feature

**主线 B（scheduler 能力暴露）：**
2. Phase 2: Scheduler tool surface (P2) — 模型可用定时任务
3. Phase 3: Plugin scheduler docs (P2) — 插件侧使用方式
4. Phase 4: WebUI scheduler page (P3) — HTTP API + Vue 组件

**主线 C（独立，可与 B 并行）：**
5. Phase 5: WebUI usability (P3) — 独立优化
6. Phase 6: AstrBot extraction (P6) — 研究 + 工具
7. Phase 7: LTM import + verification (P7) — 依赖 P6

---
*Research synthesized: 2026-04-05*
