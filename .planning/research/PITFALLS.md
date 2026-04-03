# Pitfalls Research

**Domain:** Chatbot runtime infrastructure (AcaBot v2 milestone)
**Researched:** 2026-04-02
**Confidence:** HIGH — grounded in codebase analysis and known failure patterns for asyncio/LanceDB/plugin systems

## Critical Pitfalls

### Pitfall 1: Plugin Reconciler State Desync Between Spec and Status

**What goes wrong:**
When replacing the monolithic `plugin_manager.py` (972 lines) with a Reconciler (Package + Spec + Status), the Status often drifts from Spec during error recovery. A plugin Spec says "enabled" but Status is stuck in "errored" from a failed load — and the reconciler never retries because it thinks the desired state matches. Users see a plugin listed as enabled in WebUI but it's actually dead.

**Why it happens:**
Reconciler patterns borrowed from Kubernetes work because K8s has robust retry/backoff built into every controller. A naive reconciler loop that only reacts to Spec changes (not periodic re-sync) will miss transient failures. Also: the old `plugin_manager.py` has implicit ordering dependencies between plugins (e.g., `BackendBridgeToolPlugin` depends on `ComputerRuntime` being ready) that get lost when moving to declarative reconciliation.

**How to avoid:**
- Reconciler must re-sync on a timer (e.g., every 60s), not just on Spec changes
- Status must include `last_error`, `retry_count`, `last_reconciled_at` — not just a state enum
- Define explicit dependency ordering in Spec (not implicit import-time ordering)
- Keep the `BackendBridgeToolPlugin` transition path tested: load order must be deterministic during migration

**Warning signs:**
- Plugin shows "enabled" in WebUI but its tools don't appear in ToolBroker
- `RuntimePluginContext` fields are None/uninitialized for a supposedly-loaded plugin
- Tests pass with single plugin but fail with multiple plugins loaded

**Phase to address:**
Plugin reconciler implementation phase. Status schema design is the critical first decision.

---

### Pitfall 2: Phantom Plugin Registrations After Hot Reload

**What goes wrong:**
Old plugin's tools/hooks remain registered in ToolBroker after unload or reload. The reconciler unloads the plugin (calls `teardown()`), but the ToolBroker still has stale `ToolDef` entries pointing to dead handlers. LLM calls the tool, gets a cryptic error or silent no-op.

**Why it happens:**
Current `plugin_manager.py` registers tools via `ToolBroker.register()` but there's no transactional "unregister all tools from plugin X" operation. Tool ownership is implicit. During reload, if the new version registers tools with different names, the old names become zombies.

**How to avoid:**
- ToolBroker must track tool ownership by `plugin_id` (not by import path, which the refactor is changing)
- Implement `ToolBroker.unregister_by_owner(plugin_id)` — called atomically before re-registration
- Same pattern for hooks in the hook registry
- Integration test: reload a plugin that changes its tool list, verify old tools are gone

**Warning signs:**
- `ToolBroker.list_tools()` returns tools whose handlers raise `AttributeError` or reference garbage-collected objects
- Tool count grows monotonically across reloads

**Phase to address:**
Plugin reconciler phase — ToolBroker ownership tracking is a prerequisite for safe reload.

---

### Pitfall 3: Unified Message Tool Overwhelms LLM Context

**What goes wrong:**
Giving the LLM a single `message` tool with every capability (reply, reaction, recall, cross-session send, file attachment, text-to-image, quote) creates a tool schema so complex that the LLM hallucinates parameters, picks wrong actions, or wastes tokens parsing the schema. Worse: the LLM starts using `message(action="send", target="other_session")` unprompted, spamming channels.

**Why it happens:**
Developers design the API for completeness ("one tool to rule them all") instead of for LLM usability. LLMs struggle with union-typed parameters and large enum action fields. The "platform abstraction" tries to hide OneBot v11 details but leaks them (e.g., QQ message segment types, message IDs that are platform-specific).

**How to avoid:**
- Split into 2-3 tools max: `reply` (common path), `send_message` (cross-session, restricted), `react` (lightweight)
- Each tool should have < 5 parameters. If you need a `type` enum, keep it to 3-4 values
- Default behavior should be "reply to current conversation" with zero required params beyond content
- Gate dangerous capabilities (cross-session send) behind session-config policy, not just LLM judgment
- Test with actual LLM calls: if the model gets it wrong >10% of the time, the schema is too complex

**Warning signs:**
- LLM frequently sends `action: "recall"` when it meant `action: "reply"`
- Tool call failures spike after adding message tool (check pipeline error logs)
- LLM starts sending messages to other sessions without being asked

**Phase to address:**
Message tool design phase. Schema simplicity must be validated with real LLM testing before committing to implementation.

---

### Pitfall 4: Platform Abstraction Leak in Message Tool

**What goes wrong:**
The message tool wraps OneBot v11 message segments (CQ codes, `[CQ:image,file=...]`) behind an "abstract" interface, but edge cases leak through: image upload requires knowing NapCat's file path conventions, message IDs for quote/recall are NapCat-specific int64s, group vs. private distinction maps 1:1 to QQ semantics. When a second platform is added, the abstraction breaks everywhere.

**Why it happens:**
AcaBot currently only has NapCat as a gateway. It's tempting to model the abstraction around what NapCat supports. The PROJECT.md says "平台无关但只需 OneBot v11 实现" — but "platform-agnostic design" without a second platform to validate against is just OneBot v11 with extra indirection.

**How to avoid:**
- Accept that the abstraction will be OneBot-flavored and document that explicitly
- Use opaque message IDs (string type) at the tool layer; let the gateway translate
- Don't expose platform-specific capabilities (e.g., QQ-specific "poke") through the unified tool — put those in a platform extension
- Keep the gateway adapter interface thin: `send(target, segments)`, `react(target, msg_id, emoji)`, `recall(target, msg_id)` — 3 methods max

**Warning signs:**
- Message tool parameters include QQ-specific fields (group_id, user_id as int64)
- Tool handler imports from `acabot.gateway.napcat` directly instead of going through `GatewayProtocol`
- Adding a hypothetical Discord gateway would require changing the tool schema

**Phase to address:**
Message tool design phase. Define GatewayProtocol extension first, then build tool on top.

---

### Pitfall 5: Asyncio Scheduler Task Leaks on Shutdown

**What goes wrong:**
Scheduled tasks (cron-like or delayed) are created via `asyncio.create_task()` or `loop.call_later()` but not tracked. On shutdown, `RuntimeApp.stop()` completes but orphaned tasks continue running, holding references to already-torn-down subsystems (DB connections, gateway). Results: `RuntimeError: Event loop is closed`, corrupted writes, or the process hangs.

**Why it happens:**
The codebase already has this pattern: `napcat.py:142` uses `asyncio.create_task` fire-and-forget for event dispatch (noted in CONCERNS.md 4.3). A scheduler will create many more such tasks. Without a `TaskGroup` or manual registry, there's no way to cancel them all at shutdown.

**How to avoid:**
- Scheduler must maintain a `set[asyncio.Task]` of all active tasks with `task.add_done_callback(tasks.discard)`
- `Scheduler.stop()` must `cancel()` all tasks and `await asyncio.gather(*tasks, return_exceptions=True)`
- Use `asyncio.TaskGroup` (Python 3.11+) for grouped task lifecycle where possible
- Shutdown order: scheduler stops first (cancels pending work) → plugins unload → subsystems tear down → gateway disconnects
- Add a shutdown timeout: if tasks don't cancel within 5s, log and force-exit

**Warning signs:**
- Process hangs on SIGTERM / Ctrl+C
- "Event loop is closed" errors in logs during shutdown
- Tasks reference torn-down objects (gateway, DB) → `AttributeError` in logs

**Phase to address:**
Scheduler implementation phase. Task tracking is the first thing to build, not an afterthought.

---

### Pitfall 6: Scheduler Timer Drift Under Load

**What goes wrong:**
A "run every 5 minutes" task actually runs at 5:00, 10:03, 15:08... because each iteration awaits the task completion before scheduling the next. Under heavy LLM pipeline load (which dominates the event loop), `asyncio.sleep(300)` can overshoot significantly because the loop is blocked on synchronous LLM/DB calls.

**Why it happens:**
Naive implementation: `while True: await do_work(); await asyncio.sleep(interval)`. The sleep starts after work completes, so interval = work_time + sleep_time. Also: any blocking call in the event loop (LanceDB full-table scans are sync, noted in CONCERNS.md 2.4/3.1) delays all pending coroutines including timer wakeups.

**How to avoid:**
- Schedule from absolute time: `next_run = start + n * interval`, sleep until `next_run - now()`
- If a run takes longer than the interval, skip the missed tick (don't pile up)
- Run LanceDB operations in `loop.run_in_executor()` to avoid blocking the loop
- Log actual vs. expected execution times to detect drift early

**Warning signs:**
- Scheduled tasks consistently run late (check timestamps in structured logs)
- Bot becomes unresponsive during LTM ingestion or LanceDB compaction

**Phase to address:**
Scheduler implementation phase.

---

### Pitfall 7: LanceDB Concurrent Write Corruption

**What goes wrong:**
Two concurrent operations (e.g., LTM ingestion + user-triggered delete via WebUI) both call `_rewrite_table()` which does full-table overwrite (`create_table(..., mode="overwrite")`). The second write silently overwrites the first, losing data. Or worse: concurrent Arrow file writes corrupt the LanceDB directory, resulting in unreadable tables on next startup.

**Why it happens:**
LanceDB (file-based, single-process) has no built-in write locking. The current code (CONCERNS.md 2.4) already uses full-table rewrite for every mutation. There's no `asyncio.Lock` protecting LTM storage (unlike SQLite stores which have `self._lock`). Multiple pipeline runs can trigger LTM operations concurrently.

**How to avoid:**
- Add an `asyncio.Lock` per LanceDB table (entries, cursors, failed_windows) — same pattern as `sqlite_stores.py`
- Run `_rewrite_table()` in `loop.run_in_executor()` (it's CPU-bound Arrow serialization) but hold the lock across the entire read-modify-write
- Add a checksum or row-count verification after rewrite: read back and compare
- Log every rewrite with before/after row counts — makes data loss immediately visible

**Warning signs:**
- LTM entry count decreases unexpectedly (entries silently dropped)
- `pyarrow.lib.ArrowInvalid` errors on table open after crash
- Duplicate entries appearing (concurrent inserts both read the same snapshot)

**Phase to address:**
LTM safety phase. The lock is a 10-line fix but must be done before any other LTM work.

---

### Pitfall 8: LanceDB Backup Captures Inconsistent Snapshot

**What goes wrong:**
Backup copies the `runtime_data/ltm/` directory while a `_rewrite_table()` is in progress. The backup contains a mix of old and new Arrow fragment files. Restoring from this backup produces a corrupt or incomplete table.

**Why it happens:**
LanceDB stores data as multiple files (manifest + fragments). A file-level copy isn't atomic. Unlike SQLite (which has `.backup()` API), LanceDB has no built-in snapshot mechanism.

**How to avoid:**
- Acquire the write lock before backup, or use filesystem-level snapshots (ZFS/btrfs/LVM)
- Alternative: backup by reading all entries through the API (`to_arrow().to_pylist()`) and serializing to JSON/Parquet — slower but guaranteed consistent
- Never backup by `cp -r` on a live database
- Test backup restore as part of the backup implementation — don't ship backup without restore verification

**Warning signs:**
- Restored database has fewer entries than expected
- `lance` format errors on startup after restore

**Phase to address:**
LTM safety phase.

---

### Pitfall 9: Logging Overhaul Creates Log Spam That Hides Real Errors

**What goes wrong:**
Adding structured logging to tool calls, LTM operations, and pipeline stages generates so much output that actual errors (gateway disconnects, LLM API failures, data corruption) get buried. The log buffer (`log_buffer.py`, in-memory ring) fills with routine info and pushes out error context.

**Why it happens:**
The current logging is "too simple" (CONCERNS.md 5.3). The natural overcorrection is to log everything at INFO level. Tool call logs are especially noisy: each pipeline run may invoke 5-10 tools, each with input/output logging. Multiply by concurrent sessions.

**How to avoid:**
- Tool call summaries at INFO (tool name + duration + success/fail); full input/output at DEBUG only
- LTM operations at DEBUG except errors
- Pipeline stage transitions at INFO (5-6 log lines per run, not 50)
- Set log buffer to retain ERRORs longer than INFO (priority-weighted eviction)
- Add `run_id` / `thread_id` as structured fields for correlation, but don't include full message content in log fields (PII + size)

**Warning signs:**
- Log buffer fills in < 1 minute during active conversation
- Operators can't find error logs without grep
- Log output exceeds 1MB/minute during normal operation

**Phase to address:**
Logging overhaul phase. Define log levels and volume budget before implementing.

---

### Pitfall 10: Structured Logging Performance Hit from Serialization

**What goes wrong:**
Moving from `logger.info(f"...")` to `logger.info("...", extra={"tool_input": large_dict, "llm_response": long_string})` causes measurable latency because the logging framework serializes large objects even when the log level is filtered out (e.g., DEBUG logs still serialize in production). The LTM and pipeline hot paths slow down.

**Why it happens:**
Python's `logging` module evaluates arguments eagerly. If `extra` contains large dicts (tool inputs can be multi-KB), the serialization cost is paid even if no handler processes the record.

**How to avoid:**
- Use lazy evaluation: `logger.debug("tool result", extra={"result": lambda: serialize(result)})` or check `logger.isEnabledFor(logging.DEBUG)` before constructing expensive extra fields
- Cap serialized field sizes: truncate tool output to 500 chars in log records
- Benchmark before/after: measure pipeline latency with logging enabled vs. disabled
- Don't log full LLM responses at any level above DEBUG

**Warning signs:**
- Pipeline latency increases 10%+ after logging changes
- Memory usage spikes correlate with log volume

**Phase to address:**
Logging overhaul phase.

---

### Pitfall 11: Reference Backend Removal Leaves Dangling Imports and Dead Config

**What goes wrong:**
Deleting `src/acabot/runtime/references/` and `plugins/reference_tools.py` but missing one of the 14+ files that import `ReferenceBackend`. The bot crashes on startup with `ImportError` or `AttributeError`. Or: existing `config.yaml` files in the wild still have `reference_backend` config sections, causing config parse errors.

**Why it happens:**
`ReferenceBackend` is wired into: `plugin_manager.py` (RuntimePluginContext), `app.py`, `bootstrap/components.py`, `bootstrap/builders.py`, `control/control_plane.py`, `control/reference_ops.py`, `plugins/reference_tools.py`, `references/*` (4 files), and `__init__.py` re-exports. That's 14 files touching a single subsystem. Missing even one causes a startup crash.

**How to avoid:**
- Use `grep -r "reference_backend\|ReferenceBackend\|reference_tools\|references" src/` to find ALL references before deleting anything
- Remove in dependency order: tools → plugin context field → control plane ops → bootstrap → app → module directory
- Make config parsing tolerate unknown keys (or add explicit migration: log warning + ignore `reference_backend` section)
- Add a startup smoke test: `python -c "from acabot.runtime import RuntimeApp"` in CI

**Warning signs:**
- `ImportError` on startup after merge
- Config validation errors for existing deployments
- WebUI reference management page still in routes (404 but confusing)

**Phase to address:**
Reference Backend removal phase. Do this as an atomic PR with comprehensive grep verification.

---

### Pitfall 12: Removing Reference Backend Breaks BackendBridgeToolPlugin During Migration

**What goes wrong:**
`BackendBridgeToolPlugin` (which PROJECT.md says must remain usable during transition) depends on `RuntimePluginContext.reference_backend`. Removing references before the plugin reconciler provides an alternative breaks the bridge plugin. Operators using BackendBridge lose functionality with no migration path.

**Why it happens:**
The constraint "BackendBridgeToolPlugin 过渡期可用" conflicts with "删除 Reference Backend." If both are in the same milestone, the ordering matters critically: bridge plugin must be migrated or decoupled first.

**How to avoid:**
- Audit BackendBridgeToolPlugin's actual usage of `reference_backend` — does it use it at all, or just receive it in context?
- If it uses references: decouple first, then delete
- If it doesn't: remove the field from context, verify bridge still works, then delete references
- Order the work: bridge plugin audit → reference removal → plugin reconciler

**Warning signs:**
- BackendBridgeToolPlugin listed in active session configs but reference backend already deleted
- Plugin load errors mentioning missing context fields

**Phase to address:**
Must be resolved before or at the start of the Reference Backend removal phase.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| LanceDB full-table rewrite for every mutation | Correct behavior, simple code | O(N) per write, data loss risk under concurrency | Only until entry count < 1000 and concurrent writes are locked |
| Single `asyncio.Lock` for all LanceDB ops | Prevents corruption | Serializes all LTM operations, blocking pipeline under load | Until read/write separation is needed |
| Fire-and-forget `asyncio.create_task` for events | Simple dispatch | Task leaks, lost errors, no backpressure | Never in scheduler; OK for one-shot event handlers with error logging |
| OneBot v11-specific message tool internals | Ships faster | Rewrite needed for second platform | Acceptable if the gateway adapter interface is clean |
| Logging everything at INFO | Visible during development | Log spam in production, performance cost | Only during initial development/debugging of new subsystems |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| LanceDB + asyncio | Calling LanceDB sync APIs on the event loop, blocking all coroutines | Run all LanceDB I/O in `loop.run_in_executor()` with a thread pool |
| ToolBroker + Plugin lifecycle | Registering tools but not cleaning up on unload | Track tool ownership by plugin_id, unregister atomically |
| Scheduler + RuntimeApp shutdown | Scheduler tasks outlive the resources they depend on | Shutdown scheduler first; cancel and await all tasks before tearing down subsystems |
| NapCat gateway + message tool | Coupling message tool directly to NapCat WebSocket API format | Route through `GatewayProtocol`; message tool should never import `napcat` |
| Config parsing + subsystem removal | Old config files break on startup after removing a subsystem | Config parser must ignore/warn on unknown sections, not crash |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| FTS index rebuild on every LTM write | LTM writes take 100ms+ as entry count grows | Rebuild FTS only on batch completion, not per-entry | >500 entries |
| Semantic search full-table scan (10k limit) | Search latency >1s, memory spike | Build ANN index, or at minimum pre-filter by structured fields before vector math | >2000 entries |
| Logging serialization on hot path | Pipeline latency regression | Lazy evaluation, size caps, level checks | >10 tool calls per pipeline run |
| Scheduler polling with `asyncio.sleep` | Timer drift, missed windows | Absolute-time scheduling, skip missed ticks | Under sustained LLM load (loop saturation) |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Message tool allows cross-session send without policy check | LLM spams unrelated channels/users | Gate cross-session messaging behind session-config `allow_cross_send` flag |
| LTM filter injection via `_quote_sql_text()` | Attacker crafts message content that breaks SQL-like filter | Parameterized queries if LanceDB supports them; otherwise fuzz-test the escaping |
| Scheduler tasks run with full `RuntimePluginContext` permissions | A malicious plugin's scheduled task gets computer access | Scheduled tasks inherit the plugin's permission scope, not global |
| Log records contain full message content | PII leakage in log files/buffer | Truncate user content in logs; never log at INFO+ level |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Plugin shows "enabled" but is actually errored | Operator thinks bot has capability it doesn't | Status must show actual state with last error; WebUI should show red indicator |
| Message tool schema too complex for LLM | Bot fails to send messages correctly, confusing end users | Max 5 params per tool; test with real LLM before shipping |
| Scheduled task fails silently | Expected automated actions never happen, no notification | Scheduler must surface task errors to operator (log + optional notification) |
| Subsystem removal breaks config without migration | Bot won't start after update; operator doesn't know why | Config migration: warn on unknown keys, provide upgrade guide |

## "Looks Done But Isn't" Checklist

- [ ] **Plugin reconciler:** Often missing periodic re-sync — verify reconciler retries failed states on timer, not just on spec change
- [ ] **Plugin reload:** Often missing tool cleanup — verify ToolBroker has zero stale tools after reload (count tools before/after)
- [ ] **Message tool:** Often missing LLM usability testing — verify LLM correctly uses tool in 90%+ of test prompts
- [ ] **Scheduler:** Often missing shutdown cleanup — verify `Ctrl+C` exits cleanly within 5s with no "event loop closed" errors
- [ ] **Scheduler:** Often missing drift handling — verify tasks scheduled for T+300s actually run within T+305s under load
- [ ] **LTM safety:** Often missing concurrent write protection — verify two simultaneous writes don't lose data (write integration test)
- [ ] **LTM backup:** Often missing restore verification — verify backed-up data actually restores to a working state
- [ ] **Logging:** Often missing volume control — verify log output stays under 1MB/min during active conversation
- [ ] **Reference removal:** Often missing import sweep — verify `grep -r "ReferenceBackend\|reference_backend" src/` returns zero results after removal
- [ ] **Reference removal:** Often missing config migration — verify old config.yaml files still parse without errors

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Plugin state desync | LOW | Force-reconcile all plugins: set all Status to "unknown", let reconciler re-evaluate |
| Stale tools in ToolBroker | LOW | Full restart clears ToolBroker; add `ToolBroker.clear_all()` for hot recovery |
| LLM abusing message tool | MEDIUM | Add rate limiting to message tool; restrict to reply-only via session config; re-prompt LLM with tighter instructions |
| Scheduler task leak on shutdown | LOW | Kill process (tasks die with it); fix the registry for next release |
| LanceDB data corruption | HIGH | Restore from backup; if no backup, re-ingest from source threads (expensive). This is why backup must ship with LTM safety |
| LanceDB inconsistent backup | HIGH | No recovery without re-ingestion. Prevention is the only strategy |
| Log spam burying errors | LOW | Adjust log levels in config; filter by severity in WebUI log viewer |
| Reference removal import crash | LOW | Revert the removal commit; re-do with comprehensive grep |
| BackendBridge broken by premature removal | MEDIUM | Re-add `reference_backend` field to context as `None`; bridge must handle None gracefully |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Plugin state desync | Plugin reconciler | Reconciler retries errored plugins within 60s |
| Phantom tool registrations | Plugin reconciler | Tool count is stable across reload cycles |
| Message tool LLM confusion | Message tool design | 90%+ success rate in LLM tool-call test suite |
| Platform abstraction leak | Message tool design | Message tool has zero imports from `gateway.napcat` |
| Scheduler task leaks | Scheduler implementation | Clean shutdown completes in <5s, zero orphan tasks |
| Timer drift | Scheduler implementation | Scheduled tasks run within 5s of expected time under load |
| LanceDB write corruption | LTM safety (must be first) | Concurrent write stress test passes with zero data loss |
| LanceDB backup consistency | LTM safety | Backup-restore round-trip preserves all entries |
| Log spam | Logging overhaul | Log volume <1MB/min under normal load |
| Logging perf hit | Logging overhaul | Pipeline latency delta <5% with logging enabled |
| Dangling reference imports | Reference Backend removal | `grep` returns zero matches post-removal |
| BackendBridge breakage | Reference Backend removal | Bridge plugin loads and functions after reference removal |

## Sources

- AcaBot codebase analysis: `plugin_manager.py`, `storage.py`, `napcat.py`, `app.py`
- `.planning/codebase/CONCERNS.md` — known fragile areas and tech debt
- LanceDB documentation: file-based storage lacks write locking and atomic backup
- Python asyncio patterns: TaskGroup (3.11+), shutdown ordering, timer drift
- LLM tool-use best practices: schema simplicity, parameter count limits, union-type avoidance

---
*Pitfalls research for: AcaBot v2 runtime infrastructure milestone*
*Researched: 2026-04-02*
