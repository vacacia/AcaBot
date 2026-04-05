---
phase: 11
slug: scheduler-tool-surface
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-05
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pytest.ini` or `pyproject.toml` (existing) |
| **Quick run command** | `pytest tests/test_scheduler.py tests/test_scheduler_tool_surface.py -x -q` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_scheduler.py tests/test_scheduler_tool_surface.py -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | SCHED-01 | unit | `pytest tests/test_scheduler_tool_surface.py -k "test_create" -x` | ✅ W0 | ✅ green |
| 11-01-02 | 01 | 1 | SCHED-01 | unit | `pytest tests/test_scheduler_tool_surface.py -k "test_create_cron" -x` | ✅ W0 | ✅ green |
| 11-01-03 | 01 | 1 | SCHED-01 | unit | `pytest tests/test_scheduler_tool_surface.py -k "test_create_interval" -x` | ✅ W0 | ✅ green |
| 11-01-04 | 01 | 1 | SCHED-01 | unit | `pytest tests/test_scheduler_tool_surface.py -k "test_create_one_shot" -x` | ✅ W0 | ✅ green |
| 11-02-01 | 01 | 1 | SCHED-02 | unit | `pytest tests/test_scheduler_tool_surface.py -k "test_list" -x` | ✅ W0 | ✅ green |
| 11-02-02 | 01 | 1 | SCHED-02 | unit | `pytest tests/test_scheduler_tool_surface.py -k "test_list_owner_filter" -x` | ✅ W0 | ✅ green |
| 11-03-01 | 01 | 1 | SCHED-03 | unit | `pytest tests/test_scheduler_tool_surface.py -k "test_cancel" -x` | ✅ W0 | ✅ green |
| 11-03-02 | 01 | 1 | SCHED-03 | unit | `pytest tests/test_scheduler_tool_surface.py -k "test_cancel_invalid" -x` | ✅ W0 | ✅ green |
| 11-04-01 | 02 | 1 | SCHED-01 (dispatcher) | unit | `pytest tests/test_scheduler_dispatcher.py -x` | ✅ W0 | ✅ green |
| 11-05-01 | 03 | 2 | HTTP API | unit | `pytest tests/test_scheduler_http_api.py -x` | ✅ W0 | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_scheduler_tool_surface.py` — BuiltinSchedulerToolSurface tests (create/list/cancel actions, owner filtering)
- [x] `tests/test_scheduler_dispatcher.py` — ScheduledMessageDispatcher tests (callback reconstruction)
- [x] `tests/test_scheduler_http_api.py` — HTTP API route tests (/api/scheduler/tasks GET/POST/DELETE)
- [x] `tests/conftest.py` — add `scheduler_dispatcher` fixture if needed

*Existing infrastructure: `tests/test_scheduler.py`, `tests/test_scheduler_integration.py` cover core scheduler behavior — no changes needed to those files for Phase 11.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Task fires and notification delivered via dispatcher | SCHED-01 | Requires real scheduler worker loop + time passage | 1. Create one-shot task with 5s delay; 2. Verify notification arrives within 10s; 3. Check DB `last_fire_at` updated |
| Persistence across restart | SCHED-01 (persist) | Requires process restart | 1. Create task with `persist=True`; 2. Kill/restart runtime; 3. Verify task still in `list` and fires |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** {pending / approved YYYY-MM-DD}
