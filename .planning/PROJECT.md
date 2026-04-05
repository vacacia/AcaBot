# AcaBot v2 — Runtime 基础设施强化

## What This Is

AcaBot 是一个 agentic chatbot runtime，通过 Gateway 接收 IM 平台事件，经过 session-config 路由引擎、LLM agent pipeline、工具调用，最终通过 Gateway 回复。v1.0 完成了 runtime 基础设施的全面补全（插件 Reconciler、统一 message tool、scheduler、LTM safety、structured logging），v1.1 聚焦于生产可用性收尾——修复群聊响应 bug、让模型和插件真正用上 scheduler、优化 WebUI、完成 AstrBot 历史数据迁移。

## Core Value

**让 AcaBot 从"基础设施就绪"进化到"生产环境真正好用"：群聊行为正确、定时任务对模型可见、WebUI 交互流畅、历史记忆可迁移。**

## Current Milestone: v1.1 生产可用性收尾 + LTM 迁移

**Goal:** 修复群聊响应 bug，把 scheduler 能力暴露给模型和插件，优化 WebUI 体验，完成 AstrBot 历史数据迁移到 LTM。

**Target features:**
- 修复群聊"仅回复 @ 和引用"失效问题 (P1)
- 模型可用的定时任务 tool — 创建/查看/取消/绑定会话 (P2)
- 插件侧定时任务使用方式 + 文档示例 (P2)
- WebUI 定时任务管理页面 (P3)
- WebUI 可用性优化 (P3)
- AstrBot 聊天记录提取迁移入口 (P6)
- AstrBot 历史导入 LTM 并验证检索效果 (P7)

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

<!-- v1.1 scope -->
- [ ] 修复群聊"仅回复 @ 和引用"失效问题
- [ ] 模型可用的定时任务 tool/API（创建/查看/取消/绑定会话）
- [ ] 插件侧定时任务使用方式 + 文档示例
- [ ] WebUI 定时任务管理页面
- [ ] WebUI 可用性优化
- [ ] AstrBot 聊天记录提取迁移入口
- [ ] AstrBot 历史导入 LTM 并验证检索效果

### Out of Scope

- Gateway 层新增平台适配器（非本轮目标，当前 NapCat/OneBot v11 够用）
- OAuth/用户认证体系（AcaBot 是单操作者 bot，不是多用户 SaaS）
- 移动端 App（WebUI 已有）
- 商业化/计费功能
- LLM provider 切换优化（litellm 已够用）
- Plugin marketplace（单操作者 bot 不需要第三方分发）
- Distributed scheduler（单进程 runtime，asyncio scheduler 足够）
- OpenTelemetry（单操作者场景 overkill）

## Context

### 技术环境

- Python 3.11+ / asyncio，TypeScript (Vue 3) 前端
- litellm 多 provider LLM 调用，LanceDB 向量存储
- NapCat (OneBot v11 reverse-WebSocket) 作为唯一 Gateway
- Docker Compose 部署（acabot + napcat 双容器）

### 当前状态

- v1.0 全部 47 个需求已验证完成：插件 Reconciler、统一 message tool、scheduler、LTM safety、structured logging 均已落地
- scheduler 基础设施已就绪（cron/interval/one-shot + 持久化 + 生命周期绑定），但仅 runtime 内部可用，模型和插件尚未能直接使用
- 群聊"仅回复 @ 和引用"在生产环境中失效，是当前最高优先级 bug
- WebUI 交互体验有提升空间
- AstrBot 历史聊天记录需要迁移到 AcaBot LTM

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
*Last updated: 2026-04-05 after v1.1 milestone start*
