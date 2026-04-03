# Architecture Research

**Domain:** Chatbot runtime infrastructure — integrating new subsystems into AcaBot
**Researched:** 2026-04-02
**Confidence:** HIGH (based on full source analysis + design doc `docs/29-plugin-control-plane.md`)

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Entry / Lifecycle                              │
│  main.py → build_runtime_components() → RuntimeApp.start() → signal   │
├─────────────────────────────────────────────────────────────────────────┤
│                         Gateway Layer                                  │
│  ┌──────────────┐    StandardEvent    ┌──────────────┐                │
│  │ NapCatGateway │ ──────────────────→ │  RuntimeApp  │                │
│  │  (WS server)  │ ←────────────────── │              │                │
│  └──────────────┘    Action (send)    └──────┬───────┘                │
├──────────────────────────────────────────────┼──────────────────────────┤
│                    Orchestration              │                         │
│  ┌────────────┐  ┌──────────────┐  ┌────────┴───────┐                │
│  │RuntimeRouter│  │PluginHost    │  │ ThreadPipeline │                │
│  │→SessionRT   │  │(hooks@6pts)  │  │ (13-step exec) │                │
│  └────────────┘  └──────────────┘  └────────┬───────┘                │
├──────────────────────────────────────────────┼──────────────────────────┤
│                   Agent / Model               │                         │
│  ┌────────────────┐  ┌──────────┐  ┌────────┴───────┐                │
│  │ModelAgentRuntime│  │ToolBroker│  │ContextAssembler│                │
│  │  → LitellmAgent│  │(registry) │  │(prompt+memory) │                │
│  └────────────────┘  └──────────┘  └────────────────┘                │
├─────────────────────────────────────────────────────────────────────────┤
│                    Memory / Storage                                    │
│  ┌───────────┐  ┌──────────┐  ┌────────┐  ┌─────────┐               │
│  │MemoryBroker│  │StickyNote│  │  Soul  │  │   LTM   │               │
│  │ (fan-out)  │  │FileStore │  │ Source │  │(LanceDB)│               │
│  └───────────┘  └──────────┘  └────────┘  └─────────┘               │
│  ┌────────────────┐  ┌────────────────────┐                           │
│  │ SQLite stores   │  │ LTM Ingestor (bg)  │                           │
│  │(events/msgs/    │  │ (async write path)  │                           │
│  │ runs/threads)   │  └────────────────────┘                           │
│  └────────────────┘                                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                    Delivery                                            │
│  ┌──────────────────────────────────────────────────┐                 │
│  │ Outbox: PlannedAction[] → Gateway.send() → Store │                 │
│  └──────────────────────────────────────────────────┘                 │
├─────────────────────────────────────────────────────────────────────────┤
│                    Control Plane                                       │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────┐            │
│  │RuntimeControlPlane│  │ConfigControlPlane│  │HTTP API   │            │
│  │(introspection)   │  │(hot-reload)      │  │(→WebUI)   │            │
│  └─────────────────┘  └──────────────────┘  └───────────┘            │
└─────────────────────────────────────────────────────────────────────────┘
```

### Existing Integration Surfaces

| Surface | File | What plugs in here |
|---------|------|--------------------|
| `build_runtime_components()` | `bootstrap/__init__.py` | All component construction — single DI wiring point |
| `RuntimeApp.start()` / `.stop()` | `app.py` | Lifecycle: reconcile, gateway, ingestor, shutdown teardown |
| `ThreadPipeline` steps 1-13 | `pipeline.py` | Plugin hooks (6 points), memory retrieval, tool exec, outbox |
| `ToolBroker.register()` | `tool_broker/broker.py` | New tools (including unified message tool) |
| `Outbox.dispatch()` | `outbox.py` | Action delivery → Gateway → MessageStore → LTM notify |
| `RuntimeControlPlane` | `control/control_plane.py` | HTTP API delegates here; new management methods |
| `InMemoryLogBuffer` | `control/log_buffer.py` | WebUI log streaming |

---

## Component 1: Plugin Reconciler Architecture

### Problem

`plugin_manager.py` (972 lines) mixes hook management, plugin loading, config parsing, and model target registration. Identity is import path (breaks on refactor). `extensions/plugins/` directory mechanism never worked. Three different places do "reload" with no single source of truth.

### Architecture: Package / Spec / Status with Reconciler + Host

Per the accepted design in `docs/29-plugin-control-plane.md`, six new modules replace the monolithic plugin_manager:

```
                    ┌──────────────────────────┐
                    │     PluginReconciler      │
                    │   (decision layer)        │
                    │                           │
                    │  reads Package + Spec     │
                    │  computes desired vs      │
                    │    actual state           │
                    │  calls Host to converge   │
                    │  writes Status            │
                    └─────────┬────────────────┘
                              │ load/unload
                    ┌─────────▼────────────────┐
                    │   PluginRuntimeHost       │
                    │   (execution layer)       │
                    │                           │
                    │  holds loaded instances   │
                    │  manages hook registry    │
                    │  proxies tool reg to      │
                    │    ToolBroker             │
                    │  provides run_hooks()     │
                    └──────────────────────────┘
```

**Three data sources on disk:**

| Data | Location | Owner | Semantics |
|------|----------|-------|-----------|
| `PluginPackage` | `extensions/plugins/<id>/plugin.yaml` | Developer | What code is available |
| `PluginSpec` | `runtime_config/plugins/<id>/plugin.yaml` | Operator | What should be enabled + config overrides |
| `PluginStatus` | `runtime_data/plugins/<id>/status.json` | Reconciler (sole writer) | Observed state: phase, registered tools/hooks, errors |

### Module Boundaries (from design doc)

```
plugin_protocol.py     ← Plugin author contract (RuntimePlugin ABC, hooks, tool reg)
                          NO dependency on reconciler/host/package/spec/status
plugin_package.py      ← PluginPackage dataclass + PackageCatalog (scans extensions/)
plugin_spec.py         ← PluginSpec dataclass + SpecStore (reads/writes runtime_config/)
plugin_status.py       ← PluginStatus dataclass + StatusStore (reads/writes runtime_data/)
plugin_reconciler.py   ← PluginReconciler: Package + Spec + Host state → converge → Status
plugin_runtime_host.py ← PluginRuntimeHost + PluginLoadSnapshot (execution layer)
```

Key architectural invariant: **Reconciler is the brain, Host is the hands.** Reconciler never directly calls `plugin.setup()` or `plugin.teardown()`. It calls `host.load_plugin()` / `host.unload_plugin()` which handle the full lifecycle (import → instantiate → setup → register hooks/tools → snapshot).

### Bootstrap Integration

```python
# bootstrap/__init__.py — construction only, no side effects
catalog = PackageCatalog(extensions_plugins_dir)
spec_store = SpecStore(runtime_config_plugins_dir)
status_store = StatusStore(runtime_data_plugins_dir)
host = PluginRuntimeHost(tool_broker, model_target_catalog)
context_factory = make_context_factory(gateway, tool_broker, ...)
reconciler = PluginReconciler(catalog, spec_store, status_store, host, context_factory)
```

```python
# app.py — lifecycle
async def start(self):
    await self.reconciler.reconcile_all()   # first full reconcile

async def stop(self):
    await self.host.teardown_all()          # reverse-order cleanup
```

### Pipeline Integration

```python
# pipeline.py — direct replacement, same 6 hook points
# plugin_manager.run_hooks(point, ctx) → host.run_hooks(point, ctx)
```

### Control Plane Integration

```python
# control_plane.py — new resource methods (business logic here, not HTTP layer)
def list_plugins(self) -> list[PluginView]: ...
def get_plugin(self, plugin_id: str) -> PluginView | None: ...
async def update_plugin_spec(self, plugin_id, enabled, config) -> PluginView: ...
async def delete_plugin_spec(self, plugin_id: str) -> PluginView: ...
async def reconcile_all_plugins(self) -> list[PluginView]: ...
```

### Data Flow

```
WebUI "enable plugin"
  → PUT /api/system/plugins/<id>/spec
  → HTTP API → ControlPlane.update_plugin_spec()
  → SpecStore.save(spec)
  → Reconciler.reconcile_one(plugin_id)
    → reads Package (catalog.get) + Spec (store.load) + Host state (loaded_ids)
    → if should_load: Host.load_plugin(package, context) → PluginLoadSnapshot
    → if should_unload: Host.unload_plugin(plugin_id)
    → StatusStore.save(status)
  → return PluginView to WebUI
```

### Key Boundary: Reconciler Decoupled from Runtime

The `context_factory` closure (injected at bootstrap) encapsulates gateway, tool_broker, sticky_notes, etc. Reconciler only knows about Package, Spec, Host, and Status — keeps it testable.

### Trigger Points (no file-watching, no polling)

1. `app.start()` → `reconcile_all()`
2. Spec change via API → `reconcile_one(plugin_id)`
3. Manual rescan button in WebUI → `reconcile_all()`

---

## Component 2: Unified Message Tool

### Problem

Bot can only return plain text. No way to: reply-with-quote, emoji reaction, cross-session send, recall, send attachments, render text-as-image.

### Architecture: LLM Tool → Intent → Action → Outbox → Gateway

```
LLM tool call: message(action="reply", text="...", reply_to="msg_123")
  │
  ▼
MessageTool handler (registered in ToolBroker as builtin)
  │  validates params, resolves target
  │  translates intent → Action objects
  ▼
RunContext.planned_actions.append(PlannedAction(...))
  │
  ▼
ThreadPipeline step 11: Outbox.dispatch()
  │  iterates PlannedAction list
  │  calls Gateway.send(action) for each
  │  persists to MessageStore
  │  notifies LTM ingestor
  ▼
Gateway → platform (OneBot v11 → NapCat → QQ)
```

### Where Intent-to-Action Translation Lives

**In the tool handler itself** (`builtin_tools/message.py`). The tool handler is the only place that understands the LLM's intent parameters and can map them to the correct `Action`/`ActionType`. Neither Outbox nor Gateway should contain this logic.

```python
# builtin_tools/message.py
async def handle_message_tool(ctx: ToolExecutionContext, params: dict) -> str:
    action_type = params["action"]  # "send" | "reply" | "react" | "recall"
    
    if action_type == "reply":
        action = Action(type=ActionType.SEND_TEXT, text=params["text"],
                        reply_to=params["reply_to"], target=resolve_target(params))
    elif action_type == "react":
        action = Action(type=ActionType.SET_REACTION, emoji=params["emoji"],
                        target_message=params["reply_to"])
    # ...
    
    planned = PlannedAction(action=action, ...)
    ctx.run_context.planned_actions.append(planned)
    return "sent"
```

### NO_REPLY Convention

When the LLM uses the message tool AND fills `text`, it returns `NO_REPLY` to avoid double-sending. Without the tool, LLM text goes through the existing default path (pipeline builds SEND_TEXT from agent text response).

### Render-as-Image Path

```
message tool (render_as_image=true)
  → handler calls render_markdown_to_image(text) → image path
  → creates Action with image segment
  → same Outbox dispatch path
```

`render_markdown_to_image()` lives as an Outbox-layer utility, uses Playwright/Chromium from Docker image.

### Module Boundary

```
builtin_tools/message.py   ← Tool handler: intent params → Action → planned_actions
                              Depends on: ToolExecutionContext, Action, ActionType, PlannedAction
                              Does NOT depend on: Gateway, Outbox internals

types.py (ActionType)       ← May need new variants: SET_REACTION, RECALL_MESSAGE, etc.

outbox.py                   ← Unchanged. Still dispatches PlannedAction[] → Gateway.send()
```

**Critical rule:** Message tool MUST NOT bypass Outbox. All actions flow through `PlannedAction → Outbox.dispatch() → Gateway.send()` preserving message persistence, LTM notification, and `BEFORE_SEND`/`ON_SENT` plugin hooks.

---

## Component 3: Scheduler Service

### Problem

No timer/cron infrastructure. Plugins and bot core have no way to schedule deferred or periodic tasks.

### Lifecycle Position

```
bootstrap:     construct Scheduler (no tasks yet)
                 │
app.start():     │
                 ├─ reconciler.reconcile_all()
                 │    └─ plugins may register tasks via context
                 ├─ scheduler.start()  ← begins executing
                 │
                 ... runtime running, tasks fire on schedule ...
                 │
app.stop():      │
                 ├─ scheduler.stop()    ← cancel all pending, await running (timeout)
                 ├─ host.teardown_all() ← plugin teardown (tasks already gone)
                 ├─ ltm_ingestor.stop() ← background writer flush
                 ├─ computer_runtime.cleanup()
                 └─ gateway.stop()      ← close WS connections
```

**Scheduler stops FIRST** because scheduled callbacks may depend on other runtime components (gateway, tool_broker, plugins) that get torn down later.

### Architecture

```
┌──────────────────────────────────────────────┐
│                  Scheduler                    │
│                                              │
│  register(task_id, schedule, callback,       │
│           owner=None)                        │
│  unregister(task_id)                         │
│  unregister_by_owner(owner_id)               │
│  start() → creates asyncio management task   │
│  stop()  → cancels all, awaits completion    │
│  list_tasks() → TaskInfo[]                   │
│                                              │
│  Schedule types: once_at, interval, cron     │
│  Default max_concurrent=1 per task           │
│  Pure asyncio, no external deps              │
└──────────────────────────────────────────────┘
```

### Integration with Plugin Teardown

`unregister_by_owner(owner_id)` enables clean teardown:

```
Host.unload_plugin(plugin_id):
  1. scheduler.unregister_by_owner(f"plugin:{plugin_id}")  ← cancel tasks first
  2. ToolBroker.unregister(source=f"plugin:{plugin_id}")   ← remove tools
  3. model_target_catalog.unregister(...)                   ← remove model targets
  4. plugin.teardown()                                      ← plugin cleanup
  5. remove from loaded set, rebuild hook registry
```

### Module Boundary

```
scheduler.py   ← Scheduler class + schedule types + task registry
                  Depends on: asyncio only (pure infrastructure)
                  Does NOT depend on: plugins, gateway, tools
```

Wiring: `plugin_runtime_host.py` calls `scheduler.unregister_by_owner()` on unload. `app.py` brackets lifecycle. `bootstrap/__init__.py` constructs + wires.

---

## Component 4: Logging / Observability

### Current State

- `logging.getLogger("acabot.*")` throughout
- `InMemoryLogBuffer` (ring buffer) + `InMemoryLogHandler` → WebUI via `GET /api/logs`
- `LogEntry`: `timestamp, level, logger, message, kind, seq`
- Missing: tool call details, LTM process info, structured fields

### Enhancement: Enrich Existing Pattern

```
Runtime code
  │  logger.info("tool executed", extra={"log_kind": "tool_exec",
  │               "tool_name": "bash", "duration_ms": 120})
  ▼
InMemoryLogHandler.emit(record)
  │  extracts structured fields → LogEntry.context dict [NEW]
  ▼
InMemoryLogBuffer (ring buffer, ~2000 entries)
  ▼
HTTP API: GET /api/logs?after_seq=N  (response includes context)
  ▼
WebUI: renders structured details (expandable tool calls, etc.)
```

### Data Flow Map

| Source | Logger | Key Extra Fields | Consumer |
|--------|--------|------------------|----------|
| Tool execution | `acabot.runtime.tool_broker` | `tool_name`, `duration_ms`, `result_preview` | WebUI tool panel |
| LTM extraction | `acabot.runtime.memory.ltm` | `thread_id`, `facts_extracted`, `window_range` | WebUI LTM view |
| LTM query | `acabot.runtime.memory.ltm` | `query_text`, `results_count`, `retrieval_mode` | WebUI memory debug |
| Agent LLM call | `acabot.agent` | `model`, `tokens_in`, `tokens_out`, `duration_ms` | WebUI run inspector |
| Plugin lifecycle | `acabot.runtime.plugin` | `plugin_id`, `phase`, `load_error` | WebUI plugin status |
| Outbox dispatch | `acabot.runtime.outbox` | `action_type`, `target`, `success` | WebUI message audit |

### Integration

No new module. Changes:
1. `control/log_buffer.py` — `LogEntry` gains `context: dict` field; handler extracts from `LogRecord.extra`
2. Emit sites — add `extra={}` dicts to log calls in tool_broker, LTM, agent, outbox
3. `control/http_api.py` — `/api/logs` response includes `context` per entry
4. WebUI — renders structured fields

---

## Component 5: LTM Data Integrity

### Current State

- `LanceDbLongTermMemoryStore` handles all LanceDB ops
- Write: `Pipeline → Outbox notifies ingestor → queue → async extraction → LanceDB write`
- Read: `MemoryBroker → LtmMemorySource → LanceDB query` (pipeline step 7)
- "Update path uses full table rewrite" (per storage.py docstring)
- No concurrency protection, no backup, no validation

### Safety Architecture (all internal to store)

```
          Read path (pipeline)          Write path (ingestor)
                │                              │
                ▼                              ▼
        ┌──────────────────────────────────────────┐
        │         LanceDbLongTermMemoryStore        │
        │                                          │
        │  + asyncio.Lock for write serialization  │
        │  + entry validation before write          │
        │  + backup before table rewrite            │
        │  + recovery from backup on corruption     │
        │  + integrity check on startup             │
        └──────────────────────────────────────────┘
                        │
                  ┌─────┴─────┐
                  │  LanceDB  │
                  │  (disk)   │
                  └───────────┘
```

### Integration Without Breaking Async Pipeline

All changes internal to `memory/long_term_memory/storage.py`:

1. **Write serialization**: `asyncio.Lock` for all write ops. Reads concurrent (LanceDB snapshot isolation).
2. **Validation before write**: Validate `MemoryEntry` before committing. Invalid → logged + skipped.
3. **Backup before rewrite**: Copy table data before full rewrite. On failure → restore. Cheap (file-based).
4. **Cursor atomicity**: `thread_cursors` update same lock scope as `memory_entries` write. If cursor fails → re-extraction (idempotent).
5. **Startup check**: Validate tables + schema on store init.

Callers (`LongTermMemoryIngestor`, `LtmMemorySource`) remain unchanged — they use the store's existing API.

---

## Component 6: Removing Reference Backend

### Dependency Map

| File | Dependency |
|------|-----------|
| `bootstrap/__init__.py` | `build_reference_backend(config)` + wiring |
| `bootstrap/builders.py` | Factory function |
| `bootstrap/components.py` | `RuntimeComponents.reference_backend` field |
| `app.py` | Constructor param |
| `plugin_manager.py` | `RuntimePluginContext.reference_backend` |
| `control/control_plane.py` | Introspection + management |
| `plugins/reference_tools.py` | `ReferenceToolsPlugin` |
| `control/http_api.py` | Reference API endpoints |
| `references/` directory | Implementations + contracts |
| `tool_broker/broker.py` | Constructor param |

### Safe Two-Phase Removal

**Phase A — Null-out (zero behavioral change, all callers handle None):**

1. `build_reference_backend()` → always returns `None`
2. Delete `ReferenceToolsPlugin` (already planned for deletion in plugin refactor)
3. Remove HTTP API reference endpoints + WebUI pages

**Phase B — Delete dead code:**

1. Delete `src/acabot/runtime/references/` directory
2. Remove `reference_backend` param from all constructors
3. Remove from `RuntimeComponents` dataclass
4. Remove builder function, OpenViking dependency

**Safety check:** Grep `reference_backend` and `ReferenceBackend` before Phase B. Verify `BackendBridgeToolPlugin` doesn't depend on it (it takes `reference_backend` via `RuntimePluginContext` but should handle `None`).

---

## Build Order

```
                    ┌──────────────────┐
                    │ 1. Remove Ref    │  no deps, reduces surface area
                    │    Backend       │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │ 2. Plugin        │  foundational: scheduler + message tool
                    │    Reconciler    │  need plugin host for integration
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───────┐ ┌───▼──────┐ ┌────▼─────────┐
     │ 3a. Scheduler  │ │3b. LTM   │ │3c. Logging   │
     │                │ │ Safety   │ │              │
     └────────┬───────┘ └──────────┘ └──────────────┘
              │
     ┌────────▼────────┐
     │ 4. Unified      │  most design-uncertain, benefits from all above
     │    Message Tool  │
     └─────────────────┘
```

| Order | Component | Rationale |
|-------|-----------|-----------|
| 1 | Remove Reference Backend | Pure deletion. Reduces noise. Plugin refactor deletes `ReferenceToolsPlugin` anyway. |
| 2 | Plugin Reconciler | Foundation. Scheduler wiring into `PluginRuntimeHost.unload_plugin()` needs the new Host. Message tool goes through cleaned-up ToolBroker path. Largest change — do while codebase is cleanest. |
| 3a | Scheduler | Standalone (pure asyncio). Wiring into Host requires step 2. Parallelizable with 3b, 3c. |
| 3b | LTM Safety | Independent storage-layer change. Parallelizable with 3a, 3c. |
| 3c | Logging | Cross-cutting, incremental. Parallelizable with 3a, 3b. |
| 4 | Unified Message Tool | Most design-uncertain (per progress.md). Benefits from stable plugin system, scheduler, and logging. |

**Parallelization:** 3a/3b/3c touch non-overlapping code. Step 1 can fold into step 2 (overlapping file deletions).

---

## Anti-Patterns to Avoid

### God Module
`plugin_manager.py` grew to 972 lines mixing concerns. Split into protocol/package/spec/status/host/reconciler.

### Message Tool Bypassing Outbox
Tool must NOT call `gateway.send()` directly. Append `PlannedAction` to `RunContext` — Outbox handles persistence, LTM notify, plugin hooks.

### Implicit Lifecycle Dependencies
Enforce explicit start/stop ordering in `app.py`. Scheduler stops before plugin teardown. Plugin teardown before gateway stop.

### Write Locks on LTM Reads
Only writes acquire `asyncio.Lock`. Reads are lock-free (LanceDB MVCC). Don't add latency to user-facing pipeline.

---

## Integration Points Summary

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Reconciler ↔ Host | `host.load_plugin()` / `host.unload_plugin()` | Reconciler decides, Host executes |
| Host ↔ ToolBroker | `tool_broker.register()` / `unregister()` keyed by `source=f"plugin:{id}"` | Same registration pattern as today |
| Host ↔ Pipeline | `host.run_hooks(point, ctx)` at 6 hook points | Replaces `plugin_manager.run_hooks()` |
| Message Tool ↔ Outbox | Via `RunContext.planned_actions` | Tool appends, Outbox dispatches in step 11 |
| Scheduler ↔ Host | `scheduler.unregister_by_owner()` during unload | Prevents orphaned tasks |
| Scheduler ↔ App | `start()`/`stop()` lifecycle bracketing | Scheduler stops first in shutdown |
| LTM Store ↔ Ingestor | Direct calls + asyncio.Lock | Write lock only; reads concurrent |
| Logging ↔ WebUI | `LogEntry.context` dict through buffer → API → UI | Additive enhancement |

---
*Architecture research for: AcaBot v2 runtime infrastructure hardening*
*Researched: 2026-04-02*
