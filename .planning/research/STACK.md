# Technology Stack

**Project:** AcaBot v1.1
**Researched:** 2026-04-05
**Focus:** Scheduler tool exposure, WebUI improvements, group chat bug fix, LTM migration

---

## Executive Summary

This milestone is **zero new Python dependencies** and **zero new npm packages**. All four feature areas (scheduler tool, WebUI scheduler page, group chat filter bug, AstrBot migration) build on existing infrastructure that was validated in v1.0. The core finding: everything needed is already in `pyproject.toml` or `package.json` -- the work is integration, not library acquisition.

The only consideration is `croniter` vs `cronsim` (the previous STACK.md recommended migrating to `cronsim`). In practice, `croniter` is already deeply embedded in the scheduler (`scheduler.py` has 5 call sites) and the v1.0 scheduler infrastructure is tested and working. Migrating to `cronsim` now would be churn with no user-facing benefit. **Recommendation: keep `croniter` for v1.1, reassess if it breaks.**

---

## Feature 1: Model-Facing Scheduler Tool

### Recommended Stack

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `RuntimeScheduler` | existing | Task execution engine | Already in `src/acabot/runtime/scheduler/scheduler.py` -- full cron/interval/one-shot support |
| `ToolBroker` | existing | Tool registration/dispatch | `src/acabot/runtime/tool_broker/broker.py` -- unified tool registry |
| `SQLiteScheduledTaskStore` | existing | Task persistence | `src/acabot/runtime/scheduler/store.py` -- SQLite-backed |
| `croniter` | >= 2.0.0 (existing) | Cron expression parsing | Already in `pyproject.toml`, 5 call sites in scheduler |

### What to Build

A new `BuiltinSchedulerToolSurface` in `src/acabot/runtime/builtin_tools/scheduler.py` (~120 lines), following the exact pattern of `BuiltinMessageToolSurface`:

- Register as source `builtin:scheduler` with ToolBroker
- Single tool named `scheduler` with action parameter: `create | list | cancel`
- `create`: maps to `RuntimeScheduler.register()` with schedule_type + schedule_spec
- `list`: maps to `RuntimeScheduler.list_tasks()`
- `cancel`: maps to `RuntimeScheduler.cancel(task_id)`
- Session binding: pass `conversation_id` as `owner` metadata so tasks auto-cleanup when session is pruned

### Key Integration Points

- `ToolBroker.register_tool()` -- same path as message/computer/skills/sticky_notes tools
- `RuntimeScheduler.register()` -- already accepts `owner`, `metadata`, `persist` parameters
- `ToolExecutionContext` -- provides `target` (EventSource) for deriving `conversation_id`
- Control Plane HTTP API -- needs new endpoints under `/api/scheduler/*` for WebUI

### New HTTP API Endpoints (for both LLM and WebUI)

| Endpoint | Method | Maps To |
|----------|--------|---------|
| `/api/scheduler/tasks` | GET | `RuntimeScheduler.list_tasks()` |
| `/api/scheduler/tasks` | POST | `RuntimeScheduler.register()` |
| `/api/scheduler/tasks/{task_id}` | DELETE | `RuntimeScheduler.cancel(task_id)` |
| `/api/scheduler/tasks/{task_id}` | GET | Single task detail |

### What NOT to Do

| Avoid | Why | Do Instead |
|-------|-----|------------|
| Expose raw `RuntimeScheduler` to LLM | LLM should not know about heap entries, misfire policy internals | Thin tool surface that translates LLM intent to scheduler calls |
| Let LLM specify arbitrary callbacks | Security risk -- LLM could reference internal functions | Tool surface creates a fixed callback that sends a notification to the bound conversation |
| Separate tools for cron/interval/oneshot | Bloats tool schema; LLM picks wrong one | Single `scheduler` tool with `schedule_type` discriminator |

---

## Feature 2: WebUI Scheduler Management Page

### Recommended Stack

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Vue 3 | ^3.5.22 (existing) | UI framework | Already in `webui/package.json` |
| Vue Router | ^4.5.1 (existing) | Routing | Already in `webui/package.json` |
| Vite | ^7.1.7 (existing) | Build tool | Already in `webui/package.json` |
| Control Plane HTTP API | existing | Data source | `src/acabot/runtime/control/http_api.py` -- pattern already established |

### What to Build

1. **New view:** `webui/src/views/SchedulerView.vue` (~200 lines)
   - Table listing all scheduled tasks (owner, schedule type, next fire time, enabled status)
   - Create dialog (schedule type selector, cron/interval/oneshot input, optional name)
   - Cancel button per row
   - Auto-refresh via polling (same pattern as LogsView)

2. **Sidebar entry:** Add "定时任务" link to `AppSidebar.vue` nav section (under "配置" group)

3. **Backend endpoints:** Add scheduler routes to `http_api.py` (pattern: same as sessions/plugins routes)

### Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data fetching | Direct `fetch()` to `/api/scheduler/*` | Consistent with all existing views (no state management library) |
| State management | Component-local `ref()` | No Pinia/Vuex -- no existing usage in codebase, adding one for one page is overkill |
| Styling | Existing CSS variables from `App.vue` | Glass morphism theme already established; reuse `--panel`, `--accent`, etc. |
| Form controls | Native HTML + custom styling | Consistent with existing components (CustomSelect, EditableListField pattern) |

### What NOT to Add

| Avoid | Why |
|-------|-----|
| Pinia / Vuex | No state management library in codebase; 14 views work fine without it |
| UI component library (Element Plus, Vuetify) | All 14 existing views use custom CSS; adding a library creates visual inconsistency |
| WebSocket for real-time updates | Polling every 5s is sufficient for a scheduler management page; SSE/WebSocket adds complexity for no real user benefit |
| Chart library | Not needed for task listing |

### WebUI Usability Improvements (Same Stack)

The "WebUI usability optimization" item requires no new packages either. Improvements should focus on:

- Responsive layout fixes (already partially in `App.vue` with media queries)
- Better error states and loading indicators (pure CSS + Vue)
- Sidebar collapsible on mobile (CSS + toggle)
- Form validation feedback (existing pattern)

---

## Feature 3: Group Chat "Reply Only to @ and Quote" Bug Fix

### Recommended Stack

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `NapCatGateway._translate_message()` | existing | Message translation | Already extracts `mentions_self`, `reply_targets_self`, `targets_self` |
| `SessionRuntime.build_facts()` | existing | Event fact derivation | Already maps `targets_self` into `EventFacts` |
| `SessionRuntime.resolve_admission()` | existing | Admission decision | Already resolves admission mode per surface |
| `MatchSpec.matches()` | existing | Condition evaluation | Already checks `targets_self`, `mentions_self`, `reply_targets_self` |

### Root Cause Analysis

The bug is in the interaction between `targets_self` computation and session-config admission logic.

**Current flow:**

1. `NapCatGateway._translate_message()` computes `targets_self`:
   ```python
   targets_self = (
       raw.get("message_type") == "private"
       or mentioned_everyone
       or mentions_self
       or reply_targets_self
   )
   ```

2. `SessionRuntime._surface_candidates()` uses these facts to pick a surface:
   ```python
   if facts.mentions_self:
       return ["message.mention", "message.plain"]
   if facts.reply_targets_self:
       return ["message.reply_to_bot", "message.plain"]
   ```

3. Session YAML's admission domain then decides respond vs silent_drop

**Bug hypothesis (requires confirmation in Phase 1):**

The `message_filter` configuration (`all`, `mention_only`, `reply_only`, `mention_or_reply`) exists in `session_templates.py` as options, but the actual admission logic in `session_runtime.py` does not directly consume a `message_filter` field. Instead it relies on the surface candidate chain. If a group message is neither @mention nor reply_to_bot, it falls to `message.plain` surface, which may have admission mode `respond` -- causing the bot to reply to all messages.

**Fix approach:** Ensure the admission domain in group session configs properly uses `targets_self` / `mentions_self` / `reply_targets_self` as match conditions, so non-targeting messages get `silent_drop`.

### Zero Dependencies Needed

This is a pure logic bug in existing code. No new libraries.

### What NOT to Do

| Avoid | Why |
|-------|-----|
| Add filtering at Gateway level | Gateway should translate, not filter -- that's session-config's job |
| Add a separate "group filter" component | The surface+admission pattern already handles this correctly when configured right |
| Hardcode group behavior | Session configs should control this per-group |

---

## Feature 4: AstrBot Database Migration to LTM

### Recommended Stack

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `aiosqlite` | >= 0.20.0 (existing) | Read AstrBot SQLite database | Already in `pyproject.toml`; AstrBot uses SQLite with `sqlmodel`/`aiosqlite` |
| `LanceDbLongTermMemoryStore` | existing | Write target | `src/acabot/runtime/memory/long_term_memory/storage.py` -- `upsert_entries()` accepts batch writes |
| `LtmWritePort` | existing | Extraction pipeline | `src/acabot/runtime/memory/long_term_memory/write_port.py` -- handles extraction + embedding + storage |
| `MemoryEntry` | existing | Target data format | `src/acabot/runtime/memory/long_term_memory/contracts.py` |

### AstrBot Database Structure (Source)

AstrBot uses SQLAlchemy+SQLModel with SQLite (`sqlite+aiosqlite:///<path>`). Key tables:

| Table | Contents | Migration Relevance |
|-------|----------|-------------------|
| `conversations` (ConversationV2) | `conversation_id`, `platform_id`, `user_id`, `content` (JSON list of OpenAI-format messages), `title`, `persona_id` | **Primary source** -- contains full chat history |
| `platform_message_history` (PlatformMessageHistory) | `platform_id`, `user_id`, `sender_id`, `sender_name`, `content` (JSON message chain) | **Secondary source** -- raw platform messages (QQ group/private) |
| `platform_sessions` (PlatformSession) | `session_id`, `platform_id`, `creator`, `is_group` | Maps sessions to users/groups |
| `personas` (Persona) | `persona_id`, `system_prompt`, `begin_dialogs` | Not needed -- AcaBot has its own soul/self system |

### Migration Strategy

**Phase A: Extract from AstrBot SQLite**
- Read `conversations` table via `aiosqlite` (no need for SQLModel dependency)
- Parse `content` JSON field (list of `{"role": "user"|"assistant", "content": "..."}` dicts)
- Map `platform_id` + `user_id` to AcaBot `conversation_id` format (`qq:group:<id>` or `qq:user:<id>`)

**Phase B: Transform to AcaBot format**
- Group message pairs into conversation windows (same sliding window logic as `LtmWritePort`)
- Run through the existing LLM-based extraction pipeline (`LtmWindowExtractor.extract_window()`)
- This generates `MemoryEntry` objects with proper `topic`, `lossless_restatement`, `keywords`, `persons`, `entities`

**Phase C: Load into LTM**
- Use `LanceDbLongTermMemoryStore.upsert_entries()` for batch writes
- Generate embeddings via `LtmEntryEmbeddingClient.embed_entries()`

### Key Integration Points

```
AstrBot SQLite ──aiosqlite──> raw message dicts
    └──> ConversationDelta (group into windows)
        └──> LtmWritePort.ingest_thread_delta() (existing method!)
            └──> extract_window() → embed_entries() → upsert_entries()
```

The `LtmWritePort.ingest_thread_delta()` method already handles the full extraction pipeline. The migration script just needs to:
1. Read AstrBot SQLite
2. Convert to `ConversationDelta` objects
3. Call `ingest_thread_delta()` for each conversation

### What to Build

A one-time migration script at `scripts/migrate_astrbot_to_ltm.py` (~150 lines):

```python
# 1. Open AstrBot SQLite (read-only)
# 2. Read conversations + platform_message_history
# 3. Group messages by conversation_id into ConversationDelta
# 4. For each delta, call ltm_write_port.ingest_thread_delta()
# 5. Report progress and stats
```

Plus a Control Plane HTTP API endpoint to trigger and monitor migration:
- `POST /api/migration/astrbot` -- start migration
- `GET /api/migration/astrbot/status` -- poll progress

### What NOT to Do

| Avoid | Why | Do Instead |
|-------|-----|------------|
| Import AstrBot's SQLModel/SQLAlchemy models | Pulls in AstrBot's entire dependency tree | Raw SQL via `aiosqlite` -- only need SELECT on 2-3 tables |
| Migrate personas/system prompts | AcaBot has its own soul/self system; AstrBot personas don't map cleanly | Only migrate conversation content |
| Try to preserve message IDs | AcaBot uses a different ID scheme; references would break | Generate new AcaBot-compatible IDs |
| Skip the extraction pipeline and write raw | Raw messages are too verbose for LTM; extraction produces the compressed `lossless_restatement` format | Always go through `LtmWritePort` extraction |

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Cron parsing | Keep `croniter` | Migrate to `cronsim` | `croniter` works fine in production; migration is pure churn for v1.1 |
| WebUI state management | Component-local refs | Pinia | No existing usage; 14 views work without it |
| WebUI components | Custom CSS | Element Plus / Naive UI | Visual inconsistency with existing glass morphism design |
| AstrBot DB access | Raw `aiosqlite` | Import AstrBot's `SQLModel` | Pulls in entire AstrBot dependency tree |
| Migration trigger | HTTP API endpoint | CLI script only | WebUI integration lets operator trigger and monitor from browser |
| Real-time scheduler updates | Polling (5s interval) | WebSocket / SSE | Overkill for a task list that changes every minutes/hours |

---

## Installation

```bash
# No new packages needed!
# All dependencies are already in pyproject.toml and package.json

# Verify existing deps are current:
pip install "croniter>=2.0.0"   # already in pyproject.toml
pip install "aiosqlite>=0.20.0" # already in pyproject.toml
```

---

## Confidence Assessment

| Feature Area | Confidence | Reason |
|-------------|------------|--------|
| Scheduler tool surface | HIGH | Exact same pattern as existing `BuiltinMessageToolSurface`; `RuntimeScheduler` API is clean and complete |
| WebUI scheduler page | HIGH | Same view pattern as 14 existing views; HTTP API pattern established |
| Group chat bug fix | MEDIUM | Root cause identified (admission domain configuration), but exact fix location depends on session YAML inspection during implementation |
| AstrBot migration | HIGH | `LtmWritePort.ingest_thread_delta()` already implements the full extraction pipeline; migration script is a thin adapter |

---

## Summary: What Changed from v1.0 Stack

| v1.0 Recommendation | v1.1 Status |
|---------------------|-------------|
| Add `cronsim` | **Not needed** -- kept `croniter` (already integrated, working) |
| Add `structlog` | **Already done** in v1.0 |
| Custom asyncio scheduler | **Already done** in v1.0 |
| LanceDB integrity layer | **Already done** in v1.0 |
| Playwright renderer | **Already done** in v1.0 |
| **New for v1.1** | **Zero new dependencies** |

---

## Sources

- `src/acabot/runtime/scheduler/scheduler.py` -- RuntimeScheduler implementation (verified 2026-04-05)
- `src/acabot/runtime/tool_broker/broker.py` -- ToolBroker registration pattern (verified 2026-04-05)
- `src/acabot/runtime/builtin_tools/message.py` -- Reference tool surface implementation (verified 2026-04-05)
- `src/acabot/runtime/control/http_api.py` -- HTTP API routing pattern (verified 2026-04-05)
- `src/acabot/runtime/memory/long_term_memory/write_port.py` -- LTM ingestion pipeline (verified 2026-04-05)
- `src/acabot/runtime/memory/long_term_memory/storage.py` -- LanceDB store API (verified 2026-04-05)
- `src/acabot/gateway/napcat.py` -- OneBot v11 message translation (verified 2026-04-05)
- `src/acabot/runtime/control/session_runtime.py` -- Admission logic (verified 2026-04-05)
- `ref/AstrBot/astrbot/core/db/__init__.py` -- AstrBot database schema (verified 2026-04-05)
- `ref/AstrBot/astrbot/core/db/po.py` -- AstrBot data models (verified 2026-04-05)
- `webui/package.json` -- Frontend dependencies (verified 2026-04-05)

---
*Stack research for: AcaBot v1.1 production readiness + LTM migration*
*Researched: 2026-04-05*
