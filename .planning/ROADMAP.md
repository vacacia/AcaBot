# Roadmap: AcaBot v2 Runtime Infrastructure

**Created:** 2026-04-02
**Granularity:** standard (6 phases, 3 parallelizable)
**Parallelization:** enabled (Phases 3a/3b/3c run concurrently)

## Phase Overview

```
Phase 1: Reference Backend Removal          [3 reqs]   ──►
Phase 2: Plugin Reconciler                   [13 reqs]  ──►
Phase 3a: Scheduler                          [8 reqs]   ──┐
Phase 3b: LTM Data Safety                   [4 reqs]   ──┼─► (parallel)
Phase 3c: Logging & Observability            [6 reqs]   ──┘
Phase 4: Unified Message Tool + Playwright   [13 reqs]  ──►
                                              ─────────
                                              47 total
```

---

## Phase 1: Reference Backend Removal

**Goal:** Delete the defunct Reference Backend subsystem, leaving zero dead imports and no runtime behavior change. Cleans the codebase before larger refactors.

**Requirements:**
- REF-01: Reference Backend subsystem completely deleted, no residual imports
- REF-02: BackendBridgeToolPlugin decoupled from Reference Backend, transition-period usable
- REF-03: config.yaml reference-related config items cleaned or marked deprecated

**Success Criteria:**
1. `grep -r "reference" src/` returns zero hits on Reference Backend modules/imports (dead code gone)
2. Bot starts successfully and completes a full request-response cycle (no runtime regression)
3. BackendBridgeToolPlugin loads and its tools execute without error in a smoke test
4. No config.yaml keys reference the deleted subsystem (or are explicitly marked `deprecated`)

**Dependencies:** None (standalone, reduces noise for subsequent phases)
**Research flag:** Light — straightforward deletion with grep verification

---

## Phase 2: Plugin Reconciler

**Goal:** Replace the 972-line `plugin_manager.py` monolith with six focused modules implementing a desired-state reconciler pattern. Deliver declarative plugin management via API and WebUI.

**Requirements:**
- PLUG-01: Plugin identity migrated from import path to plugin_id
- PLUG-02: PluginPackage scans extensions/plugins/ for plugin.yaml manifests
- PLUG-03: PluginSpec (enable/disable + config override) persisted to runtime_config/plugins/
- PLUG-04: PluginStatus (phase/error/tools/hooks) persisted to runtime_data/plugins/
- PLUG-05: PluginReconciler implements desired-state convergence (reconcile_all + reconcile_one)
- PLUG-06: PluginRuntimeHost executes load/unload/teardown/run_hooks
- PLUG-07: Single-plugin exception does not affect runtime (error isolation)
- PLUG-08: Old plugin_manager.py (972 lines) fully replaced and deleted
- PLUG-09: Legacy plugins (OpsControl/NapCatTools/ReferenceTools) deleted
- PLUG-10: REST API 5 new endpoints replace old 4 endpoints
- PLUG-11: WebUI plugin management page (list, status badges, enable/disable, schema-driven config form)
- PLUG-12: Bootstrap integration (construct catalog/spec_store/status_store/host/reconciler)
- PLUG-13: Pipeline integration (plugin_manager.run_hooks -> host.run_hooks)

**Success Criteria:**
1. A sample plugin with `plugin.yaml` is discovered, enabled via API, and its tools appear in ToolBroker
2. Disabling a plugin via WebUI removes its tools from ToolBroker and sets Status.phase to `disabled`
3. A plugin that raises during load is caught — Status shows `error` phase with `last_error`, other plugins remain functional
4. Old `plugin_manager.py` file no longer exists; `git log` confirms deletion
5. Full bot pipeline (gateway -> agent -> tool call -> reply) works with new plugin system

**Dependencies:** Phase 1 (Reference Backend gone, so ReferenceToolsPlugin deletion is clean)
**Research flag:** Heavy — need detailed audit of current plugin_manager.py load ordering and BackendBridgeToolPlugin transition

---

## Phase 3a: Scheduler

**Goal:** Deliver a lightweight asyncio scheduler supporting cron, interval, and one-shot tasks with persistence, plugin lifecycle binding, and graceful shutdown.

**Requirements:**
- SCHED-01: Cron expression scheduling (croniter-based parsing)
- SCHED-02: Interval (fixed-period) scheduling
- SCHED-03: One-shot (single delayed execution) tasks
- SCHED-04: Task persistence, recovery after runtime restart
- SCHED-05: Task cancellation by task_id
- SCHED-06: Graceful shutdown (cancel all + gather, scheduler stops first)
- SCHED-07: Plugin lifecycle binding (unload triggers unregister_by_owner)
- SCHED-08: RuntimeApp lifecycle integration (start after app start, stop first on shutdown)

**Success Criteria:**
1. A cron-scheduled task fires at the expected time (verified by log output within 1-minute tolerance)
2. After runtime restart, previously registered persistent tasks resume without re-registration
3. Unloading a plugin automatically cancels all tasks owned by that plugin (no orphaned tasks)
4. During shutdown, scheduler stops before other subsystems; no `Task was destroyed` warnings in logs

**Dependencies:** Phase 2 (needs PluginRuntimeHost for lifecycle-bound cleanup via unregister_by_owner)
**Parallel with:** Phase 3b, Phase 3c

---

## Phase 3b: LTM Data Safety

**Goal:** Protect LanceDB data integrity with write serialization, backup capability, startup validation, and graceful degradation.

**Requirements:**
- LTM-01: asyncio.Lock write serialization (prevent concurrent write corruption)
- LTM-02: Periodic backup capability (triggered via scheduler)
- LTM-03: Startup integrity check (detect corrupted tables / missing manifest)
- LTM-04: Graceful degradation on LTM failure (don't block pipeline, log error and continue)

**Success Criteria:**
1. Two concurrent LTM write operations serialize correctly (no data loss, verified by reading back both writes)
2. A scheduled backup produces a restorable snapshot in the configured backup directory
3. On startup with a corrupted LanceDB table, bot logs a warning and continues operating with LTM disabled
4. A mid-pipeline LTM failure (simulated) does not prevent the agent from completing its response

**Dependencies:** Phase 2 (scheduler integration for periodic backup), but LTM-01/03/04 can start immediately
**Parallel with:** Phase 3a, Phase 3c

---

## Phase 3c: Logging & Observability

**Goal:** Enrich logging with structured fields at key emit sites, integrate structlog for async-safe context propagation, and render structured logs in WebUI.

**Requirements:**
- LOG-01: Tool call logs include structured fields (tool_name, duration, result_summary)
- LOG-02: LLM token usage per run recorded (input/output/total tokens, model, cost)
- LOG-03: Error logs auto-associate run context (run_id, thread_id, agent_id)
- LOG-04: WebUI log viewer displays structured fields (not just plain text)
- LOG-05: LTM extraction/query process logs visible
- LOG-06: structlog integration (wrapping stdlib logging, contextvars propagation)

**Success Criteria:**
1. After a tool call, the log entry contains `tool_name`, `duration_ms`, and `result_summary` as queryable fields
2. After an agent run, a log entry shows token breakdown (input/output/total) and model name
3. WebUI log viewer renders structured fields as key-value pairs (not raw JSON strings)
4. LTM extraction events appear in logs with timing and record count

**Dependencies:** Phase 2 (needs plugin_id context for structured logging)
**Parallel with:** Phase 3a, Phase 3b

---

## Phase 4: Unified Message Tool + Playwright

**Goal:** Give the agent complete messaging capabilities (reply, quote, react, recall, media, cross-session) via a unified tool backed by platform-agnostic actions flowing through Outbox, plus text-to-image rendering.

**Requirements:**
- MSG-01: Text reply (basic send text, preserve existing behavior)
- MSG-02: Quote reply (reply_to specifies quoted message)
- MSG-03: @mention (specify user ID)
- MSG-04: Emoji reaction (add reaction to message)
- MSG-05: Message recall (recall specified message)
- MSG-06: Media/attachment sending (image, file path)
- MSG-07: Tool layer expresses intent only, mapped to Action -> Outbox -> Gateway
- MSG-08: Text-to-image rendering (Playwright render_markdown_to_image)
- MSG-09: Cross-session messaging (target parameter specifies destination session)
- MSG-10: Tool schema / field design finalized during discuss phase
- PW-01: render_markdown_to_image() utility function in Outbox layer
- PW-02: Singleton browser instance management (create on start, destroy on close)
- PW-03: markdown-it-py -> HTML -> Playwright screenshot pipeline

**Success Criteria:**
1. Agent successfully sends a quoted reply with @mention in a real conversation (verified in IM client)
2. Agent sends an image generated from markdown via text-to-image rendering
3. Cross-session message delivery works (agent sends to a different group/user than the triggering conversation)
4. All message actions flow through Outbox (no direct Gateway calls from tool layer, verified by code review)
5. Playwright browser instance starts once and is reused across multiple render calls (no process leak)

**Dependencies:** Phases 2 + 3a + 3c (stable plugin system, scheduler for cross-session notifications, structured logging for tool call observability)
**Research flag:** Heavy — message tool schema requires empirical LLM testing; GatewayProtocol extension needs OneBot v11 API review
**Plans:** 4 plans

Plans:
- [x] `04-01-PLAN.md` — Add the unified `message` builtin tool surface, lock the schema, and wire NapCat reaction payloads
- [x] `04-02-PLAN.md` — Materialize `SEND_MESSAGE_INTENT`, fix cross-session persistence semantics, and suppress duplicate default replies
- [x] `04-03-PLAN.md` — Add the render module, project dependencies, internal artifact helpers, and Playwright backend tests
- [ ] `04-04-PLAN.md` — Wire the default render service into bootstrap, Outbox, app shutdown, and sync docs/regression tests

---

## Coverage Validation

| Requirement | Phase | Count |
|-------------|-------|-------|
| REF-01..03 | 1 | 3 |
| PLUG-01..13 | 2 | 13 |
| SCHED-01..08 | 3a | 8 |
| LTM-01..04 | 3b | 4 |
| LOG-01..06 | 3c | 6 |
| MSG-01..10 | 4 | 10 |
| PW-01..03 | 4 | 3 |
| **Total** | | **47** |

**Coverage: 47/47 v1 requirements mapped (100%)**

---
*Created: 2026-04-02*
