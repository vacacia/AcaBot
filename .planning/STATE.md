---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 04
status: in_progress
last_updated: "2026-04-03T17:57:22Z"
progress:
  total_phases: 6
  completed_phases: 5
  total_plans: 4
  completed_plans: 1
---

# Project State

**Current Phase:** 04
**Phase Status:** In Progress
**Updated:** 2026-04-04

## Phase Progress

| Phase | Name | Status | Requirements |
|-------|------|--------|--------------|
| 1 | Reference Backend Removal | **Executed ✅** | REF-01, REF-02, REF-03 |
| 2 | Plugin Reconciler | **Executed ✅** | PLUG-01..13 |
| 3a | Scheduler | **Executed ✅** | SCHED-01..08 |
| 3b | LTM Data Safety | **Executed ✅** | LTM-01..04 |
| 3c | Logging & Observability | **Executed ✅** | LOG-01..06 |
| 4 | Unified Message Tool + Playwright | In Progress | MSG-01..10, PW-01..03 |

## Active Plans

| Plan | Wave | Status | Requirements |
|------|------|--------|--------------|
| 04-01 | 1 | **Executed ✅** | MSG-04, MSG-05, MSG-07, MSG-10 |
| 04-02 | 2 | Ready | MSG-01, MSG-02, MSG-03, MSG-06, MSG-07, MSG-09 |
| 04-03 | 3 | Ready | MSG-08, PW-01, PW-02, PW-03 |
| 04-04 | 4 | Ready | MSG-05, MSG-08, PW-01, PW-02, PW-03 |

## Verification Results

### Phase 1

- ✅ Zero grep hits for all reference backend symbols
- ✅ All modified Python files pass syntax check
- ✅ BackendBridgeToolPlugin smoke test passes
- ✅ 548 total tests pass (7 pre-existing backend failures)

### Phase 2

- ✅ Zero `from.*plugin_manager import` in `src/acabot/`
- ✅ Zero `RuntimePluginManager` references in `src/acabot/` (only docstring mention in plugin_protocol.py)
- ✅ `plugin_manager.py` deleted (959 lines removed)
- ✅ `ops_control.py`, `napcat_tools.py` deleted
- ✅ All new symbols importable: `PluginReconciler`, `PluginRuntimeHost`, `PackageCatalog`, `SpecStore`, `StatusStore`
- ✅ 6 new modules created: plugin_protocol, plugin_package, plugin_spec, plugin_status, plugin_runtime_host, plugin_reconciler
- ✅ Sample plugin at `extensions/plugins/sample_tool/`
- ✅ 5 new REST API endpoints replace 4 old ones
- ✅ WebUI PluginsView.vue fully rewritten with schema-driven config form
- ✅ BackendBridgeToolPlugin preserved as transitional code with direct tool registration
- ✅ 557 tests pass, 9 pre-existing backend failures (missing `pi` binary), 26 skipped
- ✅ Vite build succeeds

### Phase 4

- ✅ `tests/runtime/test_message_tool.py` 全绿, 锁定 `message` tool schema、user_actions-only 行为、严格 reaction 失败语义和 D-08 文案
- ✅ `tests/runtime/test_builtin_tools.py` 与 `tests/test_gateway.py` 全绿, `builtin:message` 注册链和 NapCat `set_msg_emoji_like` payload 已固定
- ✅ 总验证命令 `PYTHONPATH=src uv run pytest -q tests/runtime/test_message_tool.py tests/runtime/test_builtin_tools.py tests/test_gateway.py` 通过, 共 39 tests passed

## Commits

| Commit | Description |
|--------|-------------|
| d09413c | refactor: delete reference backend modules and tests (Phase 1, PLAN-01) |
| (wave 2) | refactor: remove all reference backend integration points (Phase 1, PLAN-02) |
| 2b05cd3 | chore: remove unused ThreadState import from app.py |
| ba16ed1 | feat: add plugin reconciler foundation modules (Phase 2, Wave 1) |
| 1dfe340 | refactor: wire new plugin system and delete legacy code (Phase 2, Wave 2) |
| b454029 | feat: rewrite plugin management WebUI page (Phase 2, Wave 3) |
| 413571d | test(04-01): add failing tests for unified message tool |
| 85f27dc | feat(04-01): implement unified message tool surface |
| 893b56c | test(04-01): add failing tests for message registration and reaction payload |
| 4231417 | feat(04-01): register message builtin and support reaction payloads |
| e25b106 | docs(04-01): sync unified message tool contracts |

## Decisions Log

- D-01: No config migration — treat old config as non-existent
- D-02: ADR reference_backend field removed (Phase 1 already deleted the subsystem)
- D-03: Inline state changes + toast notifications for plugin operations
- D-04: Plugin load failures shown as badge; full error in modal on click
- D-05: Single reconcile API call with frontend transition state
- D-06: BackendBridgeToolPlugin confirmed to have no reference_backend dependency — kept as-is
- D-06: Sample plugin `sample_tool` ships as developer template with config_schema
- D-07: Unified `message` tool keeps one model-facing name; only `send` becomes `SEND_MESSAGE_INTENT`
- D-08: NapCat reaction delivery maps to `set_msg_emoji_like(message_id, emoji_id)`; `recall` stays on `delete_msg`

## Blockers

None.

---
*Last updated: 2026-04-04*
