# Phase 1: Reference Backend Removal - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-03
**Phase:** 01-reference-backend-removal
**Areas discussed:** Deletion scope (single area — user pre-empted all gray areas with one directive)

---

## Deletion Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Gradual deprecation | Mark deprecated, remove over multiple phases | |
| Partial removal + compatibility shims | Delete core but keep None placeholders for downstream | |
| Complete erasure | Delete everything, as if it never existed | ✓ |

**User's choice:** Complete erasure — "就当 Reference Backend subsystem 从来不存在"

**Notes:** User pre-empted all three gray areas (BackendBridge transition, config handling, context field) with a single directive: treat it as if it never existed. No compatibility shims, no deprecated markers, no None placeholders. This collapses all gray areas into one clear decision.

---

## Claude's Discretion

- Deletion ordering (leaves-first or roots-first)
- Commit granularity (one big commit vs multiple atomic commits)

## Deferred Ideas

None — discussion stayed within phase scope
