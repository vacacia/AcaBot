---
phase: 01-reference-backend-removal
plan: 02
subsystem: infra
tags: [reference-backend, integration-cleanup, config, backend-bridge, audit-backfill]
requires:
  - phase: 01-reference-backend-removal
    provides: reference backend files already deleted by Plan 01
provides:
  - reference backend imports and bootstrap wiring removed from runtime integration points
  - config.example.yaml cleared of reference section and app/bootstrap free of reference wiring
  - legacy basename summary file for Plan 02 with REF-01 REF-02 REF-03 coverage
affects: [phase-01-verification, phase-01-validation, requirements-audit]
tech-stack:
  added: []
  patterns:
    - "REF-01 must ignore `references/__pycache__` and only check for real source files."
    - "Transitional plugins can survive subsystem deletion when targeted smoke tests still pass."
key-files:
  created:
    - .planning/phases/01-reference-backend-removal/01-PLAN-02-SUMMARY.md
  modified: []
key-decisions:
  - "Use commit 8183ad7 as the authoritative proof for reference integration cleanup."
  - "Record BackendBridgeToolPlugin as intentionally preserved transition code because it still imports and tests cleanly without reference backend."
patterns-established:
  - "Legacy basename summary matching is literal: `01-PLAN-02.md` pairs with `01-PLAN-02-SUMMARY.md`."
  - "Deletion verification uses source-file absence plus zero-symbol grep, not directory absence."
requirements-completed: [REF-01, REF-02, REF-03]
duration: 8min
completed: 2026-04-04
---

# Phase 01 Plan 02: Reference Backend Integration Cleanup Summary

**Reference backend imports, app/bootstrap wiring, runtime exports, and config example entries were removed in commit `8183ad7`, while `BackendBridgeToolPlugin` stayed importable and Phase 01 now has a legacy basename summary that current GSD can match**

Primary evidence files: `.planning/phases/01-reference-backend-removal/01-PLAN-02-SUMMARY.md` and `.planning/phases/01-reference-backend-removal/01-PLAN-02.md`.

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-04T08:05:00Z
- **Completed:** 2026-04-04T08:13:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- 把旧 Phase 01 Plan 02 的 integration cleanup 历史补成当前 GSD 能识别的 summary 文件, basename 严格保持 `01-PLAN-02`.
- 记录 `8183ad7` 里 14 个文件、379 行删除事实, 覆盖 bootstrap、app、plugin manager、HTTP API、control plane、runtime exports、config 和测试清理。
- 把 `REF-01`、`REF-02`、`REF-03` 的当前仓库事实写实: reference wiring 已经消失, `BackendBridgeToolPlugin` 仍可导入, `config.example.yaml` 不再有 `reference:` 配置。

## Task Commits

This plan was originally completed in one historical commit:

1. **Task 1: Remove all reference backend integration points from runtime and tests**  
   - `8183ad7` (`refactor`) remove all reference backend integration points

## Historical Facts

- `git log --oneline --grep='refactor: remove all reference backend integration points' -n 1`
  - 命中: `8183ad7 refactor: remove all reference backend integration points (Phase 1, PLAN-02)`
- `git show --stat --summary 8183ad7`
  - 14 files changed, 379 deletions
  - `config.example.yaml` 删除 reference config section
  - `src/acabot/runtime/__init__.py` 删除 reference re-export
  - `src/acabot/runtime/app.py` 删除 `reference_backend` 相关参数和关闭逻辑
  - `src/acabot/runtime/bootstrap/__init__.py`、`builders.py`、`components.py` 删除 reference wiring
  - `src/acabot/runtime/control/control_plane.py`、`http_api.py` 删除 reference control path
  - `src/acabot/runtime/plugin_manager.py` 删除 `reference_backend` 上下文字段
  - `src/acabot/runtime/plugins/__init__.py` 删除 `ReferenceToolsPlugin`
  - `tests/runtime/test_app.py`、`tests/runtime/test_bootstrap.py`、`tests/test_main.py`、`tests/runtime/test_webui_api.py` 清理 reference 相关断言

## Current Facts

- `test -z "$(find src/acabot/runtime/references -type f ! -path '*/__pycache__/*' -print -quit 2>/dev/null)"` 通过。正确检查方式是忽略 `__pycache__` 后确认没有真实源码文件, 不能把目录本身存在误写成回归。
- `test ! -f src/acabot/runtime/plugins/reference_tools.py && test ! -f src/acabot/runtime/control/reference_ops.py` 通过。
- `! rg -n "reference_backend|ReferenceBackend|ReferenceToolsPlugin|reference_tools|reference_ops" src tests config.example.yaml` 通过。
- `PYTHONPATH=src uv run pytest -q tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable` 通过, 结果是 `2 passed in 2.73s`。
- `! rg -n "^[[:space:]]*reference:" config.example.yaml && ! rg -n "reference_backend|ReferenceBackend" src/acabot/runtime/bootstrap src/acabot/runtime/app.py` 通过。
- `BackendBridgeToolPlugin` 仍可导入, 当前仓库保留它作为过渡插件, 但它已经不依赖 reference backend。
- `config.example.yaml` 当前没有 `reference:` section, 也没有 `reference_backend` 相关字样。

## Files Created/Modified

- `.planning/phases/01-reference-backend-removal/01-PLAN-02-SUMMARY.md` - 回填旧 Plan 02 的 integration cleanup 证据、legacy basename 说明、`BackendBridgeToolPlugin` 冒烟结果和 `config.example.yaml` 当前状态。

## Decisions Made

- `REF-01` 用“源码文件不存在 + symbol zero-hit”证明, 不再使用“目录必须不存在”这种会被 `__pycache__` 误伤的写法。
- 把 `BackendBridgeToolPlugin` 写成保留的过渡代码, 因为今天的 targeted pytest 仍然证明它能导入且可见性正确。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `python` 命令在当前仓库环境里不存在**
- **Found during:** evidence collection for current repository facts
- **Issue:** plan 里的辅助探测如果直接写 `python - <<'PY'` 会失败, 因为当前 shell 只有 `python3` 和 `uv run` 可用。
- **Fix:** backfill 文档保留 plan 里的正式验证命令不变, 实际探测时改用 `python3` 或直接用 shell / `uv run pytest`。
- **Files modified:** `.planning/phases/01-reference-backend-removal/01-PLAN-02-SUMMARY.md`
- **Verification:** `PYTHONPATH=src uv run pytest -q tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable`
- **Committed in:** not committed in this backfill session

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** 只是命令执行层的最小调整, 不影响 requirement 结论和文档结构。

## Issues Encountered

- 当前仓库是 dirty worktree, 有别人正在改的文件。我只回填计划允许的 summary / verification / validation 证据文件, 没去碰运行时代码和顶层 planning 状态文件。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `01-VERIFICATION.md` 现在可以直接复用这里的三条 requirement 证据。
- `01-VALIDATION.md` 可以明确写出 `__pycache__` 不是源码残留, 给后续 Nyquist 读取一个稳定规则。

## Self-Check: PASSED

- Found `.planning/phases/01-reference-backend-removal/01-PLAN-02-SUMMARY.md`
- Found commit: `8183ad7`
