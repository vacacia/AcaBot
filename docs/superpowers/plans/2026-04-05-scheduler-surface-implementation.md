# Scheduler Surface Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a typed scheduler facade where model-created tasks wake the bound conversation via synthetic events, while plugin scheduling gets a reserved facade/API without exposing raw callbacks.

**Architecture:** Keep `RuntimeScheduler` as the low-level timer engine and add a scheduler service layer that owns task semantics, owner validation, schedule codec, and callback reconstruction. The builtin scheduler tool and plugin context both talk to the service/facades rather than directly to low-level scheduler callbacks.

**Tech Stack:** Python, pytest, existing RuntimeScheduler, RuntimeControlPlane synthetic event injection, ToolBroker builtin tool registration.

---

## File Structure

- Create: `src/acabot/runtime/scheduler/codec.py` — schedule payload parse/serialize helpers
- Create: `src/acabot/runtime/scheduler/service.py` — typed task facade and callback rebinding
- Create: `src/acabot/runtime/scheduler/conversation_wakeup.py` — fire-time synthetic event callback builder
- Modify: `src/acabot/runtime/scheduler/__init__.py` — export new scheduler facade pieces
- Modify: `src/acabot/runtime/builtin_tools/scheduler.py` — builtin tool wired to service
- Modify: `src/acabot/runtime/builtin_tools/__init__.py` — register scheduler builtin tool
- Modify: `src/acabot/runtime/bootstrap/__init__.py` — instantiate service and inject into builtin/plugin context
- Modify: `src/acabot/runtime/plugin_protocol.py` — add plugin scheduler facade type/field
- Modify: `src/acabot/runtime/plugin_runtime_host.py` — use plugin facade owner semantics on unload
- Modify: `src/acabot/runtime/control/control_plane.py` — expose an internal scheduler synthetic event injector for wakeup callbacks
- Create/Modify tests under `tests/runtime/` for codec, service, wakeup, builtin tool, bootstrap wiring

### Task 1: Schedule Codec
- [ ] Write failing tests for payload -> schedule parsing and schedule -> payload serialization
- [ ] Run targeted pytest and verify failures
- [ ] Implement minimal `codec.py`
- [ ] Run targeted pytest and verify pass

### Task 2: Conversation Wakeup Executor
- [ ] Write failing tests proving a callback injects a scheduler-originated synthetic event into the bound conversation
- [ ] Run targeted pytest and verify failures
- [ ] Implement minimal `conversation_wakeup.py`
- [ ] Run targeted pytest and verify pass

### Task 3: ScheduledTaskService
- [ ] Write failing tests for create/list/cancel, owner isolation, metadata kind handling, and callback reconstruction
- [ ] Run targeted pytest and verify failures
- [ ] Implement minimal `service.py`
- [ ] Run targeted pytest and verify pass

### Task 4: Builtin Scheduler Tool
- [ ] Write failing tests for tool registration and tool -> service integration
- [ ] Run targeted pytest and verify failures
- [ ] Implement builtin tool changes and registration wiring
- [ ] Run targeted pytest and verify pass

### Task 5: Plugin Facade Wiring
- [ ] Write failing tests that plugin context exposes scheduler facade and unload cleanup uses plugin owner namespace
- [ ] Run targeted pytest and verify failures
- [ ] Implement plugin facade wiring without fire-time plugin handler execution
- [ ] Run targeted pytest and verify pass

### Task 6: Bootstrap / Recovery Wiring
- [ ] Write failing tests proving runtime components wire scheduler service and builtin scheduler tool registration
- [ ] Run targeted pytest and verify failures
- [ ] Implement bootstrap wiring and persisted callback rebinding
- [ ] Run targeted pytest and verify pass

### Task 7: Final Verification
- [ ] Run focused scheduler/runtime test set
- [ ] Review diffs for requirement alignment
- [ ] Only then report status
