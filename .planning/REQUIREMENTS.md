# Requirements: AcaBot v1.1

**Defined:** 2026-04-05
**Core Value:** 让 AcaBot 从"基础设施就绪"进化到"生产环境真正好用"：群聊行为正确、定时任务对模型可见、WebUI 交互流畅。

## v1 Requirements

### Group Chat Response Filtering

- [x] **GROUP-01**: 修复群聊消息响应行为 — 按照 session 配置的消息响应矩阵（admission domain）对不同消息类型做不同响应（respond / silent_drop / record_only），而非全部回复或全部忽略

### Scheduler Tool (LLM-facing)

- [ ] **SCHED-01**: 模型可以通过 `scheduler` tool 创建定时任务（cron / interval / one-shot），任务绑定到当前会话
- [ ] **SCHED-02**: 模型可以通过 `scheduler` tool 查看已创建的定时任务列表（按 owner 过滤）
- [ ] **SCHED-03**: 模型可以通过 `scheduler` tool 取消指定 task_id 的定时任务

### Plugin Scheduler

- [ ] **PLUG-01**: 插件可以通过 plugin context 使用 scheduler：注册任务、恢复持久化任务、在 unload 时自动清理（unregister_by_owner）；附带文档示例

### WebUI Scheduler

- [ ] **WEBUI-01**: WebUI 定时任务管理页面：展示任务列表、状态、下次触发时间、owner、schedule 类型
- [ ] **WEBUI-02**: WebUI 支持创建/启停/删除定时任务，操作后页面状态与后端实际任务一致
- [ ] **WEBUI-03**: 保存操作有明显视觉反馈（成功/失败提示）

### WebUI Usability

- [ ] **WEBUI-04**: 切换动画流畅优雅

### AstrBot Migration (deferred to future milestone)

- [ ] **ASTR-01**: 提供一次性 CLI 迁移工具，能从 AstrBot SQLite 数据库提取聊天记录，转换为 AcaBot 可消费的 ConversationDelta 中间格式
- [ ] **ASTR-02**: AstrBot 历史消息能正确导入 AcaBot LTM（走 LtmWritePort.ingest_thread_delta() 管线），抽查历史事实能在 LTM 查询中命中

## Out of Scope

| Feature | Reason |
|---------|--------|
| Scheduler tool 支持 edit 已有任务 | Edit = cancel + recreate，在 LLM prompt 中告知模型即可，无需单独实现 |
| AstrBot 迁移 WebUI 入口 | 一次性迁移，CLI 足够 |
| 编辑已创建定时任务的 schedule | create/cancel 覆盖，edit 场景 = cancel + recreate |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| GROUP-01 | 10 | Complete |
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

**Coverage:**
- v1 requirements: 11 total
- Mapped to phases: 9 (ASTR-01/02 deferred)
- Unmapped: 0

---
*Requirements defined: 2026-04-05*
*Last updated: 2026-04-05 after roadmap adjustment*
