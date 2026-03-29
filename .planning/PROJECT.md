# AcaBot

## What This Is

AcaBot 是一个面向 QQ / NapCat 场景的本地优先 agent runtime 和后台控制台。它的目标不是只把模型接起来跑，而是让操作者能够通过统一的 WebUI 看懂、配置和维护 bot 的真实行为，而不是继续依赖分散配置文件、硬编码路径和源码猜系统怎么运行。

当前这轮工作主要先服务你自己把系统收稳、收可用，但产品方向不是“只给作者自己调试的私人工具”。在核心控制面稳定后，它还需要能让其他操作者通过 quickstart 上手。

## Core Value

操作者必须能通过一个真实可用的 WebUI 稳定地理解并控制 AcaBot 的行为。

## Requirements

### Validated

- ✓ AcaBot 已经具备一套正式 runtime 主线，包含 gateway、router、pipeline、tool broker、memory、subagent、control plane 等核心结构 — existing
- ✓ AcaBot 已经具备本地 WebUI shell、HTTP API 和多个后台页面入口，而不是纯命令行系统 — existing
- ✓ AcaBot 已经具备 sticky notes、长期记忆、模型注册表、session 契约等第一版能力，只是很多地方还没有真正产品化 — existing
- ✓ 仓库中已经存在较完整的设计文档和页面草图，可直接作为 brownfield 演进真源 — existing

### Active

- [ ] 把 WebUI 做到“能正常设置 AcaBot 行为”，让现有页面里明确要用的管理内容真正生效
- [ ] 统一旧代码中分散的硬编码路径、设置和运行时数据目录，让系统知道哪些路径才是正式真源
- [ ] 把 Session 管理重新接回当前 runtime / session contract，而不是继续保留废弃配置入口
- [ ] 把长期记忆从“简陋但能跑”提升到“可配置、可观察、可解释、可日常使用”
- [ ] 在控制面稳定后，为未来其他操作者补 Quickstart 和最小上手文档

### Out of Scope

- 聊天工作区 / 对话工作台 — 当前 WebUI 明确不做，先聚焦后台控制台
- 单独的“平台”页面 — 已决定并入系统页，避免再拆一套弱价值导航
- 插件市场、在线安装、版本管理 — 先把现有插件 / skill / subagent 控制面做实，再谈分发系统
- 把底层实现细节原样暴露给普通操作者 — 例如直接把数据库或内部目录结构当产品字段展示，这会放大系统噪音

## Context

这是一个明确的 brownfield 项目，不是从零开始的新应用。当前代码里已经有新的 runtime 主线、session 契约、control plane 和 WebUI shell，但“可操作性”还没有真正收口。

从现有设计稿和代码状态来看，WebUI 的页面分类、页面定位和很多管理项已经被你一点点想清楚了，尤其是 `webui-pages-draft.md` 里对首页、Session、记忆、模型供应商、模型预设、提示词、日志、系统、技能、插件、工具、SubAgent 等页面的产品定位已经很明确。当前问题不是“还没想好要什么页”，而是“这些页还没有都接到正式真源上，也不一定真的能生效”。

同时，runtime 侧还有两条直接影响可用性的老问题：

- 路径 / 配置 / 运行时数据目录分散，很多地方还是硬编码或隐式默认，导致操作者很难判断系统真正把数据写到了哪里
- 长期记忆虽然已经接上了最小可运行链路，但离“实用的产品能力”还有明显距离

这轮工作的价值不在于再堆一个新特性，而在于把现有这些能力收成“用户真的能操作、能理解、能持续维护”的正式系统。

## Constraints

- **Brownfield**: 必须沿着现有 runtime 主线、session contract 和 control plane 演进，而不是另起炉灶重写一套系统 — 因为当前代码和文档已经形成正式边界
- **Product Scope**: 现有 WebUI 页面信息架构和页面定位优先保持稳定 — 因为这些页面内容已经是你明确打磨过的需求，而不是随手占位
- **Source of Truth**: WebUI 的每一个正式管理项都必须接到真实配置 / 目录 / registry / runtime 契约，而不是停留在占位 UI 状态 — 因为“页面存在但不生效”会直接毁掉控制面的可信度
- **Operability**: 路径、数据目录、filesystem catalog、运行时存储位置必须可统一解析和可说明 — 因为当前连操作者自己都不总能判断运行时数据实际落点
- **Audience**: 当前优先级是操作者可用性，后续要支持其他人上手 — 因为 Quickstart 和可维护性是明确后续目标

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| 先以 WebUI 可用性为这一轮最高优先级 | 没有真实可用的控制面，很多能力虽然“在代码里存在”，但实际上没法稳定使用 | — Pending |
| 先统一 runtime 路径 / 配置 / 数据目录，再继续铺 WebUI 生效链 | 页面只有接到正式真源上才有意义；路径不统一会让所有“保存并生效”都变得脆弱 | — Pending |
| Session 页必须围绕新的 session/runtime 契约重做，而不是恢复旧私有模型表单 | 旧入口会把系统重新带回已经废弃的配置路径 | — Pending |
| 长期记忆要从最小实验链路升级成可操作的产品能力 | 当前 LTM 太简陋，无法支撑日常使用与调试 | — Pending |
| Quickstart 放在控制面收稳之后再补 | 先让系统自己站稳，再给其他人提供稳定上手路径 | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `$gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `$gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-29 after initialization*
