# Phase 06: Runtime Infra Artifact Backfill - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning
**Mode:** Auto-generated from roadmap + research + audit evidence

<domain>
## Phase Boundary

Backfill GSD evidence for the already-delivered scheduler, LTM data safety, and logging / observability work. This phase closes the audit blockers for `3a-scheduler`, `3b-ltm-data-safety`, and `3c-logging-observability`.

This phase is about evidence reconstruction, verification repair, and phase close-out. It is not a feature-design phase.

Explicit in-scope work:
- add the missing Phase 06 context so autonomous workflow can proceed
- keep the current `06-01` to `06-04` plan split and only do minimal fixes needed to execute it
- backfill `SUMMARY.md`, `VERIFICATION.md`, and `VALIDATION.md` into the original `3a` / `3b` / `3c` phase directories
- repair stale or missing proof paths when current code no longer satisfies the old verification route
- finish Phase 06 close-out with top-level traceability, state sync, and refreshed milestone audit evidence

Explicit out-of-scope work:
- Phase 07 render readability and workspace / `runtime_data` boundary issues
- unrelated WebUI or control-plane work outside the logging proof path
- large runtime redesigns for scheduler, LTM, or logging that are not required to close an actual evidence gap

</domain>

<decisions>
## Implementation Decisions

### Execution mode
- **D-01:** Use discuss-phase auto thinking. Do not wait for more user answers.
- **D-02:** Treat roadmap + requirements + audit + Phase 06 research as the spec for this phase.

### Evidence ownership
- **D-03:** Missing artifacts must be written into the original `3a`, `3b`, and `3c` directories, because milestone audit recognizes those directories, not just Phase 06 umbrella notes.
- **D-04:** Phase 06 still needs its own `06-VERIFICATION.md` and finalized `06-VALIDATION.md`, because current GSD close-out also reads the umbrella phase artifacts.

### Honesty rules
- **D-05:** Verification must use today's repository state and today's passing commands. Old verify blocks are only hints.
- **D-06:** If a requirement still has a real proof gap, fix the smallest thing that closes the gap. Do not mark it complete without direct evidence.
- **D-07:** If original implementation history is folded into umbrella commits, say that directly in summaries instead of inventing fake task commits.

### Scope guards
- **D-08:** Only modify Phase 06 files and files explicitly named by the Phase 06 plans or required to close a real proof gap.
- **D-09:** Do not touch Phase 07 planning or unrelated dirty worktree changes.

</decisions>

<canonical_refs>
## Canonical References

Downstream execution should treat these as the canonical inputs:

- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
- `.planning/STATE.md`
- `.planning/v1.0-MILESTONE-AUDIT.md`
- `.planning/phases/06-runtime-infra-artifact-backfill/06-RESEARCH.md`
- `.planning/phases/06-runtime-infra-artifact-backfill/06-01-PLAN.md`
- `.planning/phases/06-runtime-infra-artifact-backfill/06-02-PLAN.md`
- `.planning/phases/06-runtime-infra-artifact-backfill/06-03-PLAN.md`
- `.planning/phases/06-runtime-infra-artifact-backfill/06-04-PLAN.md`
- `.planning/phases/06-runtime-infra-artifact-backfill/06-VALIDATION.md`

</canonical_refs>

<code_context>
## Existing Code Insights

### Scheduler
- Core scheduler behavior already exists under `src/acabot/runtime/scheduler/`.
- The known weak point is the stale `SCHED-08` lifecycle proof path in `tests/test_scheduler_integration.py`, because `RuntimeApp` now infers `render_service` from `pipeline.outbox`.

### LTM
- Current LTM storage and backup logic already exists under `src/acabot/runtime/memory/long_term_memory/` and bootstrap builders.
- The known weak point is `LTM-03`: current proof covers fresh validation and degradation, but the negative validation path needs explicit automated coverage for missing manifest and corrupted table conditions.

### Logging / observability
- Structured logging, query logging, and WebUI log rendering paths already exist.
- The known weak points are:
  - `LOG-02`: requirement text expects cost evidence, but current runtime path does not yet persist or log it directly
  - `LOG-04`: current tests prove logs page availability, not direct `extra` chip rendering
  - `LOG-05`: extraction-side structured logging exists in code, but direct automated proof is missing

### Top-level planning
- `.planning/REQUIREMENTS.md` still marks `SCHED-*`, `LTM-*`, and `LOG-*` as pending for Phase 06.
- `.planning/STATE.md` still treats Phase 06 as queued.
- `.planning/v1.0-MILESTONE-AUDIT.md` still reports the runtime infra groups as orphaned.

</code_context>

<specifics>
## Specific Ideas

- Keep Phase 06 as 4 plans:
  - `06-01`: scheduler proof repair + `3a` artifact chain
  - `06-02`: LTM negative validation proof + `3b` artifact chain
  - `06-03`: logging proof closure for cost / UI / extraction + `3c` artifact chain
  - `06-04`: Phase 06 close-out + top-level traceability + refreshed audit
- Prefer minimal production edits and direct proof tests over broad rewrites.
- When shell aliases from workflow docs are missing, use the same local `gsd-tools.cjs` primitives and document the substitution in summaries.

</specifics>

<deferred>
## Deferred Ideas

- Real-client render readability follow-up belongs to Phase 07.
- Workspace / `runtime_data` contract cleanup belongs to Phase 07.
- Any v2 scheduler, observability, or LTM expansion remains out of scope for this backfill phase.

</deferred>
