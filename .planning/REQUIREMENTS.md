# Requirements: AcaBot v2 Runtime Infrastructure

**Defined:** 2026-04-02
**Core Value:** 让 AcaBot 的 runtime 基础设施从 MVP 水平提升到正式可用水平：插件可管理、消息能力完整、定时任务可用、运行状态可观测。

## v1 Requirements

### Reference Backend Removal

- [x] **REF-01**: Reference Backend 子系统完全删除，无残留导入
- [x] **REF-02**: BackendBridgeToolPlugin 与 Reference Backend 解耦，过渡期可用
- [x] **REF-03**: config.yaml 中 reference 相关配置项清理或标记废弃

### Plugin Management

- [x] **PLUG-01**: 插件身份从 import path 迁移到 plugin_id
- [x] **PLUG-02**: PluginPackage 从 extensions/plugins/ 扫描 plugin.yaml manifest
- [x] **PLUG-03**: PluginSpec（启用/禁用 + 配置覆盖）持久化到 runtime_config/plugins/
- [x] **PLUG-04**: PluginStatus（phase/error/tools/hooks）持久化到 runtime_data/plugins/
- [x] **PLUG-05**: PluginReconciler 实现 desired-state 收敛（reconcile_all + reconcile_one）
- [x] **PLUG-06**: PluginRuntimeHost 执行 load/unload/teardown/run_hooks
- [x] **PLUG-07**: 单插件异常不影响 runtime（错误隔离）
- [x] **PLUG-08**: 旧 plugin_manager.py（972 行）完全替换删除
- [x] **PLUG-09**: 旧插件（OpsControl/NapCatTools/ReferenceTools）删除
- [x] **PLUG-10**: REST API 5 个新端点替代旧 4 个端点
- [x] **PLUG-11**: WebUI 插件管理页（列表、状态徽章、enable/disable、schema 驱动配置表单）
- [x] **PLUG-12**: Bootstrap 集成（构造 catalog/spec_store/status_store/host/reconciler）
- [x] **PLUG-13**: Pipeline 集成（plugin_manager.run_hooks → host.run_hooks）

### Scheduler

- [ ] **SCHED-01**: 支持 cron 表达式定时任务（使用 croniter 解析）
- [ ] **SCHED-02**: 支持 interval（固定间隔）定时任务
- [ ] **SCHED-03**: 支持 one-shot（一次性延迟）任务
- [ ] **SCHED-04**: 任务持久化，runtime 重启后恢复
- [ ] **SCHED-05**: 任务可取消（按 task_id）
- [ ] **SCHED-06**: Graceful shutdown（cancel all + gather，scheduler 最先停）
- [ ] **SCHED-07**: 插件生命周期绑定（unload 时 unregister_by_owner 自动取消）
- [ ] **SCHED-08**: RuntimeApp 生命周期集成（start 后启动，stop 时最先关闭）

### Logging / Observability

- [ ] **LOG-01**: 工具调用日志包含结构化字段（tool_name, duration, result_summary）
- [ ] **LOG-02**: LLM token 用量 per run 记录（input/output/total tokens, model, cost）
- [ ] **LOG-03**: 错误日志自动关联 run context（run_id, thread_id, agent_id）
- [ ] **LOG-04**: WebUI 日志查看器能展示结构化字段（不只是纯文本）
- [ ] **LOG-05**: LTM extraction/query 过程日志可见
- [ ] **LOG-06**: structlog 集成（wrapping stdlib logging，contextvars 传播 run context）

### LTM Data Safety

- [ ] **LTM-01**: asyncio.Lock 写序列化（防止并发写损坏）
- [ ] **LTM-02**: 定期备份能力（通过 scheduler 触发）
- [ ] **LTM-03**: 启动时完整性检查（检测损坏表/缺失 manifest）
- [ ] **LTM-04**: LTM 失败时优雅降级（不阻断 pipeline，记录错误继续）

### Unified Message Tool

- [x] **MSG-01**: 文本回复（基础 send text，保持现有行为）
- [x] **MSG-02**: 引用回复（reply_to 指定被引用消息）
- [x] **MSG-03**: @mention（指定用户 ID）
- [x] **MSG-04**: Emoji reaction（对消息添加 reaction）
- [x] **MSG-05**: 撤回消息（recall 指定消息）
- [x] **MSG-06**: 媒体/附件发送（图片、文件路径）
- [x] **MSG-07**: 工具层只表达意图，映射到 Action → Outbox → Gateway
- [ ] **MSG-08**: 文转图渲染（Playwright render_markdown_to_image）
- [x] **MSG-09**: 跨会话消息发送（target 参数指定目标会话）
- [x] **MSG-10**: 具体工具 schema / 字段设计在 discuss-phase 时敲定

### Playwright Integration

- [x] **PW-01**: render_markdown_to_image() 工具函数在 Outbox 层
- [x] **PW-02**: Singleton browser 实例管理（启动时创建，关闭时销毁）
- [x] **PW-03**: markdown-it-py → HTML → Playwright screenshot 流程

## v2 Requirements

### Plugin System

- **PLUG-V2-01**: 插件依赖声明与拓扑排序加载
- **PLUG-V2-02**: 插件资源用量追踪
- **PLUG-V2-03**: 插件 marketplace

### Scheduler

- **SCHED-V2-01**: Schedule-triggered agent runs（定时触发完整 agent pipeline）
- **SCHED-V2-02**: WebUI 定时任务管理页面

### Observability

- **LOG-V2-01**: 完整 run trace 视图（WebUI）
- **LOG-V2-02**: Memory 操作追踪
- **LOG-V2-03**: Token budget 可视化
- **LOG-V2-04**: OpenTelemetry 导出

### Message Tool

- **MSG-V2-01**: 合并转发消息
- **MSG-V2-02**: 富文本编辑
- **MSG-V2-03**: Interactive components（按钮、卡片）

## Out of Scope

| Feature | Reason |
|---------|--------|
| Plugin sandboxing | Python 无法真正隔离插件进程，单操作者场景不需要 |
| Plugin marketplace | 单操作者 bot，不需要第三方分发 |
| Distributed scheduler (Celery/Redis) | 单进程 runtime，asyncio scheduler 足够 |
| Sub-second scheduler precision | chatbot 场景不需要高精度定时 |
| Full prompt logging by default | 隐私风险 + 存储成本 |
| OpenTelemetry (v1) | 单操作者场景 overkill，v2 考虑 |
| Forward/合并转发 (v1) | OneBot v11 的合并转发 API 复杂，v1 先不做 |
| Voice/TTS | 超出当前基础设施强化范围 |
| Multiple gateway support | 当前只有 NapCat，不需要 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| REF-01 | 5 | Validated |
| REF-02 | 5 | Validated |
| REF-03 | 5 | Validated |
| PLUG-01 | 5 | Validated |
| PLUG-02 | 5 | Validated |
| PLUG-03 | 5 | Validated |
| PLUG-04 | 5 | Validated |
| PLUG-05 | 5 | Validated |
| PLUG-06 | 5 | Validated |
| PLUG-07 | 5 | Validated |
| PLUG-08 | 5 | Validated |
| PLUG-09 | 5 | Validated |
| PLUG-10 | 5 | Validated |
| PLUG-11 | 5 | Validated |
| PLUG-12 | 5 | Validated |
| PLUG-13 | 5 | Validated |
| SCHED-01 | 6 | Pending |
| SCHED-02 | 6 | Pending |
| SCHED-03 | 6 | Pending |
| SCHED-04 | 6 | Pending |
| SCHED-05 | 6 | Pending |
| SCHED-06 | 6 | Pending |
| SCHED-07 | 6 | Pending |
| SCHED-08 | 6 | Pending |
| LOG-01 | 6 | Pending |
| LOG-02 | 6 | Pending |
| LOG-03 | 6 | Pending |
| LOG-04 | 6 | Pending |
| LOG-05 | 6 | Pending |
| LOG-06 | 6 | Pending |
| LTM-01 | 6 | Pending |
| LTM-02 | 6 | Pending |
| LTM-03 | 6 | Pending |
| LTM-04 | 6 | Pending |
| MSG-01 | 4 | Validated |
| MSG-02 | 4 | Validated |
| MSG-03 | 4 | Validated |
| MSG-04 | 4 | Validated |
| MSG-05 | 4 | Validated |
| MSG-06 | 4 | Validated |
| MSG-07 | 4 | Validated |
| MSG-08 | 7 | Pending |
| MSG-09 | 4 | Validated |
| MSG-10 | 4 | Validated |
| PW-01 | 4 | Validated |
| PW-02 | 4 | Validated |
| PW-03 | 4 | Validated |

**Coverage:**
- v1 requirements: 47 total
- Validated: 28
- Pending gap closure: 19
- Mapped to phases: 47
- Unmapped: 0 ✅

---
*Requirements defined: 2026-04-02*
*Last updated: 2026-04-04 after Phase 05 foundation artifact backfill close-out*
