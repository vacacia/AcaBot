# Phase 3a/3b/3c: Parallel Phases - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-03
**Phases:** 3a-Scheduler, 3b-LTM Data Safety, 3c-Logging & Observability
**Areas discussed:** Scheduler 持久化策略, Scheduler 回调形态, LTM 备份与降级策略, structlog 集成深度

---

## Scheduler 持久化策略

| Option | Description | Selected |
|--------|-------------|----------|
| SQLite | 复用 runtime_data/acabot.db, 新建 scheduled_tasks 表 | ✓ |
| JSON/YAML 文件 | 类似 PluginSpec 的文件存储, 人类可读 | |
| 纯内存 | 不持久化, 重启后由插件重新注册 | |
| 混合 (config + memory) | 任务定义在配置文件中声明 | |

**User's choice:** SQLite, 复用现有 acabot.db
**Notes:** None

### 同一 DB vs 独立 DB

| Option | Description | Selected |
|--------|-------------|----------|
| 同一个 DB | 复用 runtime_data/acabot.db | ✓ |
| 独立 DB 文件 | runtime_data/scheduler.db | |

**User's choice:** 同一个 DB

### Misfire Recovery Policy

| Option | Description | Selected |
|--------|-------------|----------|
| Skip missed | 跳过错过的触发到下一次 | |
| Fire once on recovery | 重启后补执行一次 | |
| Per-task policy | 任务注册时自己选择 misfire 策略 | ✓ |

**User's choice:** Per-task policy, 先实现 skip 和 fire_once 两种, 默认 skip

### Persist 开关

| Option | Description | Selected |
|--------|-------------|----------|
| persist 开关 | 注册时透明化, persist 只是一个布尔开关 | ✓ |
| 全部持久化 | 所有任务都写 DB | |

**User's choice:** persist 开关

---

## Scheduler 回调形态

| Option | Description | Selected |
|--------|-------------|----------|
| async callable | 任务执行 async callable (coroutine function) | ✓ |
| Action dispatch | 结构化 action (type + payload), 通过 dispatcher 路由 | |
| Event/signal | 发射 asyncio.Event, 注册方自己处理 | |

**User's choice:** async callable

### 错误处理

| Option | Description | Selected |
|--------|-------------|----------|
| Log + continue | 报错时记录日志继续调度 | ✓ |
| Auto-disable after N failures | 连续失败 N 次后禁用 | |
| Fail-fast cancel | 失败立即取消 | |

**User's choice:** Log + continue

### 注册 API 形式

| Option | Description | Selected |
|--------|-------------|----------|
| 统一 register | register(task_id, owner, schedule, callback, ...) | ✓ |
| 分开的 register_xxx | register_cron() / register_interval() / register_oneshot() | |

**User's choice:** 统一 register

---

## LTM 备份与降级策略

### 备份方式

| Option | Description | Selected |
|--------|-------------|----------|
| 目录副本 | 直接复制 lancedb/ 目录 | ✓ |
| API 导出/导入 | 通过 LanceDB API 导出到 Parquet/JSON | |
| Defer backup | 先不做备份 | |

**User's choice:** 目录副本

### 启动校验失败处理

| Option | Description | Selected |
|--------|-------------|----------|
| 禁用 + 警告 | 禁用 LTM, 记录 warning, pipeline 继续 | ✓ |
| 尝试修复后降级 | 自动修复失败再禁用 | |
| 重试模式 | 每次 pipeline 执行时尝试重新初始化 | |

**User's choice:** 禁用 + 警告

### 降级通知

| Option | Description | Selected |
|--------|-------------|----------|
| 日志警告 | 只记录 logger.warning | |
| 日志 + bot 消息 | 通过 bot 给操作者发消息 | |
| 日志 + 状态标志 | 日志 + runtime 状态标志, WebUI 可展示 | ✓ |

**User's choice:** 日志 + 状态标志

---

## structlog 集成深度

### 集成程度

| Option | Description | Selected |
|--------|-------------|----------|
| Wrapper 模式 | structlog wrap stdlib, contextvars 传播, 渐进迁移 | ✓ |
| 增强现有 (无新依赖) | 直接增强 InMemoryLogBuffer, 用 LogRecord.extra | |
| 全量替换 | 替换所有 logging.getLogger 为 structlog | |

**User's choice:** Wrapper 模式

### Token 用量记录粒度

| Option | Description | Selected |
|--------|-------------|----------|
| Per-run 日志 | 只记录结构化日志, 不持久化 | |
| Per-run + 内存聚合 | 日志 + 内存计数器 | |
| Per-run + 持久化 | 日志 + 写入 SQLite, 支持历史查询 | ✓ |

**User's choice:** Per-run + 持久化

### WebUI 日志查看器改动

| Option | Description | Selected |
|--------|-------------|----------|
| 增强现有 | 在 LogsView.vue 基础上增加结构化字段渲染和筛选 | ✓ |
| 重写日志页面 | 全新组件, 支持 JSON 展开/折叠 | |
| You decide | 只做后端, WebUI 不改 | |

**User's choice:** 增强现有

---

## Claude's Discretion

- croniter 库选择
- SQLite 表结构设计
- Scheduler 内部 loop 实现
- 备份目录命名和保留策略
- 启动校验具体检查项
- structlog processor chain 配置
- Token 持久化存储位置 (扩展 runs 表 or 独立表)
- WebUI 筛选器交互设计

## Deferred Ideas

- SCHED-V2-01: Schedule-triggered agent runs
- SCHED-V2-02: WebUI 定时任务管理页面
- LOG-V2-01..04: 完整 run trace, Memory 追踪, Token budget 可视化, OpenTelemetry
