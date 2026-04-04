---
phase: 3b-ltm-data-safety
validated: 2026-04-04T17:13:00Z
nyquist_compliant: true
status: ready-for-audit
scope: phase
---

# Phase 3b Validation

## Validation Architecture

Phase 3b 的验证分 3 层:

1. Wave summary 层
   - `3b-01-SUMMARY.md` 固定 `LTM-01`、`LTM-03`、`LTM-04`
   - `3b-02-SUMMARY.md` 固定 `LTM-02`
2. Current executable checks 层
   - validation/write-lock 命令
   - backup 命令
   - degradation/runtime integration 命令
3. Broad recheck 层
   - 7 文件、82 个测试的当前代码复跑

## Per-Task Verification Map

| Task | Output | Requirement Coverage | Validation Method |
| --- | --- | --- | --- |
| Task 1 | [3b-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3b-ltm-data-safety/3b-01-SUMMARY.md) | `LTM-01`, `LTM-03`, `LTM-04` | `tests/runtime/test_ltm_validation.py` + `tests/runtime/test_ltm_write_lock.py` + `tests/runtime/test_ltm_data_safety.py` + `tests/runtime/test_bootstrap.py` + `tests/runtime/test_app.py` |
| Task 2 | [3b-02-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3b-ltm-data-safety/3b-02-SUMMARY.md) | `LTM-02` | `tests/runtime/test_ltm_backup.py` |
| Task 3 | [3b-VERIFICATION.md](/home/acacia/AcaBot/.planning/phases/3b-ltm-data-safety/3b-VERIFICATION.md) | `LTM-01..04` | frontmatter `status: passed` + broad recheck `82 passed` |

## Wave 0 Requirements

这些条件现在都满足了:

- `tests/runtime/test_ltm_validation.py` 已存在
- missing manifest、missing required columns、table read failure 都有直接自动化证明
- `3b-VERIFICATION.md` 已存在且 `status: passed`

## Automated Validation Set

```bash
PYTHONPATH=src uv run pytest -q tests/runtime/test_ltm_validation.py tests/runtime/test_ltm_write_lock.py
```

Expected and recorded result: `7 passed in 4.86s`

```bash
PYTHONPATH=src uv run pytest -q tests/runtime/test_ltm_backup.py
```

Expected and recorded result: `6 passed in 9.03s`

```bash
PYTHONPATH=src uv run pytest -q tests/runtime/test_ltm_data_safety.py tests/runtime/test_bootstrap.py tests/runtime/test_app.py
```

Expected and recorded result: `59 passed in 4.80s`

## Manual-Only Verifications

All phase behaviors have automated verification.

## Audit Use

后续 audit 直接读取下面 4 个文件就够了:

- [3b-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3b-ltm-data-safety/3b-01-SUMMARY.md)
- [3b-02-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3b-ltm-data-safety/3b-02-SUMMARY.md)
- [3b-VERIFICATION.md](/home/acacia/AcaBot/.planning/phases/3b-ltm-data-safety/3b-VERIFICATION.md)
- [3b-VALIDATION.md](/home/acacia/AcaBot/.planning/phases/3b-ltm-data-safety/3b-VALIDATION.md)
