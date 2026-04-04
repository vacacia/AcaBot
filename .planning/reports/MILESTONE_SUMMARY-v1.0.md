# Milestone v1.0 - Project Summary

**Generated:** 2026-04-04
**Purpose:** Team onboarding and project review
**Milestone state:** Current milestone, not archived

> 本文基于 `.planning/PROJECT.md`、`.planning/ROADMAP.md`、`.planning/REQUIREMENTS.md`、`.planning/STATE.md`，以及各 phase 的 `CONTEXT.md`、`RESEARCH.md`、`SUMMARY.md`、`VERIFICATION.md` 生成。
> 其中 Phase 1、2、3a、3b、3c 缺少统一风格的 `SUMMARY.md`，这些 phase 的一行概述和部分状态判断是根据 roadmap、context、research、state 做的归纳，不是假装有原文。

---

## 1. Project Overview

AcaBot 是一个 agentic chatbot runtime。它通过 Gateway 接收 IM 平台事件，走 session-config 路由、LLM agent pipeline、工具调用，最后再通过 Gateway 把结果发回去。

v1.0 这个 milestone 的核心目标很直白：把 AcaBot 的 runtime 基础设施从 "能跑" 往 "正式可用" 推一大截。重点不在新花活，而在把基础设施补齐并做硬化：

- 删除已经设计失败的 Reference Backend，清掉历史包袱
- 把 1 个 900+ 行的插件大泥球拆成可管理的 reconciler 架构
- 补上正式 scheduler
- 给 LTM 加数据安全保护
- 把日志做成结构化、可观察、WebUI 可读
- 让 bot 终于拥有统一 message 工具、跨会话发消息、文转图渲染这些完整消息能力

截至 2026-04-04，这个 milestone 不是归档完成态，而是 "实现已经闭环，真人验收和归档手续还没做完" 的当前态：

- Phase 1、2、3a、3b、3c 都已执行
- Phase 4 的 4 个 plan 都已落地并写了 summary
- Phase 4 的 re-verification 已经把之前的 cross-session continuity gap 关掉
- 当前剩下的主要是真人 QQ 验收和 milestone 纸面台账收口，不是主线代码 blocker

一句话总结：这轮工作已经把 AcaBot 的 runtime 主骨架从 MVP 打到了工程可维护版本，自动化闭环已经通，剩下的是验收和收档。

---

## 2. Architecture & Technical Decisions

- **Phase 1:** Reference Backend 直接硬删除，不做 deprecated，不留兼容层。
  **Why:** 项目明确要求 "当它从来不存在"，先把坏设计彻底清干净，后面重构才不会被旧债拖着走。

- **Phase 2:** 插件系统从 import path 身份切到 `plugin_id`，并拆成 `Package + Spec + Status + Reconciler + RuntimeHost + Protocol`。
  **Why:** 把代码发现、用户意图、运行状态、实际收敛动作拆开，WebUI 和 API 才能真正管理插件，而不是只能 reload 一个黑箱。

- **Phase 2:** 不做旧配置迁移，旧设计视为不存在。
  **Why:** 这是和 Phase 1 一致的替换哲学，避免为了兼容垃圾历史继续制造双轨系统。

- **Phase 3a:** Scheduler 采用 asyncio + SQLite 持久化，支持 cron / interval / one-shot，并能按 owner 做批量解绑。
  **Why:** 这足够覆盖单进程 runtime 的需求，也正好能和插件 unload 生命周期绑定。

- **Phase 3b:** LTM 走 "写入串行化 + 目录级备份 + 启动校验 + 优雅降级"。
  **Why:** 目标不是发明新记忆能力，而是保证 LanceDB 出问题时 bot 还能活着，不因为一块坏表把整个 runtime 拖死。

- **Phase 3c:** 日志采用 structlog 包装 stdlib 的渐进式接入，不推倒重来。
  **Why:** 这样能保住现有 logging 调用，同时把 run_id、thread_id、tool_name、token usage 这些结构化字段真的串起来。

- **Phase 4:** 对模型只暴露 1 个统一的 `message` tool，`send/react/recall` 通过 `action` 区分。
  **Why:** 统一 surface，后面继续扩更多消息能力时不会把工具面再拆碎。

- **Phase 4:** 只有 `send` 被抬成高层 `SEND_MESSAGE_INTENT`，`react` 和 `recall` 继续保持低层 direct action。
  **Why:** 需要内容编排、fallback、render、target 语义的只有 `send`，没必要让所有动作都走同一条重链路。

- **Phase 4:** cross-session send 明确拆开 `origin_thread_id`、`destination_thread_id`、`destination_conversation_id`。
  **Why:** `conversation_id` 是外部对话容器，`thread_id` 是 runtime 内部执行线程，这两个概念不能继续混着用。

- **Phase 4:** render 是 optional runtime capability，不是 Gateway 能力，也不是 Work World 能力。
  **Why:** render 失败时应该安全 fallback，artifact 也应该留在 `runtime_data/render_artifacts/` 这种内部目录里，而不是污染 workspace / attachments。

- **Phase 4:** facts 摘要和 working memory continuity 统一由 Outbox 通过 `OutboundMessageProjection` 生成。
  **Why:** 这样真实 `message.send` 不需要在 tool 层提前猜 `thread_content`，cross-session send、render continuity、消息事实落库也都能在同一个收口点同步。

---

## 3. Phases Delivered

| Phase | Name | Status | One-Liner |
|-------|------|--------|-----------|
| 1 | Reference Backend Removal | Executed | 把 Reference Backend 相关代码、配置、测试和 bootstrap 注入链整体删除，清掉旧设计残留。 |
| 2 | Plugin Reconciler | Executed | 用 reconciler 架构替换 monolithic plugin_manager，并交付新的 API、WebUI 插件管理页和 sample plugin。 |
| 3a | Scheduler | Executed | 补上正式 asyncio scheduler，支持 cron / interval / one-shot、持久化恢复和插件 owner 生命周期解绑。 |
| 3b | LTM Data Safety | Executed | 给 LanceDB 写入链补写锁、备份、启动校验和降级路径，避免 LTM 把 runtime 一起拖挂。 |
| 3c | Logging & Observability | Executed | 把 runtime 日志升级成结构化可观察体系，并把 WebUI 日志视图补成可读 structured fields。 |
| 4 | Unified Message Tool + Playwright | Verified | 已交付统一 message tool、send intent materialization、render service、Playwright backend，以及基于 Outbox projection 的 cross-session continuity 收口。 |

Phase 4 的 plan 粒度更细，实际已经交付了 4 段连续能力：

- `04-01`: 统一 `message` tool surface，锁死 send/react/recall schema，补齐 NapCat reaction payload
- `04-02`: `SEND_MESSAGE_INTENT` 进 Outbox，明确 destination thread contract，抑制重复默认回复
- `04-03`: render 子模块、依赖图、artifact helper、Playwright backend、fake browser tests
- `04-04`: bootstrap 默认注册 render service，Outbox 用 injected service 发图，RuntimeApp.stop() 负责回收

---

## 4. Requirements Coverage

- ✅ `REF-01..03`
  Phase 1 的执行目标和 `STATE.md` 验证结果都表明 Reference Backend 已被整段删除，零残留是这一 phase 的主线结果。

- ✅ `PLUG-01..13`
  Phase 2 已交付 plugin reconciler 基础模块、状态存储、API 替换、WebUI 重写和 sample plugin。

- ✅ `SCHED-01..08`
  `REQUIREMENTS.md` 已标记全部 `Validated`，Phase 3a state 也显示 completed。

- ✅ `LTM-01..04`
  `REQUIREMENTS.md` 已标记全部 `Validated`，Phase 3b state 也显示 completed。

- ✅ `LOG-01..06`
  `REQUIREMENTS.md` 已标记全部 `Validated`，Phase 3c state 也显示 completed。

- ✅ `MSG-01..10`, `PW-01..03`
  Phase 4 summaries、verification 和相关测试都给出了明确代码证据。

- ⚠️ Archive paperwork still pending
  代码、phase summary、phase verification 和 requirements 台账现在已经基本对齐，但 retrospective、milestone audit、正式 archive 还没做完，所以这个 milestone 仍然是 current state，不是归档态。

补充说明：

- 没有发现 milestone audit 文件
- 没有发现 `.planning/RETROSPECTIVE.md`
- 所以本 summary 是 "当前最新真实状态" 总结，不是归档审计结论

---

## 5. Key Decisions Log

| ID | Decision | Phase | Why it matters |
|----|----------|-------|----------------|
| M1-D01 | Reference Backend 彻底删除，不留兼容层 | 1 | 清掉死代码和错误抽象，避免后续重构继续背包袱 |
| M1-D02 | `reference_backend` 从 runtime/plugin/bootstrap/context 链路整体移除 | 1 | 让 Reference Backend 真正从主线消失，不只是文件删了 |
| M1-D03 | 插件身份从 import path 切到 `plugin_id` | 2 | 插件代码重构不会再把配置和 UI 打碎 |
| M1-D04 | 新插件系统采用 reconciler 模式，Spec 和 Status 分离 | 2 | 用户意图、运行状态、收敛动作终于不再混成一个类 |
| M1-D05 | Scheduler 用 SQLite 持久化到现有 runtime DB，并按 owner 清理 | 3a | 单进程方案够用，而且和插件生命周期天然对得上 |
| M1-D06 | LTM 故障必须 degrade，不允许阻断 runtime 主线 | 3b | 记忆系统变成可失效子系统，而不是启动硬前提 |
| M1-D07 | logging 走 structlog wrapper 模式，保留 stdlib logger | 3c | 能快速拿到结构化字段，又不需要一次性重写全项目日志 |
| M1-D08 | 统一 `message` tool surface，只把 `send` 抬为高层 intent | 4 | 对模型简单，对 runtime 内部仍保留合理分层 |
| M1-D09 | `SEND_MESSAGE_INTENT` 固定在 Outbox materialize 成 1 条低层消息 | 4 | render、fallback、cross-session、facts 落点都能集中收口 |
| M1-D10 | render service 是 bootstrap 注入的共享能力，artifact 固定落在 runtime internal path | 4 | 生命周期、资源回收和目录边界都清楚，不会污染 workspace |

---

## 6. Tech Debt & Deferred Items

- **Manual verification still pending**
  真实 QQ 客户端里的 quote + @ 展现、真实 cross-session 送达体验、render 图片可读性，这几项都还需要人工验收。

- **Artifact completeness is uneven**
  Phase 1、2、3a、3b、3c 没有像 Phase 4 那样统一的 `SUMMARY.md` / `VERIFICATION.md` 套件，导致团队 onboarding 时只能部分依赖推断总结。

- **Milestone paperwork is behind implementation**
  requirements / verification / progress 这几份主文档已经追平到当前代码状态，但 retrospective、milestone audit 和正式 archive 还没补，所以收档动作还差最后一段。

- **Not archived yet**
  当前 milestone 还没有 `v1.0` git tag，也没有 `.planning/milestones/` 归档快照，所以统计数据只能按当前 milestone 时间范围推算。

- **Known v2 backlog remains deferred**
  插件依赖拓扑、plugin marketplace、schedule-triggered agent runs、完整 run trace、token budget 可视化、合并转发、interactive components 这些都还在 v2 backlog。

---

## 7. Getting Started

- **Run the project:** `PYTHONPATH=src uv run python -m acabot.main`
- **Alternative entrypoint:** 安装项目后可直接用 `acabot`
- **Key directories:**
  - `src/acabot/` - runtime 主代码
  - `src/acabot/runtime/` - bootstrap、pipeline、tool、memory、scheduler、render 等核心基础设施
  - `src/acabot/runtime/control/` - control plane、HTTP API、日志缓冲
  - `webui/src/` - Vue 3 WebUI
  - `extensions/plugins/` - 新插件体系入口，当前有 `sample_tool`
  - `runtime_config/` - prompt、model binding、session config 等运行时配置
  - `.planning/phases/` - 本 milestone 的 phase 产物真源

- **Tests:** `PYTHONPATH=src uv run pytest --ignore=tests/runtime/backend/test_pi_adapter.py`

- **Where to look first:**
  - 想看 runtime 主线：`src/acabot/runtime/bootstrap/__init__.py`、`src/acabot/runtime/pipeline.py`、`src/acabot/runtime/app.py`
  - 想看插件系统：`src/acabot/runtime/plugin_protocol.py`、`plugin_runtime_host.py`、`plugin_reconciler.py`
  - 想看消息能力：`src/acabot/runtime/builtin_tools/message.py`、`src/acabot/runtime/outbox.py`、`src/acabot/gateway/napcat.py`
  - 想看 render：`src/acabot/runtime/render/`
  - 想看 scheduler：`src/acabot/runtime/scheduler/`
  - 想看 observability：`src/acabot/runtime/control/log_buffer.py`、`log_setup.py`、`webui/src/components/LogStreamPanel.vue`

---

## Stats

- **Timeline:** 2026-04-02 -> 2026-04-04
- **Phases:** 6 / 6 implemented, archive pending
- **Phase 4 plans:** 4 / 4 implemented
- **Commits:** 60
- **Files changed:** 245
- **Diff volume:** +28241 / -26782
- **Contributors:** `vacacia`, `viorettofu`
- **Git stats note:** 仓库里没有 `v1.0` tag，也没有 milestone archive，所以这里的统计是按 `git log --since='2026-04-02'` 推算的当前 milestone 范围

---

**Bottom line:** AcaBot v1.0 的 runtime 基础设施已经从 "散、旧、缺关键能力" 进化成 "主骨架清晰、可扩展、可观测、消息能力完整度很高"。现在真正拦着它收档的，不是主线代码问题，而是真人验收、台账同步和 milestone archive 这些收尾动作。
