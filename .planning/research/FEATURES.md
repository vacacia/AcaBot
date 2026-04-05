# Feature Research

**Domain:** AcaBot v1.1 -- Production usability: group chat fix, scheduler tool exposure, WebUI improvements, AstrBot history migration
**Researched:** 2026-04-05
**Confidence:** HIGH (based on v1.0 codebase audit, OneBot v11 spec, AstrBot reference codebase, scheduler/storage contracts review)

---

## Scope Note

This file covers ONLY the v1.1 milestone features. The v1.0 feature landscape (plugin Reconciler, unified message tool, scheduler infra, LTM safety, structured logging, Control Plane API, WebUI) is documented in the previous version of this file and is now **validated/landed**. All features below assume v1.0 infrastructure exists.

---

## Feature Landscape

### Table Stakes (Users Expect These)

#### 1. Group Chat Response Filtering (Bug Fix)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Bot only replies when @'d or quoted in group | Standard QQ bot behavior; noise without it makes bot unusable in groups | LOW (fix) | The bug is in session-config's `message.plain` surface matching ambient group messages with default `mode: respond`. The admission domain must default to `silent_drop` for `message.plain` in group scenes. |
| Correct `targets_self` propagation | All downstream decisions (admission, routing) depend on this flag | LOW | Already works at gateway level (NapCat sets `targets_self` correctly for mentions/replies). The gap is in session-config surface resolution: `message.plain` surface should not map to `respond` mode. |

**Root Cause Analysis (from codebase):**

The surface candidate chain in `session_runtime._surface_candidates()` returns `["message.plain"]` for group messages that are neither @ nor replies. If the session config's `message.plain` surface has `admission.default.mode: respond` (or no admission config at all, which defaults to `respond`), the bot responds to every ambient group message. The fix is one of:

1. (Recommended) Change session config default so `message.plain` admission = `silent_drop` or `record_only` for group scenes.
2. Add a `when: { scene: group, targets_self: false }` case in the admission domain that sets `mode: silent_drop`.

No code changes to gateway, event types, or router needed. This is a session-config-level fix.

#### 2. Model-Facing Scheduler Tool

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Create scheduled task (cron/interval/one-shot) | "Remind me every Monday" -- basic LLM agent capability | MEDIUM | Requires a new builtin tool surface (`BuiltinSchedulerToolSurface`) registered in `register_core_builtin_tools`. The tool translates LLM parameters into `RuntimeScheduler.register()` calls. |
| List/view own tasks | Agent needs to see what it scheduled | LOW | `RuntimeScheduler.list_tasks()` already exists; filter by owner or metadata. |
| Cancel task by ID | "Cancel my reminder" -- basic management | LOW | `RuntimeScheduler.cancel()` already exists; expose through tool. |
| Bind task to session (conversation) | Scheduled message should target the originating conversation | MEDIUM | Requires `destination_conversation_id` in task metadata + callback that sends message via Outbox when task fires. Uses existing `post_notification` pattern from Control Plane. |
| Task fires and sends message to bound session | The whole point of scheduling -- proactive messaging | MEDIUM | Callback needs access to Outbox/pipeline to send. The `post_notification` method in `RuntimeControlPlane` is the reference implementation. |

**What already exists (from codebase audit):**
- `RuntimeScheduler`: full cron/interval/one-shot engine with heap-based dispatch, persistence, misfire handling, graceful shutdown -- **complete**
- `SQLiteScheduledTaskStore`: SQLite persistence layer -- **complete**
- `contracts.py`: `CronSchedule`, `IntervalSchedule`, `OneShotSchedule`, `ScheduledTaskInfo`, `ScheduledTaskRow` -- **complete**
- `register()` / `cancel()` / `list_tasks()` / `unregister_by_owner()` APIs -- **complete**
- `ToolBroker` registration pattern: `register_tool(spec, handler, source=...)` -- **well established**

**What needs to be built:**
- `BuiltinSchedulerToolSurface` class (following pattern of `BuiltinMessageToolSurface`, `BuiltinComputerToolSurface`)
- Tool schema definition (JSON schema for LLM: action type, schedule params, message content)
- Callback factory: generates async callbacks that dispatch messages via Outbox
- Integration into `register_core_builtin_tools()` in `builtin_tools/__init__.py`
- Agent prompt hint: "You can schedule tasks using the Schedule tool"

#### 3. Plugin-Side Scheduler Usage

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Plugin accesses scheduler via context | Plugins need periodic tasks too (e.g., RSS checker, stats reporter) | LOW | Inject `RuntimeScheduler` reference into `PluginRuntimeHost` context. Plugin code calls `self.context.scheduler.register(...)` |
| Plugin tasks auto-cancelled on plugin unload | Prevent orphan timers from unloaded plugins | LOW | `RuntimeScheduler.unregister_by_owner()` already exists. Hook into Reconciler teardown to call with `owner=f"plugin:{plugin_id}"`. |
| Documentation + example | Developers need to know how to use it | LOW | Example plugin that registers a cron task and cleans up. |

#### 4. WebUI Scheduler Management Page

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| List all scheduled tasks | Operators need visibility into what's scheduled | LOW | GET endpoint wrapping `scheduler.list_tasks()`. Already have `ControlPlane` + `HttpApi` pattern. |
| View task detail (schedule, next fire, owner) | Debugging failed/skipped tasks | LOW | Return `ScheduledTaskInfo` snapshot. |
| Cancel task from WebUI | Operator override without CLI | LOW | DELETE endpoint wrapping `scheduler.cancel()`. |
| Enable/disable task | Pause without losing config | MEDIUM | Requires `enable()`/`disable()` methods on scheduler (currently only `cancel()` exists; need soft-disable that keeps task in store but skips firing). |

#### 5. WebUI Usability Optimization

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Faster page loads (SWR caching already added) | Slow API calls = bad UX | LOW (tuning) | SWR caching was added in recent commit `cc54e17`. May need further tuning of stale/revalidation thresholds. |
| Responsive layout improvements | WebUI should work on different screen sizes | LOW-MEDIUM | CSS/layout tweaks in Vue frontend. |
| Error state display | When API calls fail, user needs feedback | LOW | Toast/notification on API error. |
| Navigation polish | Current nav may be confusing for new users | LOW | Label clarity, icon improvements. |

#### 6. AstrBot Chat History Extraction

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Read AstrBot SQLite database | Migration source is AstrBot's `data/*/data.db` | LOW | AstrBot uses SQLModel/SQLite. Tables: `ConversationV2` (LLM conversations with `content: list[dict]` in OpenAI message format), `PlatformMessageHistory` (raw platform messages). Both have `platform_id`, `user_id`, timestamps. |
| Map AstrBot user/group IDs to AcaBot conversation IDs | Need to translate `platform_id:user_id` to `qq:user:XXX` / `qq:group:XXX` | LOW | AstrBot's `platform_id` is typically `aiocqhttp` with `user_id` mapping to QQ numbers. The `ConversationV2.content` field contains OpenAI-format message lists. |
| Batch extraction script/endpoint | Operators won't manually migrate | MEDIUM | One-time migration script. Not a runtime feature. Could be a CLI command or a WebUI button that reads the AstrBot DB path. |

**AstrBot data model (from codebase audit):**

```
ConversationV2:
  - conversation_id: uuid
  - platform_id: str (e.g., "aiocqhttp")
  - user_id: str (QQ number or group_id)
  - content: JSON list of {role, content} dicts (OpenAI format)
  - created_at, updated_at: datetime

PlatformMessageHistory:
  - platform_id: str
  - user_id: str
  - sender_id: str (optional)
  - sender_name: str (optional)
  - content: dict (message chain)
  - created_at: datetime

PlatformSession:
  - session_id: uuid
  - platform_id: str
  - creator: str
  - is_group: int (0=private, 1=group)
```

Key challenge: AstrBot's `PlatformMessageHistory.content` is a message chain (AstrBot format), not raw text. Need to extract plain text for LTM ingestion. The `ConversationV2.content` is cleaner (OpenAI-format messages with role/content).

#### 7. Import AstrBot History to AcaBot LTM

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Convert extracted messages to LTM MemoryEntry format | Bridge between AstrBot schema and AcaBot's `MemoryEntry` | MEDIUM | `MemoryEntry` requires: `entry_id`, `conversation_id`, `topic`, `lossless_restatement`, `keywords`, `persons`, `entities`, `provenance`. AstrBot messages lack structured extraction -- need to synthesize these fields. |
| Batch embedding generation | Each MemoryEntry needs a vector for semantic search | MEDIUM | Use LTM's existing `LtmEntryEmbeddingClient` protocol. Batch embed all entries. |
| Write to LanceDB store | Persist imported entries | LOW | Use existing `LongTermMemoryWriteStore.upsert_entries()` with vectors. |
| Verify retrieval quality | Imported data must be findable via search | MEDIUM | Use existing `GET /api/memory/long-term/search-test` endpoint to verify. Spot-check that imported AstrBot conversations surface in relevant queries. |
| Deduplication / idempotency | Re-running migration should not create duplicates | LOW | Use deterministic `entry_id` generation based on source (e.g., `astrbot:{conversation_id}:{message_index}`). |

---

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| LLM creates cron expressions via tool | Natural language scheduling -- "remind the group every Friday at 3pm" | LOW (tool exposure) | LLM parses intent to cron/interval params. Unique vs NoneBot2 which requires manual cron setup. |
| Scheduled agent runs with full tool access | Cron fires a full agent pipeline, not just a static message | HIGH | Beyond simple "send text at time X" -- the bot can reason, use tools, and generate dynamic content on schedule. |
| Cross-framework LTM migration | Import history from other bot frameworks into semantic memory | MEDIUM | Rare capability. Most bots treat history as ephemeral. AcaBot preserves knowledge across framework switches. |
| Plugin-scheduler integration with lifecycle binding | Plugins register periodic tasks that auto-clean | LOW | Unique to AcaBot's reconciler-aware architecture. |

---

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Distributed scheduler | "What if I run multiple instances?" | AcaBot is single-instance Docker. Distributed scheduling adds complexity for zero benefit. | Single-process `RuntimeScheduler` with SQLite persistence. |
| Schedule recurrence rules (RRULE) | "Every 2nd Tuesday of odd months" | RRULE is extremely complex; cron covers 99% of use cases | Cron expressions + one-shot for edge cases. LLM can compose complex schedules from multiple cron entries. |
| Real-time scheduler UI (WebSocket push) | "See tasks fire in real-time" | Overkill for single-operator bot. Polling every 5-10 seconds is fine. | Polling-based refresh on scheduler page. |
| Full AstrBot feature parity | "Bot must work exactly like AstrBot" | AcaBot has different architecture; 1:1 parity impossible and undesirable | Migrate data, not behavior. AcaBot's agent model is fundamentally different. |
| Import AstrBot persona/config | "Keep my AstrBot settings" | Persona systems are incompatible (AstraBot persona = prompt string; AcaBot = soul files + session agents) | Manual reconfiguration. Import only chat data, not persona config. |
| Import all AstrBot plugin data | "Keep plugin state" | Plugin ecosystems are incompatible | Start fresh. AcaBot plugins are different architecture. |

---

## Feature Dependencies

```
[Group Chat Fix (P1)]
    └── requires ──> Session config update (no code dependency)
    └── independent ──> No dependency on any other v1.1 feature

[Scheduler Tool Surface (P2)]
    └── requires ──> RuntimeScheduler (already built)
    └── requires ──> ToolBroker registration pattern (already built)
    └── requires ──> Outbox/message dispatch (for callback firing)
    └── enables ──> Plugin-Side Scheduler Usage
    └── enables ──> WebUI Scheduler Page

[Plugin-Side Scheduler (P2)]
    └── requires ──> Scheduler Tool Surface (tool registration pattern)
    └── requires ──> PluginRuntimeHost scheduler injection
    └── requires ──> Reconciler teardown hook (already built)
    └── independent ──> Does NOT require WebUI scheduler page

[WebUI Scheduler Page (P3)]
    └── requires ──> HTTP API endpoints (control_plane + http_api additions)
    └── requires ──> RuntimeScheduler.list_tasks() (already built)
    └── requires ──> Soft enable/disable (new method on scheduler)
    └── enhanced-by ──> Scheduler Tool Surface (shows model-created tasks)

[WebUI Usability (P3)]
    └── independent ──> No dependency on other features
    └── enhanced-by ──> SWR caching (already added)

[AstrBot History Extraction (P6)]
    └── requires ──> Read access to AstrBot SQLite DB file
    └── requires ──> AstrBot schema knowledge (from reference codebase)
    └── independent ──> Does NOT require scheduler or WebUI features

[Import to LTM (P7)]
    └── requires ──> AstrBot History Extraction (must extract first)
    └── requires ──> LTM write port (already built)
    └── requires ──> Embedding client (already built)
    └── requires ──> Deterministic entry_id generation
```

### Dependency Notes

- **Group chat fix is fully independent:** It's a session-config-level change. Can ship as a hotfix before any other v1.1 work.
- **Scheduler tool surface is the keystone for P2-P3:** Both plugin-side usage and WebUI page depend on the tool being registered. Build tool surface first.
- **Plugin-side scheduler is additive after tool surface:** Once the tool surface exists and the scheduler is injected into plugin context, plugin authors can use it immediately. The Reconciler teardown hook already calls `unregister_by_owner()`.
- **WebUI scheduler page needs soft-disable:** Current scheduler only has `cancel()` (hard delete). The WebUI needs `enable()`/`disable()` to pause tasks without losing them.
- **AstrBot migration is a two-phase process:** Phase 1 (P6) extracts data from AstrBot DB. Phase 2 (P7) converts and imports to LTM. They should be separate phases because extraction may reveal data quality issues that affect import strategy.
- **LTM import reuses existing infrastructure:** `LtmWritePort`, `LongTermMemoryWriteStore`, and the embedding client all exist. The import is primarily a data transformation problem, not an infrastructure problem.

---

## MVP Definition

### Phase 1: Fix (P1)

Minimum to unblock production usage.

- [ ] Fix group chat "reply only to @ and quote" -- update session config admission defaults so `message.plain` surface in group scenes defaults to `silent_drop` or `record_only`

### Phase 2: Scheduler Exposure (P2)

Make scheduler usable by model and plugins.

- [ ] `BuiltinSchedulerToolSurface` -- create/view/cancel/bind-to-session tool for LLM
- [ ] Tool schema definition (JSON schema for `schedule_task`, `list_tasks`, `cancel_task`)
- [ ] Callback factory (scheduler fires -> sends message to bound conversation via Outbox)
- [ ] Register tool in `register_core_builtin_tools()`
- [ ] Plugin context injection (`context.scheduler` reference)
- [ ] Plugin auto-cleanup on Reconciler teardown
- [ ] Documentation + example plugin

### Phase 3: WebUI Polish (P3)

Operator-facing improvements.

- [ ] Scheduler management page (list, detail, cancel, enable/disable)
- [ ] HTTP API endpoints for scheduler CRUD
- [ ] Soft enable/disable on `RuntimeScheduler`
- [ ] WebUI usability pass (layout, error states, navigation)

### Phase 4: LTM Migration (P6-P7)

Historical data continuity.

- [ ] AstrBot DB extraction script/endpoint
- [ ] Conversation-to-MemoryEntry transformer
- [ ] Batch embedding + write to LanceDB
- [ ] Deterministic entry_id for idempotency
- [ ] Search quality verification

---

## Feature Prioritization Matrix

| Feature | User Value | Impl Cost | Priority | Depends On |
|---------|------------|-----------|----------|------------|
| Group chat @/reply filter fix | HIGH | LOW | P1 | None |
| Scheduler tool: create task | HIGH | MEDIUM | P2 | Scheduler infra (done) |
| Scheduler tool: list tasks | MEDIUM | LOW | P2 | Scheduler infra (done) |
| Scheduler tool: cancel task | MEDIUM | LOW | P2 | Scheduler infra (done) |
| Scheduler tool: bind to session | HIGH | MEDIUM | P2 | Outbox (done) |
| Plugin scheduler context | MEDIUM | LOW | P2 | Scheduler tool surface |
| Plugin auto-cleanup | MEDIUM | LOW | P2 | Reconciler (done) |
| Plugin docs + example | LOW | LOW | P2 | Plugin scheduler context |
| WebUI: scheduler list page | MEDIUM | LOW | P3 | HTTP API endpoints |
| WebUI: scheduler cancel button | MEDIUM | LOW | P3 | HTTP API endpoints |
| WebUI: scheduler enable/disable | MEDIUM | MEDIUM | P3 | Soft-disable method |
| WebUI: usability pass | MEDIUM | LOW-MEDIUM | P3 | None |
| AstrBot DB extraction | MEDIUM | MEDIUM | P6 | AstrBot DB access |
| AstrBot -> LTM conversion | HIGH | MEDIUM | P7 | Extraction + LTM write port |
| LTM import verification | HIGH | MEDIUM | P7 | Import complete |
| Deduplication / idempotency | MEDIUM | LOW | P7 | Deterministic entry_id |

**Priority key:**
- P1: Must fix immediately -- blocks production usage
- P2: Core feature exposure -- scheduler tool + plugin integration
- P3: Operator experience -- WebUI improvements
- P6-P7: Data migration -- separate phase, lower urgency

---

## Detailed Feature Specifications

### Scheduler Tool Schema (P2)

The tool should follow the existing builtin tool surface pattern. Proposed tool name: `Schedule`.

**Actions:**

| Action | Parameters | Returns |
|--------|-----------|---------|
| `create` | `action`, `schedule_type` (cron/interval/one_shot), `schedule_spec` (cron_expr/seconds/fire_at), `message` (text to send when task fires), `persist` (bool, default true) | `task_id`, `next_fire_at` |
| `list` | None (or optional `owner` filter) | Array of `{task_id, schedule, next_fire_at, enabled, metadata}` |
| `cancel` | `task_id` | `{cancelled: true/false}` |

**Callback behavior:**
When a task fires, the callback constructs a send intent using the stored `message` and `destination_conversation_id` from task metadata, then dispatches through the Outbox (same pattern as `RuntimeControlPlane.post_notification`).

**Key design decision:** Task ownership. Model-created tasks should use `owner = "tool:schedule:{run_id}"` so they can be traced back. Session-bound tasks carry `conversation_id` in metadata.

### WebUI Scheduler Page API (P3)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/scheduler/tasks` | List all scheduled tasks |
| GET | `/api/scheduler/tasks/:task_id` | Get task detail |
| DELETE | `/api/scheduler/tasks/:task_id` | Cancel task |
| PUT | `/api/scheduler/tasks/:task_id/toggle` | Enable/disable task |

### AstrBot Migration Data Flow (P6-P7)

```
AstrBot SQLite DB                    AcaBot LTM (LanceDB)
     |                                       |
     v                                       |
[Extraction Script]                           |
  - Read ConversationV2 rows                 |
  - Read PlatformMessageHistory rows          |
  - Map platform_id -> "qq"                  |
  - Map user_id -> conversation_id           |
     |                                       |
     v                                       |
[Transformer]                                 |
  - Group messages into windows              |
  - Generate entry_id (deterministic)        |
  - Synthesize topic/lossless_restatement    |
    (use message text directly)              |
  - Extract persons from sender_name         |
  - Extract keywords from text               |
  - Set conversation_id = "astrbot:{orig}"   |
     |                                       |
     v                                       v
[Batch Embed + Write] ─────────────────> [LanceDB tables]
  - Embed entries                           - memory_entries
  - upsert_entries(vectors=...)             - vectors
```

**Transformer strategy for `lossless_restatement`:**
AstrBot messages are in OpenAI format (`{role, content}`). For each message pair (user + assistant), create one `MemoryEntry` with:
- `topic`: First 50 chars of user message
- `lossless_restatement`: Concatenated user+assistant messages (cleaned)
- `keywords`: Extracted from message text (simple word frequency, or LLM extraction)
- `persons`: Sender names from `PlatformMessageHistory.sender_name`
- `conversation_id`: Deterministic from AstrBot `conversation_id`
- `entry_id`: `astrbot:{conversation_id}:{message_index}`

---

## Sources

- AcaBot codebase: `src/acabot/runtime/scheduler/` -- scheduler contracts, engine, store (fully audited)
- AcaBot codebase: `src/acabot/runtime/builtin_tools/` -- existing tool surface patterns (message, computer, skills, sticky_notes, subagents)
- AcaBot codebase: `src/acabot/runtime/control/control_plane.py` -- `post_notification` as reference for scheduled message dispatch
- AcaBot codebase: `src/acabot/runtime/control/session_runtime.py` -- surface candidate chain and admission resolution (group chat bug source)
- AcaBot codebase: `src/acabot/runtime/contracts/session_config.py` -- `EventFacts`, `MatchSpec`, `AdmissionDecision` (group chat fix target)
- AcaBot codebase: `src/acabot/types/event.py` -- `StandardEvent`, `targets_self` propagation (verified correct at gateway level)
- AcaBot codebase: `src/acabot/gateway/napcat.py` -- `_translate_message` sets `targets_self` correctly for mentions/replies
- AcaBot codebase: `src/acabot/runtime/memory/long_term_memory/contracts.py` -- `MemoryEntry` schema for migration target
- AcaBot codebase: `src/acabot/runtime/memory/long_term_memory/write_port.py` -- LTM write pipeline for import
- AstrBot reference: `ref/AstrBot/astrbot/core/db/po.py` -- `ConversationV2`, `PlatformMessageHistory`, `PlatformSession` data models
- AstrBot reference: `ref/AstrBot/astrbot/core/platform_message_history_mgr.py` -- message history CRUD
- AstrBot reference: `ref/AstrBot/astrbot/builtin_stars/astrbot/long_term_memory.py` -- AstrBot's own LTM (session-based, simpler than AcaBot)
- AcaBot config: `docs/29-plugin-control-plane.md` -- Reconciler teardown hooks for plugin scheduler cleanup

---
*Feature research for: AcaBot v1.1 production usability + LTM migration*
*Researched: 2026-04-05*
