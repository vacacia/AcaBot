# Phase 2: Plugin Reconciler - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-03
**Phase:** 02-plugin-reconciler
**Areas discussed:** WebUI interaction feel, Sample plugin, Plugin capability audit scope

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Sample plugin | SC#1 requires sample plugin — what should it do? | |
| Config migration | Import path to plugin_id migration path | |
| WebUI interaction feel | Loading/error/feedback patterns in the UI | ✓ |
| ADR update needed | reference_backend stale in ADR | |

**User's notes:**
1. Research 阶段要看看 plugin 应该实现哪些能力，目前的设计是否足够
2. 不需要考虑配置迁移/兼容，同样当旧设计不存在，所有的数据/配置都不重要
4. 先修正 ADR

---

## WebUI Interaction Feel

### Q1: Progress & result feedback

| Option | Description | Selected |
|--------|-------------|----------|
| Inline state only (Recommended) | Loading spinner + disabled controls, no toast | |
| Inline + toast | Inline state + small toast notifications for success/error | ✓ |
| You decide | Let Claude decide | |

**User's choice:** Inline + toast
**Notes:** None

### Q2: Error display for failed plugins

| Option | Description | Selected |
|--------|-------------|----------|
| Inline error panel (Recommended) | Red section in expanded panel with full traceback | |
| Badge + modal | Failed badge on list, full error in modal on click | ✓ |
| Badge + expandable | Red badge with first line, click to expand | |

**User's choice:** Badge + modal
**Notes:** None

### Q3: Rescan reconcile UX

| Option | Description | Selected |
|--------|-------------|----------|
| Simple refresh (Recommended) | Button → spinner → list refreshes | |
| Progressive updates | Per-plugin status updates during reconcile | ✓ |
| You decide | Let Claude decide | |

**User's choice:** Progressive updates
**Notes:** 另外，下面的discuss使用中文

### Q3b: Progressive updates implementation

| Option | Description | Selected |
|--------|-------------|----------|
| 等全部完成后刷新 | reconcile_all 返回后一次性更新列表 | |
| SSE 实时推送 | 每个插件 reconcile 完推送一条更新 | |
| 两阶段刷新（推荐） | 先返回 package 列表（reconciling 状态），完成后再请求最终状态 | ✓ |

**User's choice:** 两阶段刷新
**Notes:** None

---

## Additional Gray Areas (Round 2)

### Selection

| Option | Description | Selected |
|--------|-------------|----------|
| PackageCatalog 边界 | Python 命名空间包在三种环境下的行为 | |
| BackendBridge 过渡 | BackendBridgeToolPlugin import 迁移 | |
| 插件能力审视范围 | Research 阶段审视插件基建需求空缺 | ✓ |
| Sample plugin 用途 | 测试用 vs 模板 vs 单测替代 | ✓ |

---

## Sample Plugin

| Option | Description | Selected |
|--------|-------------|----------|
| 纯测试用 echo plugin | 最简单的 echo tool，验证完可删 | |
| 可以留作模板的示例插件 | 小但有用的工具 + config_schema 示例，留在 repo 里 | ✓ |
| 不需要，单测就够了 | 用 mock plugin 在单测里验证 | |

**User's choice:** 可以留作模板的示例插件
**Notes:** None

---

## Plugin Capability Audit Scope

| Option | Description | Selected |
|--------|-------------|----------|
| 协议层 + 占位设计（推荐） | 审视 RuntimePlugin 协议和 RuntimePluginContext 是否完备 | |
| 只看本轮实现 | 只审视 ADR 中明确的 6 个模块 | |
| 对标行业实践 | 对比 pluggy/stevedore 等看是否遗漏常见能力 | |

**User's choice:** Other — "能力是指插件是否有不同的基建需求，比如之前没考虑过插件会需要LLM，插件需要持久化数据存储，插件需要定时任务。现在发现了空缺的能力(在ADR里写过了)，看看是否还需要考虑什么能力"
**Notes:** Research 阶段要检查：ADR 已记录的 4 个空缺（LLM 调用、定时任务、富消息发送、平台适配器 API）之外，是否还有遗漏的插件基建需求。

---

## Claude's Discretion

- Sample plugin 的具体功能（提供什么工具）
- 两阶段刷新 API 的内部实现方式
- 测试结构和组织

## Deferred Ideas

None — discussion stayed within phase scope
