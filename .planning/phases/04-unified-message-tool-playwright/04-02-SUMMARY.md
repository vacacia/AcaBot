---
phase: 04-unified-message-tool-playwright
plan: 2
subsystem: runtime
tags: [message-tool, outbox, pipeline, cross-session, qq]
requires:
  - phase: 04-01
    provides: unified message builtin tool surface and SEND_MESSAGE_INTENT action type
provides:
  - canonical conversation_id -> destination thread helpers
  - send intent materialization into one low-level SEND_SEGMENTS action
  - cross-session message facts and working memory updates on destination thread
  - duplicate default reply suppression for content-type message.send
affects: [04-03, 04-04, message-runtime, runtime-docs]
tech-stack:
  added: []
  patterns: [explicit destination-thread contract, outbox materialization, model-runtime reply suppression]
key-files:
  created: [src/acabot/runtime/ids.py]
  modified:
    [
      src/acabot/runtime/contracts/context.py,
      src/acabot/runtime/outbox.py,
      src/acabot/runtime/model/model_agent_runtime.py,
      src/acabot/runtime/pipeline.py,
      tests/runtime/test_outbox.py,
      tests/runtime/test_model_agent_runtime.py,
      tests/runtime/test_pipeline_runtime.py,
      docs/01-system-map.md,
      docs/02-runtime-mainline.md,
      docs/03-data-contracts.md
    ]
key-decisions:
  - "OutboxItem 显式拆出 origin_thread_id、destination_thread_id、destination_conversation_id, 不再让 cross-session 语义躲在 metadata 里"
  - "SEND_MESSAGE_INTENT 一律在 Outbox 物化成单条 SEND_SEGMENTS, reply_to 继续走 Action.reply_to"
  - "默认回复抑制只认 ActionType.SEND_MESSAGE_INTENT + suppresses_default_reply, react/recall 永远不抑制"
patterns-established:
  - "Pattern: cross-session send 的消息事实、working memory、LTM dirty 全部跟 destination_thread_id 对齐"
  - "Pattern: default assistant text append 的唯一判断点在 ModelAgentRuntime._to_runtime_result()"
  - "Pattern: internal delivery report 和真实 Outbox delivery 使用同一套 destination contract"
requirements-completed: [MSG-01, MSG-02, MSG-03, MSG-06, MSG-09]
duration: 6m
completed: 2026-04-03
---

# Phase 04 Plan 02: Runtime Send Path Summary

**Canonical destination-thread send delivery with outbox materialization, cross-session persistence, and duplicate-reply suppression for `message.send`**

## Performance

- **Duration:** 6m
- **Started:** 2026-04-04T02:03:48+08:00
- **Completed:** 2026-04-03T18:10:39Z
- **Tasks:** 3
- **Files modified:** 11

## Accomplishments

- 把 `conversation_id`、`destination_thread_id`、`origin_thread_id` 的 contract 固定成显式字段, 不再靠隐式 metadata 猜目标线程。
- 让 `SEND_MESSAGE_INTENT` 真正接进 `Outbox -> Gateway` 主线, 支持 `reply_to`、`at_user`、`images`、`target` 和 `render` text fallback。
- 把 cross-session send 的消息事实、working memory 和默认回复抑制语义都落到正确位置, 避免 "tool send + assistant text" 双发。

## Task Commits

Each task was committed atomically:

1. **Task 1: Define canonical destination-thread contracts for send intent delivery** - `0ab0293`, `35a1ba5`
2. **Task 2: Materialize `SEND_MESSAGE_INTENT` into one low-level send action** - `81c13ea`, `7ace988`
3. **Task 3: Suppress duplicate default replies and update the correct thread after delivery** - `992e975`, `aebf9b5`
4. **Docs sync:** `c72ab8e`

## Files Created/Modified

- `src/acabot/runtime/ids.py` - 集中解析 canonical `conversation_id` 并生成 destination `EventSource` / `thread_id`
- `src/acabot/runtime/contracts/context.py` - 为 `OutboxItem` 增加 origin/destination thread contract 字段
- `src/acabot/runtime/outbox.py` - 物化 `SEND_MESSAGE_INTENT`, 并把 facts/LTM dirty 改到 destination thread
- `src/acabot/runtime/model/model_agent_runtime.py` - 在默认文本追加点做 content send suppression
- `src/acabot/runtime/pipeline.py` - cross-session delivered content 改写 destination thread working memory
- `tests/runtime/test_outbox.py` - send intent materialization 和 cross-session persistence 覆盖
- `tests/runtime/test_model_agent_runtime.py` - 默认回复抑制与非抑制覆盖
- `tests/runtime/test_pipeline_runtime.py` - destination thread working memory 覆盖
- `docs/01-system-map.md` - 同步主线职责说明
- `docs/02-runtime-mainline.md` - 同步 pipeline/outbox 的 cross-session send 语义
- `docs/03-data-contracts.md` - 同步 `OutboxItem` destination contract 与 suppression 规则

## Decisions Made

- 保留 `conversation_id` 和 `thread_id` 两套字段语义, 即使 v1 的 `build_thread_id_from_conversation_id()` 仍返回相同 canonical 字符串。
- `render` 在本 plan 里故意不接 render backend, 只在 Outbox materialization 时退化成原样 text segment, 为 04-03 留出升级点。
- `ThreadPipeline._build_internal_delivery_report()` 也同步走 destination contract, 避免内部送达模式和真实发送模式出现双轨语义。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 补齐 internal delivery report 的 destination-thread 语义**
- **Found during:** Task 3
- **Issue:** `deliver_actions=False` 的 internal delivery report 还在把所有动作默认挂回当前 thread, 和真实 Outbox 送达语义不一致。
- **Fix:** 让 `ThreadPipeline._build_internal_delivery_report()` 也解析 `destination_conversation_id` / `destination_thread_id`, 复用同一套目标 contract。
- **Files modified:** `src/acabot/runtime/pipeline.py`
- **Verification:** `PYTHONPATH=src uv run pytest -q tests/runtime/test_model_agent_runtime.py tests/runtime/test_pipeline_runtime.py`
- **Committed in:** `aebf9b5`

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** 这个修补只是在同一文件里补齐一致性, 没扩 scope, 但避免了后面 internal mode 再写回错 thread。

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `message.send` 的 runtime 主线已经闭合, 04-03 可以直接在 Outbox materialization 层接 render service / Playwright backend。
- `render` 目前仍按计划退化成普通 text segment, 这不是 bug, 是下一 plan 的明确接入点。

## Self-Check: PASSED

- Found `.planning/phases/04-unified-message-tool-playwright/04-02-SUMMARY.md`
- Found commits `0ab0293`, `35a1ba5`, `81c13ea`, `7ace988`, `992e975`, `aebf9b5`, `c72ab8e`
