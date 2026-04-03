---
phase: 04-unified-message-tool-playwright
plan: 01
subsystem: messaging
tags: [message-tool, napcat, builtin-tools, pytest, qq]
requires: []
provides:
  - unified message builtin tool with send/react/recall surface
  - SEND_MESSAGE_INTENT action contract for high-level send planning
  - NapCat REACTION payload mapping via set_msg_emoji_like
affects: [04-02, 04-03, outbox, gateway, tool-broker]
tech-stack:
  added: []
  patterns:
    - "Unified message tool surface with one tool name and action enum"
    - "Only send becomes high-level intent; react and recall stay low-level actions"
key-files:
  created:
    - src/acabot/runtime/builtin_tools/message.py
    - tests/runtime/test_message_tool.py
  modified:
    - src/acabot/types/action.py
    - src/acabot/runtime/builtin_tools/__init__.py
    - src/acabot/gateway/napcat.py
    - tests/runtime/test_builtin_tools.py
    - tests/test_gateway.py
    - docs/01-system-map.md
    - docs/02-runtime-mainline.md
    - docs/03-data-contracts.md
    - docs/07-gateway-and-channel-layer.md
    - docs/18-tool-skill-subagent.md
key-decisions:
  - "Unified message tool keeps one model-facing name while only send becomes SEND_MESSAGE_INTENT."
  - "NapCat reaction delivery uses the dedicated set_msg_emoji_like payload and leaves recall on delete_msg."
patterns-established:
  - "Builtin message surface returns ToolResult.user_actions only and never calls Gateway directly."
  - "Canonical send targets are validated as qq:user:* or qq:group:* before becoming Action payload."
requirements-completed: [MSG-04, MSG-05, MSG-07, MSG-10]
duration: 5min
completed: 2026-04-04
---

# Phase 04 Plan 01: Unified Message Tool Surface Summary

**Unified `message` builtin tool with locked send/react/recall schema, high-level `SEND_MESSAGE_INTENT`, and NapCat reaction payload support**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-03T17:52:57Z
- **Completed:** 2026-04-03T17:57:22Z
- **Tasks:** 2
- **Files modified:** 12

## Accomplishments

- 新增 `builtin:message` surface, 对模型只暴露一个 `message` tool, 并锁定 `send` / `react` / `recall` 三种 action。
- `message.send` 现在产出高层 `SEND_MESSAGE_INTENT`, 明确携带 `text`、`images`、`render`、`at_user`、`target` 和默认回复抑制 metadata。
- NapCat gateway 补齐 `REACTION -> set_msg_emoji_like(message_id, emoji_id)` 映射, 现有 `RECALL -> delete_msg` 路径保持不变。

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement the unified `message` builtin tool surface and locked schema**
   - `413571d` (`test`) RED: add failing tests for unified message tool
   - `85f27dc` (`feat`) GREEN: implement unified message tool surface
2. **Task 2: Register `message` as a core builtin tool and add NapCat reaction payload support**
   - `893b56c` (`test`) RED: add failing tests for message registration and reaction payload
   - `4231417` (`feat`) GREEN: register message builtin and support reaction payloads

**Additional docs sync:** `e25b106` (`docs`) sync unified message tool contracts

## Files Created/Modified

- `src/acabot/runtime/builtin_tools/message.py` - 统一 `message` builtin tool surface, 包含 send/react/recall handler 和 target / emoji 校验
- `src/acabot/types/action.py` - 新增高层 `ActionType.SEND_MESSAGE_INTENT`
- `src/acabot/runtime/builtin_tools/__init__.py` - 把 `builtin:message` 接进 core builtin registration
- `src/acabot/gateway/napcat.py` - 新增 `REACTION -> set_msg_emoji_like` 出站 payload
- `tests/runtime/test_message_tool.py` - 覆盖 schema 锁定、user_actions-only、reaction 严格失败、recall 直通和 D-08 文案
- `tests/runtime/test_builtin_tools.py` - 断言 runtime builtin 注册链包含 `message`, 并把 plugin status 测试写入路径隔离到 `tmp_path`
- `tests/test_gateway.py` - 固定 reaction payload 契约并保留 recall 回归断言
- `docs/01-system-map.md` - 更新 bootstrap builtin tool 列表
- `docs/02-runtime-mainline.md` - 更新 mainline 中 core builtin tool 描述
- `docs/03-data-contracts.md` - 记录 `SEND_MESSAGE_INTENT` 及高低层动作边界
- `docs/07-gateway-and-channel-layer.md` - 记录 NapCat reaction payload 映射
- `docs/18-tool-skill-subagent.md` - 记录 `message` builtin tool 语义和 send 抑制规则

## Decisions Made

- `message` 对模型只保留一个工具名, 通过 `action` 字段区分操作, 这样后续扩展 send intent materialization 和 render 能力时不会再拆 surface。
- 只有 `send` 进入高层 intent family, `react` / `recall` 继续保持底层直通动作, 避免简单动作被不必要地拖进 Outbox 编排链。
- `message.send` 在 tool 层就写死默认回复抑制 metadata 和 canonical destination, 给 04-02 的 Outbox materialization 一个稳定输入。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 隔离 builtin tool 测试的 plugin status 写入路径**
- **Found during:** Task 2 RED
- **Issue:** `test_builtin_core_tools_survive_reconciler_run` 试图往仓库根目录 `runtime_data/plugins/` 写状态, 当前环境权限拒绝, 会挡住 Task 2 的验证命令。
- **Fix:** 把该测试切到 `tmp_path / "runtime_data"` 作为 `runtime_root`, 保持断言目标不变。
- **Files modified:** `tests/runtime/test_builtin_tools.py`
- **Verification:** `PYTHONPATH=src uv run pytest -q tests/runtime/test_builtin_tools.py tests/test_gateway.py`
- **Committed in:** `893b56c`

**2. [Rule 2 - Missing Critical] 按 CLAUDE.md 要求同步更新契约文档**
- **Found during:** Plan wrap-up
- **Issue:** 本计划修改了 builtin tool surface、ActionType 和 gateway payload, 如果不更新主文档, 代码和文档会立刻分叉。
- **Fix:** 同步更新 system map、runtime mainline、data contracts、gateway layer、tool system 文档。
- **Files modified:** `docs/01-system-map.md`, `docs/02-runtime-mainline.md`, `docs/03-data-contracts.md`, `docs/07-gateway-and-channel-layer.md`, `docs/18-tool-skill-subagent.md`
- **Verification:** 手工检查文档表述与当前代码一致, 并完成总验证测试
- **Committed in:** `e25b106`

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 missing critical)
**Impact on plan:** 都是收口型修正。一个保证测试可运行, 一个保证文档真源不漂移, 没有引入额外架构范围。

## Issues Encountered

- Task 2 的验证子集暴露了一个测试环境耦合问题: builtin tool 回归测试默认写仓库根目录的 `runtime_data/`。已切到 `tmp_path`, 现在验证命令稳定通过。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `SEND_MESSAGE_INTENT` 已经是稳定输入, 04-02 可以直接接 Outbox materialization、cross-session persistence 语义和默认回复抑制逻辑。
- `message.react` / `message.recall` 的低层 contract 已经锁死, 后续 phase 不需要再碰 tool surface 和 NapCat reaction payload。
- No blockers.

## Self-Check: PASSED

- Found `.planning/phases/04-unified-message-tool-playwright/04-01-SUMMARY.md`
- Found commits: `413571d`, `85f27dc`, `893b56c`, `4231417`, `e25b106`
