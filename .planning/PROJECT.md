# AcaBot v2 — Runtime 基础设施强化

## What This Is

AcaBot 是一个 agentic chatbot runtime，通过 Gateway 接收 IM 平台事件，经过 session-config 路由引擎、LLM agent pipeline、工具调用，最终通过 Gateway 回复。当前核心 pipeline 已稳定运行，本轮工作聚焦于 runtime 基础设施的补全和重构——插件体系、消息工具、定时任务、日志、数据安全等，让 bot 从"能跑"进化到"好用、可扩展、可观测"。

## Core Value

**让 AcaBot 的 runtime 基础设施从 MVP 水平提升到正式可用水平：插件可管理、消息能力完整、定时任务可用、运行状态可观测。**

## Requirements

### Validated

- ✓ Gateway ↔ LLM pipeline 完整运行 — existing
- ✓ Session-config 路由引擎 — existing
- ✓ ToolBroker 统一工具注册/执行 — existing
- ✓ Memory 三层架构（working/sticky notes/LTM） — existing
- ✓ Computer subsystem（Host/Docker/Remote 后端） — existing
- ✓ WebUI + Control Plane HTTP API — existing
- ✓ Skills / Subagents 子系统 — existing
- ✓ 目录三层分离（extensions/ runtime_config/ runtime_data/） — existing
- ✓ Docker 镜像双版本（Full + Lite） — existing
- ✓ LanceDB-backed LTM runtime — existing

### Active

- [x] 定时任务基础设施（统一 scheduler，插件 + bot 核心均可用）
- [x] 日志内容优化（需调研后确定具体范围）
- [x] LTM 数据库安全性（数据完整性保障）
- [x] 插件管控重构（docs/29-plugin-control-plane.md 完整方案）
- [x] 统一 message 工具（统一 `message` surface + `SEND_MESSAGE_INTENT` + cross-session contract）
- [x] Playwright + Chromium 集成（镜像依赖 + Outbox render service + runtime artifact path）
- [x] 删除 Reference Backend（设计不合理，不再需要）
- [ ] milestone 收尾（真人 QQ 验收、retrospective、milestone audit、archive）

### Out of Scope

- Gateway 层新增平台适配器（非本轮目标，当前 NapCat/OneBot v11 够用）
- OAuth/用户认证体系（AcaBot 是单操作者 bot，不是多用户 SaaS）
- 移动端 App（WebUI 已有）
- 商业化/计费功能
- LLM provider 切换优化（litellm 已够用）

## Context

### 技术环境

- Python 3.11+ / asyncio，TypeScript (Vue 3) 前端
- litellm 多 provider LLM 调用，LanceDB 向量存储
- NapCat (OneBot v11 reverse-WebSocket) 作为唯一 Gateway
- Docker Compose 部署（acabot + napcat 双容器）

### 当前状态

- pipeline 核心稳定，Reference Backend 已删除，旧 `plugin_manager.py` 已被 Reconciler 体系替换
- 旧内建插件（OpsControl/NapCatTools/ReferenceTools）已删除，`extensions/plugins/` 目录已由新 plugin package / spec / status 体系接管
- bot 已具备统一 `message` tool、引用 / @ / reaction / recall / 附件 / 文转图 / 跨会话发送能力
- Outbox 已把 facts 摘要和 working memory continuity 收口到同一个 projection 逻辑，真实 `message.send` 也能更新 destination thread
- render service / Playwright backend / runtime artifact path / shutdown cleanup 都已接通
- scheduler、structured logging、LTM data safety 都已落地
- 当前主要剩余工作不是主线代码，而是真人 QQ 验收和 milestone 归档文档收尾

### 已有方案文档

- `docs/29-plugin-control-plane.md` — 插件管控重构完整方案（六模块拆分 + Reconciler 架构）
- `.harness/progress.md` — 项目进度和已定方案摘要

## Constraints

- **Tech Stack**: Python 3.11+ / asyncio，不引入新的异步框架
- **Gateway**: 当前只有 NapCat，消息工具设计需平台无关但只需 OneBot v11 实现
- **部署**: Docker Compose，镜像改动需兼容 Full + Lite 双版本
- **兼容性**: 插件重构需保证 BackendBridgeToolPlugin 过渡期可用
- **单操作者**: AcaBot 面向单个操作者，不需要多租户隔离

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 插件体系用 Reconciler 模式（Package + Spec + Status） | 分离代码（Package）、意图（Spec）、观察（Status），WebUI 可管理 | — Landed |
| 插件身份从 import path 改为 plugin_id | class 重构不会破坏配置和 UI | — Landed |
| 旧插件直接删除不迁移 | 代码量小，新体系重写更干净 | — Landed |
| Playwright 作为镜像依赖而非 plugin/runtime | bot 通过 bash 直接用，Outbox 层提供 render_markdown_to_image() | — Landed |
| 统一 message 工具保持单一 surface，但只把 `send` 抬为高层 `SEND_MESSAGE_INTENT` | 对模型简单，对 runtime 内部仍保留合理分层 | — Landed |
| facts / working memory continuity 统一由 Outbox projection 生成 | 避免 tool、pipeline、gateway 各自维护一套 rich send 摘要规则 | — Landed |
| 定时任务做成正式基础设施 | 插件和 bot 核心都需要，不能只是 ad-hoc asyncio.sleep | — Landed |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-04 after Phase 04 re-verification and doc sync*
