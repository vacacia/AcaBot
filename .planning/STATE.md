# Project State

**Current Phase:** 2 — Plugin Reconciler
**Phase Status:** Executed ✅
**Updated:** 2026-04-03

## Phase Progress

| Phase | Name | Status | Requirements |
|-------|------|--------|--------------|
| 1 | Reference Backend Removal | **Executed ✅** | REF-01, REF-02, REF-03 |
| 2 | Plugin Reconciler | **Executed ✅** | PLUG-01..13 |
| 3a | Scheduler | Ready | SCHED-01..08 |
| 3b | LTM Data Safety | Ready | LTM-01..04 |
| 3c | Logging & Observability | Ready | LOG-01..06 |
| 4 | Unified Message Tool + Playwright | Blocked by Phase 3 | MSG-01..10, PW-01..03 |

## Active Plans

| Plan | Wave | Status | Requirements |
|------|------|--------|--------------|
| PLAN-01-plugin-foundation | 1 | **Executed ✅** | PLUG-01..07 |
| PLAN-02-integration-deletion | 2 | **Executed ✅** | PLUG-08, 09, 10, 12, 13 |
| PLAN-03-webui | 3 | **Executed ✅** | PLUG-11 |

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

## Commits

| Commit | Description |
|--------|-------------|
| d09413c | refactor: delete reference backend modules and tests (Phase 1, PLAN-01) |
| (wave 2) | refactor: remove all reference backend integration points (Phase 1, PLAN-02) |
| 2b05cd3 | chore: remove unused ThreadState import from app.py |
| ba16ed1 | feat: add plugin reconciler foundation modules (Phase 2, Wave 1) |
| 1dfe340 | refactor: wire new plugin system and delete legacy code (Phase 2, Wave 2) |
| b454029 | feat: rewrite plugin management WebUI page (Phase 2, Wave 3) |

## Decisions Log

- D-01: No config migration — treat old config as non-existent
- D-02: ADR reference_backend field removed (Phase 1 already deleted the subsystem)
- D-03: Inline state changes + toast notifications for plugin operations
- D-04: Plugin load failures shown as badge; full error in modal on click
- D-05: Single reconcile API call with frontend transition state
- D-06: BackendBridgeToolPlugin confirmed to have no reference_backend dependency — kept as-is
- D-06: Sample plugin `sample_tool` ships as developer template with config_schema

## Blockers

None.

---
*Last updated: 2026-04-03*
