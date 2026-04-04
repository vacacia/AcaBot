---
phase: 06
slug: runtime-infra-artifact-backfill
status: passed
validated: 2026-04-04T17:20:00Z
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-04
---

# Phase 06 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `pytest 9.0.2` + `pytest-asyncio` auto mode |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `PYTHONPATH=src uv run pytest -q tests/test_scheduler.py tests/runtime/test_ltm_validation.py tests/runtime/test_ltm_write_lock.py tests/test_structured_logging.py tests/runtime/test_tool_broker.py tests/test_agent.py tests/runtime/test_pipeline_runtime.py tests/runtime/test_long_term_memory_source.py` |
| **Full suite command** | `PYTHONPATH=src uv run pytest --ignore=tests/runtime/backend/test_pi_adapter.py` |
| **Estimated runtime** | ~30 seconds for the quick mixed suite on this machine |

## Sampling Rate

- After every plan task, run the smallest relevant command from the map below.
- After every Phase 06 plan close-out, rerun the phase-specific command set and update the original phase artifacts first.
- Before milestone audit refresh, check `06-VERIFICATION.md`, `3a/3b/3c` verification files, and top-level traceability together.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | `SCHED-01..06` | unit | `PYTHONPATH=src uv run pytest -q tests/test_scheduler.py` | ✅ | ✅ green |
| 06-01-02 | 01 | 1 | `SCHED-07..08` | integration | `PYTHONPATH=src uv run pytest -q tests/test_scheduler_integration.py -k 'unload_plugin_cancels_scheduled_tasks or app_start_starts_scheduler or app_stop_order'` | ✅ | ✅ green |
| 06-02-01 | 02 | 1 | `LTM-01`, `LTM-03` | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_ltm_validation.py tests/runtime/test_ltm_write_lock.py` | ✅ | ✅ green |
| 06-02-02 | 02 | 1 | `LTM-02` | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_ltm_backup.py` | ✅ | ✅ green |
| 06-02-03 | 02 | 1 | `LTM-04` | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_ltm_data_safety.py tests/runtime/test_bootstrap.py tests/runtime/test_app.py` | ✅ | ✅ green |
| 06-03-01 | 03 | 1 | `LOG-01`, `LOG-03`, `LOG-06` | unit / integration | `PYTHONPATH=src uv run pytest -q tests/test_structured_logging.py tests/runtime/test_tool_broker.py` | ✅ | ✅ green |
| 06-03-02 | 03 | 1 | `LOG-02` | unit / integration | `PYTHONPATH=src uv run pytest -q tests/test_agent.py tests/runtime/test_pipeline_runtime.py -k 'structured_usage_log or token_usage_and_logs_it'` | ✅ | ✅ green |
| 06-03-03 | 03 | 1 | `LOG-04`, `LOG-05` | browser / integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_webui_api.py::test_logs_page_renders_structured_extra_fields tests/runtime/test_long_term_memory_source.py::test_extractor_client_emits_structured_log tests/runtime/test_long_term_memory_source.py::test_query_planner_client_emits_structured_log tests/runtime/test_long_term_memory_source.py::test_embedding_client_emits_structured_log tests/runtime/test_long_term_memory_source.py::test_long_term_memory_source_emits_structured_logs` | ✅ | ✅ green |
| 06-04-01 | 04 | 2 | `SCHED-01..08`, `LTM-01..04`, `LOG-01..06` | documentation / audit | `test -f .planning/phases/06-runtime-infra-artifact-backfill/06-VERIFICATION.md && rg -n '^status: passed$' .planning/phases/06-runtime-infra-artifact-backfill/06-VERIFICATION.md && rg -n '^status: passed$|^wave_0_complete: true$|^nyquist_compliant: true$' .planning/phases/06-runtime-infra-artifact-backfill/06-VALIDATION.md` | ✅ | ✅ green |

## Wave 0 Requirements

Wave 0 已清空:

- `SCHED-08` 的 stale RuntimeApp fixture 已修
- `LTM-03` 的 missing manifest / corruption 负向 proof 已补
- `LOG-02` 的 `cost_usd` 已贯通到日志和 run metadata
- `LOG-04` 的 `/logs` extra chip browser proof 已补
- `LOG-05` 的 extraction-side structured log proof 已补

## Manual-Only Verifications

Phase 06 自己没有剩余 manual-only gate。

## Validation Sign-Off

- [x] All tasks have automated verification
- [x] Sampling continuity is preserved
- [x] Wave 0 gaps are closed
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** complete
