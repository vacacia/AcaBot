---
phase: 06-runtime-infra-artifact-backfill
plan: 03
subsystem: logging-artifact-backfill
tags: [artifact-backfill, logging, webui, ltm, docs]
requires:
  - phase: 3c-logging-observability
    provides: missing summary, verification, and validation artifacts
provides:
  - cost-aware token logging evidence
  - direct `/logs` browser proof and LTM extraction proof
  - full `3c-logging-observability/` artifact chain
affects: [phase-3c-audit, runtime-infra-traceability, docs]
tech-stack:
  added: []
  patterns:
    - "Use focused browser tests when the full page suite has unrelated failures."
key-files:
  created:
    - .planning/phases/3c-logging-observability/3c-01-SUMMARY.md
    - .planning/phases/3c-logging-observability/3c-02-SUMMARY.md
    - .planning/phases/3c-logging-observability/3c-03-SUMMARY.md
    - .planning/phases/3c-logging-observability/3c-VERIFICATION.md
    - .planning/phases/3c-logging-observability/3c-VALIDATION.md
    - .planning/phases/06-runtime-infra-artifact-backfill/06-03-SUMMARY.md
  modified:
    - src/acabot/agent/agent.py
    - src/acabot/agent/response.py
    - src/acabot/runtime/contracts/context.py
    - src/acabot/runtime/model/model_agent_runtime.py
    - src/acabot/runtime/pipeline.py
    - tests/test_agent.py
    - tests/runtime/test_pipeline_runtime.py
    - tests/runtime/test_webui_api.py
    - tests/runtime/test_long_term_memory_source.py
    - docs/01-system-map.md
    - docs/02-runtime-mainline.md
key-decisions:
  - "Propagate `cost_usd` all the way into `RunRecord.metadata['usage_cost_usd']` so logs and persistence agree."
  - "Treat the unrelated models-page failure in `tests/runtime/test_webui_api.py` as non-blocking for LOG-04."
patterns-established:
  - "Focused proof commands are acceptable when the broad suite is contaminated by unrelated failures."
requirements-completed: [LOG-01, LOG-02, LOG-03, LOG-04, LOG-05, LOG-06]
duration: 1 session
completed: 2026-04-04
---

# Phase 06 Plan 03 Summary

## Accomplishments

- 新增 `cost_usd` / `usage_cost_usd` 贯通, 让 `LOG-02` 的成本字段同时落到结构化日志和 run metadata。
- 新增 `/logs` focused browser proof 和 LTM extraction focused proof, 把 `LOG-04`、`LOG-05` 从“推断成立”收成“直接可证”。
- 补齐 `3c` 原目录的 summary / verification / validation 工件。

## Verification Results

- `PYTHONPATH=src uv run pytest -q tests/test_structured_logging.py tests/runtime/test_tool_broker.py`
  - `20 passed in 6.43s`
- `PYTHONPATH=src uv run pytest -q tests/test_agent.py tests/runtime/test_pipeline_runtime.py -k 'structured_usage_log or token_usage_and_logs_it'`
  - `3 passed, 29 deselected in 3.14s`
- `PYTHONPATH=src uv run pytest -q tests/runtime/test_webui_api.py::test_logs_page_renders_structured_extra_fields tests/runtime/test_long_term_memory_source.py::test_extractor_client_emits_structured_log tests/runtime/test_long_term_memory_source.py::test_query_planner_client_emits_structured_log tests/runtime/test_long_term_memory_source.py::test_embedding_client_emits_structured_log tests/runtime/test_long_term_memory_source.py::test_long_term_memory_source_emits_structured_logs`
  - `5 passed in 10.66s`
- `PYTHONPATH=src uv run pytest -q tests/test_structured_logging.py tests/runtime/test_tool_broker.py tests/test_agent.py tests/runtime/test_pipeline_runtime.py`
  - `52 passed, 12 warnings in 3.40s`

## Commits

- historical: `2a202ac`
- current backfill session: not committed yet when this summary was written

## Notes

- `tests/runtime/test_webui_api.py` 全文件目前有一个无关失败: `test_models_page_renders_seeded_registry_targets_and_bindings`. 这条不在 Phase 06 范围, 所以 `LOG-04` 的 gate 继续使用 focused `/logs` proof.

## Self-Check: PASSED

- Found `.planning/phases/3c-logging-observability/3c-VERIFICATION.md`
- Found `.planning/phases/3c-logging-observability/3c-VALIDATION.md`
- Found docs sync in `docs/01-system-map.md` and `docs/02-runtime-mainline.md`
