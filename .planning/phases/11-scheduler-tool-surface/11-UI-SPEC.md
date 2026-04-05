---
phase: 11
slug: scheduler-tool-surface
status: draft
created: 2026-04-05
---

# Phase 11 — UI Design Contract

> Backend-only phase (builtin tool + HTTP API). No new UI components.
> API contracts documented here for Phase 13 WebUI consumption.

---

## HTTP API Contract (Phase 11 Deliverable)

REST endpoint consumed by Phase 13 WebUI.

### Base Path
`/api/scheduler/tasks`

### Owner Binding
All requests use `X-Session-ID` header to identify the task owner (session_id).

### Endpoints

#### `GET /api/scheduler/tasks`
List all tasks for the owner.

**Request headers:**
```
X-Session-ID: {session_id}
```

**Response `200`:**
```json
{
  "tasks": [
    {
      "task_id": "uuid-string",
      "owner": "session_id",
      "schedule": {
        "kind": "cron" | "interval" | "one_shot",
        "spec": {
          "cron_expr"?: string,
          "interval_seconds"?: float,
          "fire_at"?: float
        }
      },
      "persist": true,
      "misfire_policy": "skip" | "fire_once",
      "next_fire_at": 1712345678.0,
      "enabled": true,
      "metadata": {}
    }
  ]
}
```

Field notes:
- `schedule.spec` structure varies by `kind`:
  - `cron`: `{ "cron_expr": "0 9 * * *", "tz": "Asia/Shanghai" }`
  - `interval`: `{ "interval_seconds": 3600.0 }`
  - `one_shot`: `{ "fire_at": 1712345678.0 }`
- `next_fire_at` is a Unix timestamp float (seconds since epoch)

#### `POST /api/scheduler/tasks`
Create a new scheduled task.

**Request headers:**
```
X-Session-ID: {session_id}
Content-Type: application/json
```

**Request body:**
```json
{
  "schedule": {
    "kind": "cron",
    "spec": { "cron_expr": "0 9 * * *", "tz": "Asia/Shanghai" }
  },
  "persist": true,
  "misfire_policy": "skip",
  "note": "optional notification content"
}
```

**Response `201`:**
```json
{
  "task_id": "uuid-string",
  "owner": "session_id",
  "schedule": { "kind": "cron", "spec": { "cron_expr": "0 9 * * *", "tz": "Asia/Shanghai" } },
  "persist": true,
  "misfire_policy": "skip",
  "next_fire_at": 1712345678.0,
  "enabled": true,
  "metadata": { "note": "optional notification content" }
}
```

**Error responses:**
- `400`: Invalid schedule spec or missing required fields
- `422`: Unprocessable entity (malformed cron expression, etc.)

#### `DELETE /api/scheduler/tasks/{task_id}`
Cancel (delete) a scheduled task.

**Request headers:**
```
X-Session-ID: {session_id}
```

**Response `200`:**
```json
{
  "message": "Task cancelled",
  "task_id": "uuid-string"
}
```

**Error responses:**
- `404`: Task not found or not owned by requester

---

## LLM Tool Schema (Phase 11 Deliverable)

Single `scheduler` builtin tool with `action` enum.

```json
{
  "name": "scheduler",
  "description": "Create, list, or cancel scheduled tasks. Tasks persist across restarts.",
  "parameters": {
    "type": "object",
    "properties": {
      "action": {
        "type": "string",
        "enum": ["create", "list", "cancel"],
        "description": "The operation to perform"
      },
      "schedule": {
        "type": "object",
        "description": "Required for action=create",
        "properties": {
          "kind": {
            "type": "string",
            "enum": ["cron", "interval", "one_shot"]
          },
          "spec": {
            "type": "object",
            "description": "Schedule specification"
          }
        },
        "required": ["kind", "spec"]
      },
      "task_id": {
        "type": "string",
        "description": "Required for action=cancel"
      },
      "note": {
        "type": "string",
        "description": "Optional notification content sent when task fires"
      }
    },
    "required": ["action"]
  }
}
```

### Action Details

| Action | Required Params | Returns |
|--------|-----------------|---------|
| `create` | `schedule` (kind + spec) | `{ task_id, schedule, next_fire_at, ... }` |
| `list` | none | `{ tasks: [...] }` |
| `cancel` | `task_id` | `{ message, task_id }` |

---

## Phase 11 Scope Summary

| Deliverable | Status |
|-------------|--------|
| `scheduler` builtin tool (LLM-facing) | Phase 11 implements |
| HTTP API `/api/scheduler/tasks` | Phase 11 implements |
| WebUI scheduler page | Phase 13 implements (consumes this API) |
