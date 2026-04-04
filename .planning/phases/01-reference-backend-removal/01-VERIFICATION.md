---
phase: 01-reference-backend-removal
verified: 2026-04-04T08:38:20Z
status: passed
score: 3/3 requirements verified
gaps: []
---

# Phase 01: Reference Backend Removal Verification Report

**Phase Goal:** 把 Reference Backend 整段历史删干净, 让当前仓库里只剩删除结果, 不再剩任何 source import、runtime wiring、config entry 或测试耦合。
**Verified:** 2026-04-04T08:38:20Z
**Status:** passed

## Goal Achievement

Phase 01 的三条 requirement 现在都有可重复执行的证据:

- REF-01 已经不是“我记得当时删过”这种口头说法, 而是 git 删除历史加今天仓库的 source-file zero check。
- REF-02 已经不是“应该没问题”, 而是 `BackendBridgeToolPlugin` 的 targeted pytest 仍然能过。
- REF-03 已经用 `config.example.yaml` 和 runtime wiring zero-hit 检查固定住, 没再给 reference config 留缝。

## Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Reference backend 源码文件已经删光, 当前目录只剩 `__pycache__` `.pyc` 缓存。 | ✓ VERIFIED | `find src/acabot/runtime/references -type f ! -path '*/__pycache__/*' -print -quit 2>/dev/null` 无输出 |
| 2 | `reference_tools.py` 和 `reference_ops.py` 已删除。 | ✓ VERIFIED | shell `test ! -f ...` 通过 |
| 3 | `src/`、`tests/`、`config.example.yaml` 里不再残留 reference backend 相关符号。 | ✓ VERIFIED | zero-hit `rg` 检查通过 |
| 4 | `BackendBridgeToolPlugin` 现在不依赖 reference backend, 但仍可导入并通过 targeted pytest。 | ✓ VERIFIED | `2 passed in 2.73s` |
| 5 | `config.example.yaml` 已经没有 `reference:` section, bootstrap 和 app 里也没有 `reference_backend` wiring。 | ✓ VERIFIED | REF-03 shell 检查通过 |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| REF-01 deletion reality check | `test -z "$(find src/acabot/runtime/references -type f ! -path '*/__pycache__/*' -print -quit 2>/dev/null)" && test ! -f src/acabot/runtime/plugins/reference_tools.py && test ! -f src/acabot/runtime/control/reference_ops.py && ! rg -n "reference_backend|ReferenceBackend|ReferenceToolsPlugin|reference_tools|reference_ops" src tests config.example.yaml` | pass, no output | ✓ PASS |
| REF-02 BackendBridge importability | `PYTHONPATH=src uv run pytest -q tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable` | `2 passed in 2.73s` | ✓ PASS |
| REF-03 config and wiring cleanup | `! rg -n "^[[:space:]]*reference:" config.example.yaml && ! rg -n "reference_backend|ReferenceBackend" src/acabot/runtime/bootstrap src/acabot/runtime/app.py` | pass, no output | ✓ PASS |

## Requirements Coverage

| Requirement | Description | Command | Status | Evidence |
| --- | --- | --- | --- | --- |
| `REF-01` | Reference Backend subsystem completely deleted, no residual imports | `test -z "$(find src/acabot/runtime/references -type f ! -path '*/__pycache__/*' -print -quit 2>/dev/null)" && test ! -f src/acabot/runtime/plugins/reference_tools.py && test ! -f src/acabot/runtime/control/reference_ops.py && ! rg -n "reference_backend|ReferenceBackend|ReferenceToolsPlugin|reference_tools|reference_ops" src tests config.example.yaml` | ✓ SATISFIED | source files 无命中, deleted files 不存在, residual symbol grep 为 0 |
| `REF-02` | BackendBridgeToolPlugin decoupled from Reference Backend and transition-period usable | `PYTHONPATH=src uv run pytest -q tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable` | ✓ SATISFIED | `2 passed in 2.73s` |
| `REF-03` | Reference-related config and runtime wiring cleaned from example config and core startup path | `! rg -n "^[[:space:]]*reference:" config.example.yaml && ! rg -n "reference_backend|ReferenceBackend" src/acabot/runtime/bootstrap src/acabot/runtime/app.py` | ✓ SATISFIED | config.example.yaml 无 `reference:` section, bootstrap / app 无 reference wiring |

## Notes For Audit

- `__pycache__` 不能当成 REF-01 回归。Phase 01 删除的是 reference backend 源码和接线, 不是禁止 Python 重新生成缓存目录。
- `verify phase-completeness 01` 当前会把 `01-PLAN-01-SUMMARY.md` 和 `01-PLAN-02-SUMMARY.md` 标成 orphan summary warning, 原因是它的匹配逻辑只认 `-PLAN.md` 文件名; 这不影响本 phase 的 legacy basename backfill 目标, 也不影响本文件对 REF-01..03 的验证结论。

---

_Verified: 2026-04-04T08:38:20Z_  
_Verifier: Codex_
