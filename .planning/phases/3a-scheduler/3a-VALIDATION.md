---
phase: 3a-scheduler
validated: 2026-04-04T17:13:00Z
nyquist_compliant: true
status: ready-for-audit
scope: phase
---

# Phase 3a Validation

## Validation Architecture

Phase 3a 的验证现在分 3 层:

1. Wave summary 层
   - `3a-01-SUMMARY.md` 固定 `SCHED-01..06`
   - `3a-02-SUMMARY.md` 固定 `SCHED-07..08`
2. Current executable checks 层
   - `tests/test_scheduler.py` 证明 scheduler core
   - `tests/test_scheduler_integration.py` 证明 plugin unload 和 RuntimeApp lifecycle
3. Historical evidence 层
   - `94ffb24` 证明 Wave 1 核心交付
   - `2a202ac` 证明 Wave 2 集成交付

## Per-Task Verification Map

| Task | Output | Requirement Coverage | Validation Method |
| --- | --- | --- | --- |
| Task 1 | [3a-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3a-scheduler/3a-01-SUMMARY.md) | `SCHED-01..06` | `git show --stat --summary 94ffb24` + `PYTHONPATH=src uv run pytest -q tests/test_scheduler.py` |
| Task 2 | [3a-02-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3a-scheduler/3a-02-SUMMARY.md) | `SCHED-07..08` | `git show --stat --summary 2a202ac` + `PYTHONPATH=src uv run pytest -q tests/test_scheduler_integration.py -k 'unload_plugin_cancels_scheduled_tasks or app_start_starts_scheduler or app_stop_order'` |
| Task 3 | [3a-VERIFICATION.md](/home/acacia/AcaBot/.planning/phases/3a-scheduler/3a-VERIFICATION.md) | `SCHED-01..08` | frontmatter `status: passed` + requirements table completeness |

## Wave 0 Requirements

这些基础条件现在都满足了:

- `3a-01-SUMMARY.md` 和 `3a-02-SUMMARY.md` 已存在
- `3a-VERIFICATION.md` 已存在且 `status: passed`
- `tests/test_scheduler_integration.py` 已改成当前 `RuntimeApp` 构造路径可用的 fake pipeline/outbox

## Automated Validation Set

```bash
PYTHONPATH=src uv run pytest -q tests/test_scheduler.py
```

Expected and recorded result: `21 passed in 7.15s`

```bash
PYTHONPATH=src uv run pytest -q tests/test_scheduler_integration.py -k 'unload_plugin_cancels_scheduled_tasks or app_start_starts_scheduler or app_stop_order'
```

Expected and recorded result: `3 passed, 1 deselected in 5.97s`

## Manual-Only Verifications

All phase behaviors have automated verification.

## Audit Use

后续 audit 直接读取下面 4 个文件就够了:

- [3a-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3a-scheduler/3a-01-SUMMARY.md)
- [3a-02-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3a-scheduler/3a-02-SUMMARY.md)
- [3a-VERIFICATION.md](/home/acacia/AcaBot/.planning/phases/3a-scheduler/3a-VERIFICATION.md)
- [3a-VALIDATION.md](/home/acacia/AcaBot/.planning/phases/3a-scheduler/3a-VALIDATION.md)
