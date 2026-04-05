# Scheduler Tool Surface Design

**Date:** 2026-04-05
**Status:** Approved for implementation

## Goal

Make scheduler usable from the model side while preserving a clean path for future plugin scheduling.

## Decisions

- Model-facing scheduled tasks are **typed jobs**, not arbitrary public callbacks.
- The first implemented job kind is **`conversation_wakeup`**.
- A `conversation_wakeup` task is bound to the originating `conversation_id`.
- When such a task fires, runtime injects a **synthetic scheduled event** into the same conversation and lets the normal agent pipeline handle it.
- Plugin scheduling uses a **facade API**, not raw `RuntimeScheduler.register(callback=...)`.
- Plugin-facing `plugin_handler` tasks are **reserved in the schema this round**, but fire-time execution is deferred.
- `owner` is a visibility/authorization boundary, not a behavior type.
  - model tasks: `owner = conversation_id`
  - plugin tasks: `owner = plugin:{plugin_id}`
- Schedule parsing/serialization must be centralized in shared scheduler codec helpers.

## Architecture

### Layers

1. **`RuntimeScheduler`**
   - low-level timer engine
   - persistence, misfire handling, callback triggering
   - unaware of model/plugin business semantics

2. **`ScheduledTaskService`**
   - public runtime-facing scheduler facade
   - validates and parses schedule payloads
   - enforces owner rules
   - creates/list/cancels typed tasks
   - rebuilds fire-time callbacks from persisted metadata

3. **Fire-time executors**
   - `conversation_wakeup`: implemented now
   - `plugin_handler`: schema reserved, execution deferred

4. **Adapters**
   - builtin `scheduler` tool calls `ScheduledTaskService`
   - plugin context exposes `PluginScheduler` facade

## Data Model

Top-level persisted task fields:

- `task_id`
- `owner`
- `schedule`
- `persist`
- `misfire_policy`
- `metadata`

`metadata.kind` is required and determines fire-time behavior.

### `conversation_wakeup` metadata

- `kind = "conversation_wakeup"`
- `conversation_id`
- `note`
- `created_by = "llm_tool"`
- `source = "builtin:scheduler"`
- optional timestamps / labels

### `plugin_handler` metadata

- `kind = "plugin_handler"`
- `plugin_id`
- `handler_name`
- `payload`
- `created_by = "plugin"`

## Fire-time Behavior

For `conversation_wakeup`:

1. Scheduler fires callback.
2. Callback resolves the bound `conversation_id`.
3. Runtime injects a synthetic inbound event into that conversation.
4. Event metadata marks it as scheduler-originated.
5. Normal router / session / pipeline handles it.

This is intentionally **not** the same as directly sending a static notification.

## Testing Strategy

- scheduler codec round-trip tests
- service tests for create/list/cancel and owner isolation
- conversation wakeup tests proving synthetic event injection into the bound conversation
- builtin tool tests proving tool -> service integration
- bootstrap/plugin context tests proving facades are wired

## Deferred

- fire-time execution of `plugin_handler`
- richer delivery modes
- edit/update existing tasks
- advanced WebUI task creation semantics
