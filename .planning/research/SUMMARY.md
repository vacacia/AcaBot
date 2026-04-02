# Project Research Summary

**Project:** AcaBot v2 Runtime Infrastructure Hardening
**Domain:** Agentic chatbot runtime (plugin system, messaging, scheduling, observability, vector DB integrity)
**Researched:** 2026-04-02
**Confidence:** HIGH

## Executive Summary

AcaBot is a Python 3.11+ asyncio chatbot runtime with an LLM agent pipeline at its core. This milestone hardens six infrastructure dimensions: plugin management (replacing a 972-line monolith with a Kubernetes-style reconciler), unified message/action tooling (enabling the agent to reply, react, quote, and send cross-session), a lightweight asyncio task scheduler, structured logging, LanceDB data integrity, and removal of the defunct Reference Backend. The guiding principle across all areas is **minimize new dependencies** — the runtime already has a working pipeline, so stdlib and existing-dep solutions are strongly preferred over new frameworks.

The recommended approach centers on a desired-state reconciler pattern for plugins (Package/Spec/Status with a pure-function reconciler and dumb executor host), a single unified `message` LLM tool backed by platform-agnostic actions flowing through the existing Outbox, a custom asyncio scheduler (~150-200 lines) using `croniter` for cron parsing, `structlog` layered on top of existing stdlib logging, and application-level `asyncio.Lock` plus periodic backup for LanceDB safety. Only two new dependencies are needed: `structlog` and `croniter`.

The primary risks are: plugin reconciler state desync (Status drifting from Spec without periodic re-sync), phantom tool registrations surviving plugin reload, LanceDB concurrent write corruption (no lock currently exists), and the message tool schema overwhelming the LLM if made too complex. All are addressable with specific design patterns identified in the research.

## Key Findings

### Recommended Stack

See [STACK.md](STACK.md) for full details.

**New dependencies (only two):**
- **`structlog` (>= 25.1.0):** Structured logging with `contextvars` integration for async-safe context binding — wraps existing stdlib `logging`, enabling incremental migration
- **`croniter` (>= 3.0.0):** Cron expression parsing for the scheduler — pure Python, ~50KB, no transitive deps

**Existing dependencies leveraged (no additions):**
- **Playwright + Chromium:** Text-to-image rendering via `render_markdown_to_image()` — already in Docker image
- **LanceDB (pin to >= 0.28.0, < 1.0):** Bump floor for `merge_insert` improvements and `compact_files` API
- **markdown-it-py + Jinja2:** Markdown-to-HTML for image rendering — already present

**Explicitly rejected:** APScheduler (threading-based or unstable v4), Celery/Huey/dramatiq (require message broker), loguru (replaces stdlib entirely, not async-safe), external plugin frameworks (Pluggy, stevedore — overkill for ~10-20 plugins).

### Expected Features

See [FEATURES.md](FEATURES.md) for full analysis with prioritization matrix and competitor comparison.

**Must have (table stakes — P1):**
- Plugin identity (`plugin_id`), install/uninstall API, enable/disable toggle, error isolation, config persistence
- Unified message tool (reply, quote, mention, media) + cross-session messaging
- Scheduler with cron + one-shot + persistence + plugin-lifecycle-bound cleanup + graceful shutdown
- Tool call logging with structured fields, LLM token usage per run, error logging with run context
- LanceDB concurrent write protection, backup capability, graceful degradation on LTM failure
- Delete Reference Backend (dead code removal)

**Should have (differentiators — P2):**
- Plugin hot reload via reconciler unload/load cycle
- Text-to-image rendering (Playwright)
- Full run trace view in WebUI
- Schedule-triggered agent runs (proactive bot behavior)
- LanceDB auto-compaction

**Defer (v2+):**
- Plugin marketplace, dependency resolution, resource usage tracking
- Conversation replay/debug
- OpenTelemetry export
- Forward/合并转发 messages

### Architecture Approach

See [ARCHITECTURE.md](ARCHITECTURE.md) for full component designs and integration diagrams.

The architecture replaces the monolithic `plugin_manager.py` with six focused modules following a Reconciler + Host pattern, adds a Scheduler service with explicit lifecycle positioning (stops first on shutdown), enhances logging by enriching the existing `LogEntry` with a `context: dict` field, and hardens LTM storage with write serialization — all wired through the existing `build_runtime_components()` DI point and `RuntimeApp` lifecycle.

**Major components:**
1. **Plugin Reconciler + Host** — Six modules (protocol, package, spec, status, reconciler, host) replace `plugin_manager.py`. Reconciler is the brain (desired vs. actual state), Host is the hands (load/unload/hooks). Three data sources on disk: Package (developer), Spec (operator), Status (reconciler output).
2. **Unified Message Tool** — `builtin_tools/message.py` translates LLM intent to `Action` objects appended to `RunContext.planned_actions`, dispatched by Outbox. Never bypasses Outbox (preserves persistence, LTM notify, plugin hooks).
3. **Scheduler** — Pure asyncio service (~150-200 lines) with task registry keyed by `task_id` and `owner`. Supports cron/interval/one-shot. Integrates with plugin unload via `unregister_by_owner()`.
4. **Logging Enhancement** — No new module. `LogEntry` gains `context: dict`; structured fields emitted via `logging.info(..., extra={})` at six key sites (tool exec, LTM, agent, plugin lifecycle, outbox).
5. **LTM Data Safety** — Internal to `storage.py`: `asyncio.Lock` for write serialization, validation before write, periodic backup via scheduler, startup integrity check.
6. **Reference Backend Removal** — Two-phase: null-out (zero behavioral change) then delete dead code across 14+ files.

### Critical Pitfalls

See [PITFALLS.md](PITFALLS.md) for all 12 pitfalls with recovery strategies.

1. **Plugin reconciler state desync** — Status drifts from Spec after transient failures if reconciler only reacts to Spec changes. *Avoid:* periodic re-sync timer (60s), rich Status with `last_error`/`retry_count`/`last_reconciled_at`.
2. **Phantom tool registrations after reload** — Old plugin tools persist in ToolBroker as zombies. *Avoid:* `ToolBroker.unregister_by_owner(plugin_id)` called atomically before re-registration; track ownership.
3. **LanceDB concurrent write corruption** — No write lock exists; concurrent rewrite operations lose data. *Avoid:* `asyncio.Lock` per table (10-line fix, must be done first before any other LTM work).
4. **Message tool overwhelming the LLM** — Complex union-typed schema causes hallucinated params and wrong action selection. *Avoid:* 2-3 tools max with <5 params each; test with real LLM calls before shipping.
5. **Scheduler task leaks on shutdown** — Orphaned tasks hold refs to torn-down subsystems. *Avoid:* tracked task set with `cancel()` + `gather()`, scheduler stops first in shutdown order.

## Implications for Roadmap

Based on research, the build order and dependency analysis suggest the following phase structure:

### Phase 1: Reference Backend Removal
**Rationale:** Pure deletion that reduces surface area and noise before the larger refactors. No dependencies on other phases. The plugin refactor deletes `ReferenceToolsPlugin` anyway, so removing the reference subsystem first avoids carrying dead code through subsequent changes.
**Delivers:** Clean codebase with ~14 files simplified/removed, no runtime behavior change.
**Addresses:** "Delete Reference Backend" (P1 feature), dead code cleanup.
**Avoids:** Dangling imports pitfall (#11), BackendBridge breakage pitfall (#12) — must audit bridge plugin usage first.

### Phase 2: Plugin Reconciler
**Rationale:** Foundation for everything else. Scheduler wiring into `PluginRuntimeHost.unload_plugin()` needs the new Host. Message tool goes through cleaned-up ToolBroker path. This is the largest change — do while codebase is cleanest.
**Delivers:** Six new modules replacing `plugin_manager.py`; declarative plugin management via API/WebUI; plugin identity, enable/disable, error isolation, config persistence.
**Addresses:** All P1 plugin features.
**Avoids:** State desync pitfall (#1), phantom registration pitfall (#2) — by designing Status schema and tool ownership tracking from the start.

### Phase 3a/3b/3c: Scheduler, LTM Safety, Logging (parallelizable)
**Rationale:** These three touch non-overlapping code and can be built concurrently. All depend on Phase 2 (scheduler needs Host for plugin lifecycle integration, logging needs plugin_id context, LTM safety is independent but benefits from scheduler for periodic backup/compaction).
**Delivers:**
- *3a — Scheduler:* Cron + interval + one-shot task registration, plugin-lifecycle-bound cleanup, graceful shutdown. Uses `croniter`.
- *3b — LTM Safety:* `asyncio.Lock` write serialization, backup capability, startup integrity check, graceful degradation.
- *3c — Logging:* Structured `LogEntry.context`, enriched emit sites, WebUI rendering of structured fields. Uses `structlog`.
**Addresses:** Scheduler P1 features, LanceDB safety P1 features, observability P1 features.
**Avoids:** Task leak pitfall (#5), timer drift pitfall (#6), write corruption pitfall (#7), backup inconsistency pitfall (#8), log spam pitfall (#9).

### Phase 4: Unified Message Tool
**Rationale:** Most design-uncertain component (per project progress notes). Benefits from stable plugin system (tool registration), scheduler (cross-session notifications), and logging (tool call observability). Needs real LLM testing for schema validation.
**Delivers:** Unified message tool (reply, quote, react, recall), cross-session messaging, text-to-image rendering via Playwright.
**Addresses:** Message tool P1 features, text-to-image P2 feature.
**Avoids:** LLM confusion pitfall (#3), platform abstraction leak pitfall (#4) — by defining GatewayProtocol extension first and testing with real LLM calls.

### Phase Ordering Rationale

- **Phase 1 before 2:** Reference removal eliminates noise from the plugin refactor; `ReferenceToolsPlugin` deletion is cleaner as a standalone step.
- **Phase 2 before 3:** Scheduler needs `PluginRuntimeHost` for lifecycle-bound task cleanup. Logging needs `plugin_id` propagation from the new plugin system.
- **Phase 3 parallelizable:** Scheduler (`scheduler.py`), LTM safety (`storage.py`), and logging (`log_buffer.py` + emit sites) touch entirely different modules.
- **Phase 4 last:** Message tool is the most design-uncertain and benefits from all prior infrastructure. Cross-session messaging requires scheduler for notifications. Text-to-image requires stable Outbox integration.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (Plugin Reconciler):** Complex migration from 972-line monolith. Need detailed audit of current `plugin_manager.py` load ordering and implicit dependencies between plugins. `BackendBridgeToolPlugin` transition needs explicit verification.
- **Phase 4 (Message Tool):** Schema design requires LLM testing validation. The "unified vs. split" tool decision (1 tool vs. 2-3 tools) must be resolved with empirical testing. GatewayProtocol extension design needs OneBot v11 API review for reaction/recall support.

Phases with standard patterns (lighter planning):
- **Phase 1 (Reference Removal):** Straightforward deletion with grep verification. Well-defined dependency map already documented.
- **Phase 3a (Scheduler):** Standard asyncio pattern, ~150-200 lines. `croniter` API is simple.
- **Phase 3b (LTM Safety):** Internal to one file (`storage.py`). `asyncio.Lock` is a known pattern.
- **Phase 3c (Logging):** Additive changes to existing infrastructure. `structlog` has excellent stdlib integration docs.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All recommendations verified against current releases and existing codebase constraints. Only 2 new deps. |
| Features | HIGH | Based on mature ecosystem analysis (NoneBot2, Koishi, LangSmith) and existing codebase review. Clear P1/P2/P3 prioritization. |
| Architecture | HIGH | Full source analysis + accepted design doc (`docs/29-plugin-control-plane.md`). Integration points well-mapped. |
| Pitfalls | HIGH | Grounded in codebase analysis and known failure patterns for asyncio/LanceDB/plugin systems. Recovery strategies defined. |

**Overall confidence:** HIGH

### Gaps to Address

- **Message tool schema complexity vs. LLM usability:** Research recommends 2-3 tools with <5 params each, but the exact split (reply vs. send_message vs. react) needs empirical LLM testing during Phase 4 planning. No substitute for testing with actual model calls.
- **Plugin load ordering during migration:** The current `plugin_manager.py` has implicit ordering dependencies. The new reconciler design assumes explicit dependency declaration, but the migration path for existing plugins needs per-plugin audit.
- **LanceDB `run_in_executor` performance:** Research recommends running sync LanceDB calls in executor threads, but actual latency impact under AcaBot's workload is untested. Benchmark during Phase 3b.
- **Scheduler persistence across restarts:** Research notes the need for persistent job store (SQLite) but the exact schema and migration strategy need design during Phase 3a planning.

## Sources

### Primary (HIGH confidence)
- AcaBot codebase: `plugin_manager.py`, `storage.py`, `napcat.py`, `app.py`, `bootstrap/`, `control/`
- `docs/29-plugin-control-plane.md` — accepted Plugin Reconciler design
- `.planning/PROJECT.md`, `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/CONCERNS.md`
- [LanceDB PyPI](https://pypi.org/project/lancedb/) — version 0.30.1 confirmed, concurrent access patterns
- [Playwright Python PyPI](https://pypi.org/project/playwright/) — version 1.58.0 confirmed
- [structlog docs](https://www.structlog.org/) — stdlib integration patterns
- [croniter PyPI](https://pypi.org/project/croniter/) — cron parsing library

### Secondary (MEDIUM confidence)
- NoneBot2 (`nonebot.dev`) — plugin loading, `require()`, marketplace patterns
- Koishi (`koishi.chat`) — `ctx.plugin()`, `ctx.cron()`, universal message elements
- APScheduler docs — asyncio scheduler patterns (used as anti-reference: too heavy for this use case)
- LangSmith docs — tracing and token tracking patterns

### Tertiary (LOW confidence)
- APScheduler 4.x stability assessment — still pre-release, API may stabilize differently than expected
- LanceDB `>= 1.0` breaking changes — speculative, based on Lance format evolution patterns

---
*Research completed: 2026-04-02*
*Ready for roadmap: yes*
