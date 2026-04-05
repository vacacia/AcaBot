# Phase 11: Scheduler Tool Surface - Research

**Researched:** 2026-04-05
**Domain:** AcaBot Runtime Scheduler LLM-Facing Tool + HTTP API
**Confidence:** HIGH

## Summary

Phase 11 implements a `scheduler` builtin tool allowing the LLM to create, list, and cancel scheduled tasks, plus a synchronous HTTP API for the Phase 13 WebUI. The core `RuntimeScheduler` already exists (Phase 3a) with full `register/cancel/list_tasks/unregister_by_owner` API and SQLite persistence. This phase adds the tool surface, `ScheduledMessageDispatcher` intermediate layer, and HTTP API routes.

The approach is to model `BuiltinSchedulerToolSurface` after the existing `BuiltinMessageToolSurface` action-based pattern, wire a `ScheduledMessageDispatcher` into the tool handler for notification delivery, and add HTTP routes in `http_api.py` via `X-Session-ID` header-based owner filtering.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-06:** Single `scheduler` tool + action enum (`create` / `list` / `cancel`)
- **D-07:** Schedule discriminated union with `kind` + `spec` separation
- **D-08:** `task_id` auto-generated (UUID), returned immediately to model after creation
- **D-09:** `note` field optional (message sent when task fires)
- **D-10:** REST paths: `GET/POST/DELETE /api/scheduler/tasks`
- **D-11:** Owner binding: Header-based, `X-Session-ID` header passes owner session_id
- **D-12:** Use `ScheduledMessageDispatcher` intermediate layer
- **D-13:** Callback closure captures `conversation_id` (not ToolExecutionContext)
- **D-14:** Persistence recovery: callback=None, reconstructed via `ScheduledMessageDispatcher`
- **D-15:** Reference `control_plane.py:post_notification()` pattern for dispatcher

### Claude's Discretion

- croniter library (Phase 3a settled)
- SQLite table structure details
- Tool handler error handling approach
- Whether `list` returns `created_at` / `last_fire_at` fields

### Deferred Ideas (OUT OF SCOPE)

None - all gray areas resolved.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SCHED-01 | Model can create scheduled tasks (cron/interval/one-shot) via `scheduler` tool, bound to current session | `RuntimeScheduler.register()` API, `CronSchedule/IntervalSchedule/OneShotSchedule` contracts, `ScheduledMessageDispatcher` callback pattern |
| SCHED-02 | Model can view list of created scheduled tasks (filtered by owner) | `RuntimeScheduler.list_tasks()` returns `ScheduledTaskInfo` list; filter by owner in tool handler |
| SCHED-03 | Model can cancel a specific task_id via `scheduler` tool | `RuntimeScheduler.cancel(task_id)` returns bool |

## Standard Stack

### Core (Already Implemented)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `RuntimeScheduler` | Existing | Core scheduling engine | Phase 3a delivered |
| `SQLiteScheduledTaskStore` | Existing | SQLite persistence | Phase 3a delivered |
| `CronSchedule/IntervalSchedule/OneShotSchedule` | Existing | Schedule type contracts | Phase 3a delivered |
| `croniter` | Existing | Cron expression parsing | Phase 3a settled |
| `ToolBroker.register_tool()` | Existing | Tool registration | Pattern established |

### New Components for Phase 11

| Component | Purpose | File Location |
|-----------|---------|---------------|
| `BuiltinSchedulerToolSurface` | LLM-facing scheduler tool (action-based: create/list/cancel) | `src/acabot/runtime/builtin_tools/scheduler.py` (new) |
| `ScheduledMessageDispatcher` | Intermediate layer reconstructing callbacks at fire-time from conversation_id | `src/acabot/runtime/scheduler/dispatcher.py` (new) |
| `RuntimeControlPlane.scheduler_*` methods | HTTP API handlers for WebUI | `src/acabot/runtime/control/control_plane.py` |
| HTTP API routes | GET/POST/DELETE `/api/scheduler/tasks` | `src/acabot/runtime/control/http_api.py` |

**Installation:** No new packages needed. All dependencies already present.

## Architecture Patterns

### Recommended Project Structure

```
src/acabot/runtime/
├── builtin_tools/
│   ├── __init__.py       # add BuiltinSchedulerToolSurface to register_core_builtin_tools()
│   └── scheduler.py      # NEW: BuiltinSchedulerToolSurface
└── scheduler/
    ├── __init__.py       # export ScheduledMessageDispatcher
    ├── dispatcher.py     # NEW: ScheduledMessageDispatcher
    ├── scheduler.py      # existing
    ├── contracts.py      # existing
    └── store.py          # existing
```

### Pattern 1: Action-Based Tool Surface (BuiltinMessageToolSurface Reference)

**What:** Single tool with `action` enum field dispatching to sub-handlers.

**When to use:** When one tool name serves multiple related operations.

**Source:** `src/acabot/runtime/builtin_tools/message.py`

```python
# Pattern: _tool_spec() returns ToolSpec, _handle_* methods per action
class BuiltinSchedulerToolSurface:
    def register(self, tool_broker: ToolBroker) -> list[str]:
        tool_broker.register_tool(
            self._tool_spec(),
            self._handle_scheduler,  # single handler, dispatches on action
            source=BUILTIN_SCHEDULER_TOOL_SOURCE,
        )
        return ["scheduler"]

    @staticmethod
    def _tool_spec() -> ToolSpec:
        return ToolSpec(
            name="scheduler",
            description="... scheduler tool description ...",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "cancel"],
                        "description": "...",
                    },
                    "schedule": { ... },  # for create
                    "note": { ... },      # for create
                    "task_id": { ... },   # for cancel
                },
                required": ["action"],
            },
        )

    async def _handle_scheduler(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        action = str(arguments.get("action", "")).strip()
        if action == "create":
            return self._handle_create(arguments, ctx)
        if action == "list":
            return self._handle_list(arguments, ctx)
        if action == "cancel":
            return self._handle_cancel(arguments, ctx)
        raise ValueError(f"unsupported scheduler action: {action}")
```

### Pattern 2: ScheduledMessageDispatcher (Callback Reconstruction)

**What:** Factory that creates async callbacks capturing `conversation_id`, used at task fire time to deliver notifications via `post_notification()`.

**Reference:** `control_plane.py:post_notification()` (lines 848-968)

```python
class ScheduledMessageDispatcher:
    """Reconstructs callbacks at task fire-time from conversation_id.

    Phase 3a decision: callback closure captures conversation_id (not ToolExecutionContext).
    At fire-time, dispatcher creates the callback with live runtime context.
    """

    def __init__(
        self,
        control_plane: RuntimeControlPlane,
    ) -> None:
        self._control_plane = control_plane

    def make_callback(
        self,
        conversation_id: str,
        note: str | None,
    ) -> Callable[[], Awaitable[None]]:
        """Create async callback that sends note to conversation_id."""
        async def callback() -> None:
            if note:
                await self._control_plane.post_notification(
                    payload={
                        "conversation_id": conversation_id,
                        "text": note,
                    }
                )
        return callback
```

### Pattern 3: HTTP API Route Registration (http_api.py Pattern)

**What:** `RuntimeHttpApiServer.handle_api_request()` dispatches on URL path segments using if-chain pattern.

**Source:** `src/acabot/runtime/control/http_api.py` (lines 257-714)

```python
# In handle_api_request(), add:
if segments == ["scheduler", "tasks"] and method == "GET":
    owner = _query_value(query, "owner", "") or self._get_session_id_from_headers()
    return self._ok(self._await(
        self.control_plane.list_scheduler_tasks(owner=owner)
    ))
if segments == ["scheduler", "tasks"] and method == "POST":
    return self._ok(self._await(
        self.control_plane.create_scheduler_task(payload=payload)
    ))
if len(segments) == 3 and segments[:2] == ["scheduler", "tasks"]:
    task_id = segments[2]
    if method == "DELETE":
        return self._ok(self._await(
            self.control_plane.cancel_scheduler_task(task_id=task_id)
        ))
```

### Pattern 4: ToolBroker.register_tool() Signature

**Source:** `src/acabot/runtime/tool_broker/broker.py` (lines 69-103)

```python
def register_tool(
    self,
    spec: ToolSpec,
    handler: ToolHandler,  # async def handler(arguments, ctx) -> Any
    *,
    source: str = "runtime",
    metadata: dict[str, Any] | None = None,
) -> None:
```

`ToolHandler = Callable[[dict[str, Any], ToolExecutionContext], Awaitable[Any]]` (from `broker.py` line 29)

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cron parsing | Custom cron parser | `croniter` | Already used by Phase 3a scheduler; robust, tested |
| Task fire notification | Direct Outbox calls from callback | `ScheduledMessageDispatcher` + `post_notification()` | `post_notification()` already handles thread context, world_view, outbox wiring |
| Tool result serialization | Custom JSON shaping | `ToolResult` from `tool_broker.contracts` | Already has `llm_content`, `attachments`, `raw`, `artifacts`, `user_actions` fields |
| Session-to-owner mapping | Custom header parsing | `X-Session-ID` header per D-11 | Already established pattern in http_api.py |

## Runtime State Inventory

> Skip this section - Phase 11 is a greenfield feature (new tool surface + HTTP API), not a rename/refactor/migration phase. No runtime state needs migration.

**Step 2.5: SKIPPED** — Phase 11 adds new functionality to an existing scheduler runtime. No rename/refactor/migration of existing runtime state.

## Common Pitfalls

### Pitfall 1: Callback Captures ToolExecutionContext Directly
**What goes wrong:** Callback closures capture `ctx` or `ToolExecutionContext`, but ToolExecutionContext references live objects (thread, agent, world_view) that are invalid at fire-time.
**Why it happens:** `ToolExecutionContext` is run-scoped, not task-scoped. Task may fire minutes/hours later in a different run.
**How to avoid:** Phase 3a decision D-13: only capture `conversation_id` (a string) in the callback closure. Use `ScheduledMessageDispatcher.make_callback(conversation_id, note)` to reconstruct the callback at fire time.
**Warning signs:** `RuntimeScheduler` worker loop fires tasks after original run context is gone; callback references `ctx.agent`, `ctx.world_view`, etc.

### Pitfall 2: Tool Handler Returns Before Task Fires
**What goes wrong:** Model calls `scheduler.create(...)` and the tool returns immediately with `task_id`, but the caller assumes synchronous execution.
**Why it happens:** Scheduler is async; task fires in background worker loop.
**How to avoid:** Document that `create` returns immediately with `task_id`; task fires asynchronously per schedule.
**Warning signs:** Model calls `scheduler.create` and expects result message to arrive at scheduled time.

### Pitfall 3: Owner Filter Missing in list_tasks
**What goes wrong:** `list` action returns all tasks from all owners, leaking information between sessions.
**Why it happens:** `RuntimeScheduler.list_tasks()` returns all tasks; filtering by owner is the tool handler's responsibility.
**How to avoid:** In `_handle_list()`, extract `owner` from `ToolExecutionContext` (via `ctx.agent.agent_id` or conversation_id) and filter returned tasks.
**Warning signs:** WebUI or model sees tasks from other sessions.

### Pitfall 4: Scheduler Not Started Before Gateway
**What goes wrong:** Gateway events arrive but scheduler worker loop hasn't started, so no tasks fire.
**Why it happens:** `RuntimeApp.start()` calls `scheduler.start()` before `gateway.start()`, but if scheduler start fails silently, tasks queue but never execute.
**How to avoid:** Phase 3a already wired scheduler start in `app.start()` with try/except. Verify new phases don't re-order this incorrectly.
**Warning signs:** `scheduler.start()` raises exception or returns without logging "Scheduler started".

## Code Examples

### Example: Tool Handler Registration in register_core_builtin_tools()

**Source:** `src/acabot/runtime/builtin_tools/__init__.py` (lines 37-79)

```python
# In register_core_builtin_tools(), add parameter:
def register_core_builtin_tools(
    *,
    tool_broker: ToolBroker,
    computer_runtime: ComputerRuntime | None,
    skill_catalog: SkillCatalog | None,
    sticky_note_service,
    subagent_delegator: SubagentDelegationBroker | None,
    scheduler_dispatcher: ScheduledMessageDispatcher | None,  # NEW PARAM
) -> dict[str, list[str]]:
    ...
    scheduler_surface = BuiltinSchedulerToolSurface(
        dispatcher=scheduler_dispatcher,
    )
    return {
        ...
        BUILTIN_SCHEDULER_TOOL_SOURCE: scheduler_surface.register(tool_broker),
    }
```

### Example: HTTP API X-Session-ID Header Parsing

**Source:** `src/acabot/runtime/control/http_api.py` (pattern from existing handlers)

```python
def _get_session_id_from_headers(self) -> str:
    """Extract X-Session-ID from current request context.

    Note: ThreadingHTTPServer doesn't expose per-request headers directly.
    The Handler class captures headers in self.headers during do_*.
    Need to thread this through to handle_api_request or use a contextvar.
    """
    # For the built-in http.server, we'd need to store headers in a
    # context-local way. One approach: parse from the calling context.
    # For simplicity, use query param ?owner= as fallback.
    return ""

# In handle_api_request:
owner = _query_value(query, "owner", "")  # primary: query param
# X-Session-ID header would need threading through Handler → server → handle_api_request
```

Note: The built-in `ThreadingHTTPServer` doesn't expose request headers to `handle_api_request` without threading changes. Alternative: use `?owner=` query parameter for the HTTP API, and rely on session binding for the tool surface.

### Example: RuntimeScheduler.register() Call

**Source:** `src/acabot/runtime/scheduler/scheduler.py` (lines 153-227)

```python
# From _handle_create in BuiltinSchedulerToolSurface:
task_id = uuid.uuid4().hex
callback = dispatcher.make_callback(
    conversation_id=conversation_id,
    note=note,
)
await runtime_scheduler.register(
    task_id=task_id,
    owner=owner,  # from ctx
    schedule=schedule_obj,  # CronSchedule | IntervalSchedule | OneShotSchedule
    callback=callback,
    persist=True,
    misfire_policy="skip",
    metadata={"note": note},
)
return ToolResult(llm_content=json.dumps({"task_id": task_id, "status": "created"}))
```

### Example: Schedule Type from Discriminated Union

**Source:** `src/acabot/runtime/scheduler/contracts.py` (lines 15-48)

```python
@dataclass(frozen=True, slots=True)
class CronSchedule:
    cron_expr: str

@dataclass(frozen=True, slots=True)
class IntervalSchedule:
    seconds: float

@dataclass(frozen=True, slots=True)
class OneShotSchedule:
    fire_at: float

# From tool handler, parsing "kind" + "spec":
if kind == "cron":
    schedule_obj = CronSchedule(cron_expr=spec["expr"])
elif kind == "interval":
    schedule_obj = IntervalSchedule(seconds=spec["seconds"])
elif kind == "one_shot":
    schedule_obj = OneShotSchedule(fire_at=spec["fire_at"])
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| AstrBot plugin-based scheduler | AcaBot native RuntimeScheduler + builtin tool surface | Phase 3a (scheduler core), Phase 11 (tool surface) | LLM can self-manage tasks without plugin infrastructure |
| Direct callback closure over ToolExecutionContext | `ScheduledMessageDispatcher` intermediate layer | Phase 3a decision D-13 | Task callbacks survive run context destruction |
| Plugin-only scheduler access | Both LLM (tool) and WebUI (HTTP API) access | Phase 11 | Unified task management across interfaces |

**Deprecated/outdated:**
- AstrBot `create_future_task` / `delete_future_task` / `list_future_tasks` plugin API — replaced by OpenClaw-style single `scheduler` tool with action enum

## Open Questions

1. **X-Session-ID header threading through ThreadingHTTPServer**
   - What we know: `RuntimeHttpApiServer` uses Python's built-in `ThreadingHTTPServer`; headers are available on `self.headers` inside `BaseHTTPRequestHandler` methods but not passed to `handle_api_request`.
   - What's unclear: Best pattern to propagate session ID from handler to server method without重构 the HTTP server architecture.
   - Recommendation: Use `?owner=` query parameter for HTTP API; X-Session-ID header for tool surface (passed via `ToolExecutionContext.metadata` from agent runtime).

2. **`created_at` / `last_fire_at` fields in list response**
   - What we know: `ScheduledTaskInfo` (line 52-74 in contracts.py) has `task_id`, `owner`, `schedule`, `persist`, `misfire_policy`, `next_fire_at`, `enabled`, `metadata`. It does NOT have `created_at` or `last_fire_at`.
   - What's unclear: Whether store tracks `last_fire_at` — looking at `store.py`, it doesn't.
   - Recommendation: Add `created_at` and `last_fire_at` to `ScheduledTaskInfo` and `ScheduledTaskRow` if WebUI needs them. Otherwise list returns what's available.

3. **`set_enabled()` method for WebUI (per STATE.md)**
   - What we know: `RuntimeScheduler` has no `set_enabled()` — only `cancel()`. STATE.md notes WebUI needs `set_enabled()`.
   - What's unclear: Whether this is in scope for Phase 11 or Phase 13.
   - Recommendation: Add `RuntimeScheduler.enable(task_id)` / `disable(task_id)` to Phase 11 since it's needed by WEBUI-02 and directly supports the scheduler tool surface.

## Environment Availability

**Step 2.6: SKIPPED** — No external dependencies. Phase 11 is pure Python code additions to existing runtime. No new tools, services, or CLIs required beyond what's already in the project.

## Validation Architecture

> Included per `workflow.nyquist_validation: true` in `.planning/config.json`.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | `pytest.ini` or `pyproject.toml` (not checked — assume standard pytest) |
| Quick run command | `pytest tests/test_scheduler.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|---------------|
| SCHED-01 | Create cron/interval/one-shot task, task_id returned | unit | `pytest tests/test_scheduler.py -k "test_register" -x` | YES |
| SCHED-01 | Task fires and notification sent | integration | `pytest tests/test_scheduler_integration.py -k "test_scheduler_fires_notification" -x` | PARTIAL (integration test exists, not specific to new surface) |
| SCHED-02 | List tasks filtered by owner | unit | `pytest tests/test_scheduler.py -k "test_list_tasks" -x` | YES |
| SCHED-03 | Cancel task by task_id | unit | `pytest tests/test_scheduler.py -k "test_cancel" -x` | YES |

### Sampling Rate
- **Per task commit:** `pytest tests/test_scheduler.py tests/test_scheduler_integration.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_scheduler_tool_surface.py` — tests for BuiltinSchedulerToolSurface (create/list/cancel actions)
- [ ] `tests/test_scheduler_dispatcher.py` — tests for ScheduledMessageDispatcher callback reconstruction
- [ ] `tests/test_scheduler_http_api.py` — tests for HTTP API routes (/api/scheduler/tasks)
- [ ] `tests/conftest.py` — add `scheduler_dispatcher` fixture if needed

*(Existing test infrastructure: `tests/test_scheduler.py`, `tests/test_scheduler_integration.py` cover core scheduler behavior — no changes needed to those files for Phase 11.)*

## Sources

### Primary (HIGH confidence)
- `src/acabot/runtime/scheduler/scheduler.py` — RuntimeScheduler API (register/cancel/list_tasks/unregister_by_owner)
- `src/acabot/runtime/scheduler/contracts.py` — ScheduleType discriminated union definitions
- `src/acabot/runtime/scheduler/store.py` — SQLiteScheduledTaskStore persistence
- `src/acabot/runtime/builtin_tools/message.py` — BuiltinMessageToolSurface action-based pattern reference
- `src/acabot/runtime/builtin_tools/__init__.py` — register_core_builtin_tools() pattern
- `src/acabot/runtime/tool_broker/broker.py` — ToolBroker.register_tool() signature
- `src/acabot/runtime/control/http_api.py` — HTTP API route registration pattern
- `src/acabot/runtime/control/control_plane.py` — post_notification() pattern for dispatcher
- `src/acabot/runtime/bootstrap/__init__.py` — scheduler wiring in bootstrap
- `.planning/phases/3a-scheduler/3a-CONTEXT.md` — Phase 3a locked decisions

### Secondary (MEDIUM confidence)
- `.planning/phases/11-scheduler-tool-surface/11-CONTEXT.md` — Phase 11 decisions
- `.planning/REQUIREMENTS.md` — SCHED-01/02/03 requirements

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — all components are existing Phase 3a code or well-established patterns
- Architecture: HIGH — action-based tool pattern fully established via BuiltinMessageToolSurface; dispatcher pattern via post_notification()
- Pitfalls: HIGH — all pitfalls identified from Phase 3a decisions and code review

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (30 days — scheduler infrastructure is stable, only surface layer being added)
