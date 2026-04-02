# Handoff — 当前进展

最后更新：2026-04-02

## 系统状态

AcaBot 已完成一轮目录重构和文档清理。核心 runtime 主线（Gateway → RuntimeApp → SessionRuntime → ThreadPipeline → Outbox）稳定运行，记忆三层（/self、sticky notes、长期记忆）均已通过 MemoryBroker 统一接入上下文组装。

## 近期关键变更

**目录重构（2026-04-02）**：`runtime-env/` 重命名为 `deploy/`，`plugins/` 统一收入 `extensions/`（含 plugins/、skills/、subagents/），运行时目录统一为 `runtime_config/`（操作者真源）和 `runtime_data/`（运行时事实）。inline 配置模式已移除，filesystem-only。详见 `docs/28-directory-restructure.md`。

**文档清理（2026-04-02）**：删除 14 个冗余文档（17-* 系列重复、tmp-*、openclaw-*、sandbox-notes、旧 known-issues、rule-design），记忆子系统文档合并到 `docs/05-memory-and-context.md`，配置文档（09）更新了路径引用。

**Session-Owned Agent（2026-03-30）**：每个 session 独占一个 agent（`sessions/qq/group/<id>/agent.yaml`），不跨 session 共享。Agent 描述 prompt_ref、enabled_tools、skills 和 computer_policy。

**Subagent 文件系统 Catalog（2026-03-29）**：subagent 定义真源从 profile/plugin 收成文件系统 catalog，每个 subagent 只认 `SUBAGENT.md`。Session 只负责 `visible_subagents`，child run 默认不递归、不支持 approval resume。

**长期记忆（2026-03-27 ~ 2026-04-01）**：Core SimpleMem + LanceDB 实现已跑通。写入线 fact-driven（mark_dirty → 增量事实窗口 → 滑窗提取），检索线 run-driven（三路召回 → reranking → XML 注入）。

## 文档结构

核心架构文档是编号系列 `docs/00-14`，覆盖系统地图、runtime 主线、数据契约、路由、记忆、网关、WebUI、配置、部署等。子系统详细文档在 `docs/wiki/`（computer、sticky-notes、long-term-memory、skill、subagent）。LTM 实现设计在 `docs/LTM/`。历史计划和设计 spec 在 `docs/superpowers/`。

## 已知问题

WebUI 配置页面不完整。Docker 镜像缺少基础环境（字体、chrome 等）。Bot 可用工具偏少。日志信息不够全面。LTM 数据库缺少安全防护。
