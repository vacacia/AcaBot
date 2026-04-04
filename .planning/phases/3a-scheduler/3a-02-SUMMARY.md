---
phase: 3a-scheduler
plan: 02
subsystem: scheduler-integration
tags: [scheduler, runtime-app, plugin-lifecycle, artifact-backfill]
requires:
  - phase: 3a-scheduler
    provides: historical Phase 3 completion commit 2a202ac
provides:
  - plugin lifecycle binding evidence for scheduler-owned tasks
  - RuntimeApp lifecycle evidence for scheduler start/stop ordering
  - plan-level requirement coverage for SCHED-07..08
affects: [runtime-app, plugin-runtime-host, scheduler-tests, audit-traceability]
tech-stack:
  added: []
  patterns:
    - "When constructor wiring changes later, refresh the proof test instead of pretending the runtime regressed."
key-files:
  created:
    - .planning/phases/3a-scheduler/3a-02-SUMMARY.md
  modified:
    - src/acabot/runtime/app.py
    - src/acabot/runtime/plugin_runtime_host.py
    - src/acabot/runtime/bootstrap/__init__.py
    - src/acabot/runtime/bootstrap/components.py
    - tests/test_scheduler_integration.py
key-decisions:
  - "Scheduler stops before plugin teardown so unload cannot race with still-running scheduled tasks."
  - "Phase 06 refreshes only the stale test harness for RuntimeApp construction; it does not change scheduler production behavior."
patterns-established:
  - "Lifecycle proof belongs in focused integration tests, not in broad runtime smoke commands."
requirements-completed: [SCHED-07, SCHED-08]
duration: historical + backfill refresh
completed: 2026-04-04
---

# Phase 3a Plan 02 Summary

**Wave 2 把 scheduler 接到 plugin 和 RuntimeApp 生命周期里, Phase 06 再把这条证据链修到当前构造路径上**

## Accomplishments

- `2a202ac` 把 scheduler 注入 `PluginRuntimeHost`、`RuntimeApp`、bootstrap 组件树, 完成 `SCHED-07` 和 `SCHED-08`.
- 当前 `RuntimeApp` 会从 `pipeline.outbox` 推断 `render_service`, 所以旧的 `pipeline=None` 测试壳已经不成立.
- Phase 06 只补了 `tests/test_scheduler_integration.py` 的最小 fake pipeline/outbox, 让 start/stop proof 重新对齐当前代码.

## Verification Results

- `git show --stat --summary 2a202ac`
  - 结果: `src/acabot/runtime/app.py`、`src/acabot/runtime/bootstrap/__init__.py`、`tests/test_scheduler_integration.py` 在 Phase 3 完成交付里一起更新
- `PYTHONPATH=src uv run pytest -q tests/test_scheduler_integration.py -k 'unload_plugin_cancels_scheduled_tasks or app_start_starts_scheduler or app_stop_order'`
  - 结果: `3 passed, 1 deselected in 5.97s`

## Task Commits

1. Historical scheduler integration delivery
   - `2a202ac` — `feat: complete phase 3`
2. Phase 06 proof refresh
   - not committed yet in this backfill session when this summary was written

## Notes

- 这里修的是 `SCHED-08` 的测试入口, 不是 `RuntimeApp` 或 scheduler 的生产行为.
- `SCHED-07` 的 unload cleanup 继续由 `test_unload_plugin_cancels_scheduled_tasks` 直接证明.

## Self-Check: PASSED

- Found `src/acabot/runtime/app.py`
- Found `src/acabot/runtime/plugin_runtime_host.py`
- Found `tests/test_scheduler_integration.py`
- Found commit: `2a202ac`
