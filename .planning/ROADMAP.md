# Roadmap: AcaBot v1.1 生产可用性收尾

**Created:** 2026-04-05
**Granularity:** standard (5 phases)
**Parallelization:** enabled (Phase 10 / 11+12 / 13+14 are three independent workstreams)

## Phase Overview

```
Phase 10: Group Chat Bug Fix           [1 req]   ──────────────────────────►
Phase 11: Scheduler Tool Surface       [3 reqs]  ──►
Phase 12: Plugin Scheduler             [1 req]   ──┐
Phase 13: WebUI Scheduler Page         [3 reqs]  ──┼─► (parallel with Phase 14)
Phase 14: WebUI Usability              [1 req]   ──┘
                                              ─────────
                                               9 total (ASTR-01/02 deferred)
```

---

## Phases

- [x] **Phase 10: Group Chat Bug Fix** - 修复群聊"仅回复 @ 和引用"失效问题 (completed 2026-04-05)
- [ ] **Phase 11: Scheduler Tool Surface** - 模型通过 builtin tool 使用 scheduler（创建/查看/取消）
- [ ] **Phase 12: Plugin Scheduler** - 插件通过 plugin context 使用 scheduler（注册/恢复/清理）+ 文档示例
- [ ] **Phase 13: WebUI Scheduler Page** - 定时任务管理页面（列表/状态/时间/owner）+ 创建/启停/删除
- [ ] **Phase 14: WebUI Usability** - 保存操作视觉反馈 + 切换动画

---

## Phase Details

### Phase 10: Group Chat Bug Fix

**Goal:** 群聊消息响应行为符合 session config 中 admission domain 配置——仅当消息满足 respond 条件时才回复，否则 silent_drop 或 record_only。

**Depends on:** None (独立 P1 bug fix)
**Requirements:** GROUP-01

**Success Criteria** (what must be TRUE):
1. 在 group scene 配置 `respond` 为 admission 时，bot 仅回复 @ 或引用消息
2. 在 group scene 配置 `silent_drop` 为 admission 时，bot 对普通群消息完全不回复（无任何 gateway 发送）
3. 在 group scene 配置 `record_only` 为 admission 时，bot 不回复但消息仍进入 pipeline 处理
4. 修复后 bot 在 group 中不再回复所有消息（生产环境验证或测试场景验证）

**Plans:** 1/1 plans complete

---

### Phase 11: Scheduler Tool Surface

**Goal:** 模型可以通过 `scheduler` builtin tool 自主管理定时任务（创建 cron/interval/one-shot 任务、查看列表、取消任务），任务绑定到触发会话。

**Depends on:** None (独立于 group bug fix)
**Requirements:** SCHED-01, SCHED-02, SCHED-03

**Success Criteria** (what must be TRUE):
1. 模型调用 `scheduler` tool 并传入 `create` action + cron/interval/one-shot 参数时，任务被创建并持久化到 SQLite
2. 模型调用 `scheduler` tool 并传入 `list` action 时，返回当前 owner（触发会话）的任务列表，包含状态/下次触发时间
3. 模型调用 `scheduler` tool 并传入 `cancel` action + task_id 时，任务被取消且不再触发
4. 模型创建的任务在 runtime 重启后恢复执行（持久化验证）
5. HTTP API 同步实现：GET/POST/DELETE /api/scheduler/tasks，供 Phase 13 WebUI 使用

**Plans:** TBD
**UI hint:** yes

---

### Phase 12: Plugin Scheduler

**Goal:** 插件可以通过 plugin context 注入的 scheduler ref 使用定时任务能力（注册/恢复/自动清理），附带文档示例。

**Depends on:** Phase 11 (scheduler tool surface 完成，RuntimeScheduler 能力已暴露)
**Requirements:** PLUG-01

**Success Criteria** (what must be TRUE):
1. 插件通过 `plugin context.scheduler` 可以调用 `register()` / `unregister_by_owner()` / `list_by_owner()`
2. 插件 unload 时自动触发 `scheduler.unregister_by_owner(plugin_id)`（teardown hook wiring）
3. 插件在 runtime 重启后可以通过 `scheduler.list_by_owner()` 恢复自己注册的任务
4. 文档示例（`docs/` 或 `extensions/plugins/` 下的示例插件）演示完整使用流程

**Plans:** TBD

---

### Phase 13: WebUI Scheduler Page

**Goal:** WebUI 提供完整的定时任务管理界面，页面状态与后端实际任务一致，操作结果有明确反馈。

**Depends on:** Phase 11 (HTTP API 就绪)
**Requirements:** WEBUI-01, WEBUI-02, WEBUI-03

**Success Criteria** (what must be TRUE):
1. WebUI 定时任务管理页面展示任务列表：task_id、schedule 类型、下次触发时间、owner、状态（enabled/disabled）
2. WebUI 支持创建定时任务（填写 schedule 参数、绑定 owner）
3. WebUI 支持启停/删除操作，操作后页面任务状态与后端实际一致（刷新后不丢失）
4. 保存/创建操作后有明显视觉反馈（成功提示 toast 或状态变更）

**Plans:** TBD
**UI hint:** yes

---

### Phase 14: WebUI Usability

**Goal:** WebUI 交互体验流畅优雅——页面切换动画流畅，操作反馈明确。

**Depends on:** None (独立于 scheduler 主线，可与 Phase 13 并行)
**Requirements:** WEBUI-04

**Success Criteria** (what must be TRUE):
1. 页面切换（导航到不同视图）有流畅的过渡动画，无生硬跳转
2. 列表页/详情页切换动画时间在 200-400ms 范围内，无闪烁
3. 操作反馈（如删除、启停）在视觉上有连贯的动画表现

**Plans:** TBD
**UI hint:** yes

---

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 10. Group Chat Bug Fix | 1/1 | Complete   | 2026-04-05 |
| 11. Scheduler Tool Surface | 0/? | Not started | - |
| 12. Plugin Scheduler | 0/? | Not started | - |
| 13. WebUI Scheduler Page | 0/? | Not started | - |
| 14. WebUI Usability | 0/? | Not started | - |

---

## Coverage Validation

| Requirement | Phase | Status |
|-------------|-------|--------|
| GROUP-01 | 10 | Planned |
| SCHED-01 | 11 | Pending |
| SCHED-02 | 11 | Pending |
| SCHED-03 | 11 | Pending |
| PLUG-01 | 12 | Pending |
| WEBUI-01 | 13 | Pending |
| WEBUI-02 | 13 | Pending |
| WEBUI-03 | 13 | Pending |
| WEBUI-04 | 14 | Pending |
| ASTR-01 | — | Deferred |
| ASTR-02 | — | Deferred |

**Coverage: 9/11 v1 requirements mapped (ASTR-01/02 deferred to future milestone)**
**Deferred: ASTR-01, ASTR-02**

---

## Parallelization Map

```
三条独立主线（全部并行）:
主线 A:  Phase 10 (group chat bug fix) ──────────────────────────►
主线 B:  Phase 11 ──► Phase 12 ──► Phase 13 ───────────────────►
主线 C:  Phase 14 (WebUI usability, 与 Phase 13 并行) ──────────►

AstrBot 迁移: deferred to future milestone (ASTR-01, ASTR-02)
```

---

*Created: 2026-04-05*
