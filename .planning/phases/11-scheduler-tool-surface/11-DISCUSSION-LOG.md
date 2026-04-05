# Phase 11: Scheduler Tool Surface - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 11-Scheduler Tool Surface
**Areas discussed:** Tool Schema, HTTP API, Callback Mechanism

---

## Tool Schema

| Option | Description | Selected |
|--------|-------------|----------|
| AstrBot style: 3 separate tools | create_future_task / delete_future_task / list_future_tasks, cron_expression OR run_at + run_once | |
| **OpenClaw style: single tool + action enum** | One scheduler tool, action enum (create/list/cancel), discriminated union schedule | ✓ |
| Custom: 3 tools + separate schedule fields | Separate schedule_type + fields, not cron string or ISO datetime | |

**User's choice:** OpenClaw style: single tool + action enum
**Notes:** User wanted to see OpenClaw and AstrBot research first

---

## Schedule Format

| Option | Description | Selected |
|--------|-------------|----------|
| OpenClaw: kind + spec separated | {type: "cron", spec: {expr, tz?}} / {type: "interval", spec: {seconds}} / {type: "one_shot", spec: {fire_at}} | ✓ |
| Simplified: type + fields directly | {type: "cron", cron_expr, tz?} / {type: "interval", seconds} / {type: "one_shot", fire_at} | |

**User's choice:** OpenClaw: kind + spec separated

---

## HTTP API Owner Binding

| Option | Description | Selected |
|--------|-------------|----------|
| Header-based: X-Session-ID | WebUI passes owner via X-Session-ID header, backend binds server-side | ✓ |
| Query param: ?owner=session_id | Explicit owner in URL | |

**User's choice:** Header-based (X-Session-ID)
**Notes:** This was deferred to research in first attempt; user selected after research results presented

---

## Callback Mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| **ScheduledMessageDispatcher intermediate layer** | Callback captures conversation_id (not TEC), dispatcher uses post_notification() pattern, callback reconstructed on persist recovery | ✓ |
| Direct message in callback | Simple but violates Phase 3a TEC constraint | |
| Trigger LLM re-run | Most powerful but out of Phase 11 scope | |

**User's choice:** ScheduledMessageDispatcher
**Notes:** Follows State.md constraint that callback must NOT capture ToolExecutionContext

---

## OpenClaw and AstrBot Research

User requested research on OpenClaw and AstrBot scheduler tool schemas before deciding.

**AstrBot findings:**
- 3 separate tools: create_future_task / delete_future_task / list_future_tasks
- cron_expression OR run_at + run_once (mutually exclusive)
- job_id auto-generated, returned on create

**OpenClaw findings:**
- Single cron tool with 8 actions: add/list/remove/update/run/runs/wake/status
- Discriminated union schedule: {kind: "cron", expr} | {kind: "at", atMs} | {kind: "every", everyMs}
- Loose schema surface (additionalProperties: true), runtime validation
- Session targets: main | isolated | current | session:custom-id

## Claude's Discretion

- croniter library (Phase 3a decision)
- SQLite table schema details
- Tool handler error handling
- Whether list returns created_at / last_fire_at fields

## Deferred Ideas

None — all gray areas resolved in this discussion session.

---
