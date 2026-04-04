---
phase: 3c-logging-observability
plan: 02
subsystem: logging-emit-sites
tags: [logging, tool-broker, token-usage, ltm, artifact-backfill]
requires:
  - phase: 3c-logging-observability
    provides: historical Phase 3 completion commit 2a202ac
provides:
  - tool call structured logging evidence for LOG-01
  - cost-aware token logging and run metadata evidence for LOG-02
  - LTM extraction/query structured logging evidence for LOG-05
affects: [tool-broker, agent, pipeline, ltm-model-clients, docs, audit-traceability]
tech-stack:
  added: []
  patterns:
    - "When a requirement claims cost, persist the same cost on both logs and run metadata."
key-files:
  created:
    - .planning/phases/3c-logging-observability/3c-02-SUMMARY.md
  modified:
    - src/acabot/runtime/tool_broker/broker.py
    - src/acabot/agent/agent.py
    - src/acabot/agent/response.py
    - src/acabot/runtime/model/model_agent_runtime.py
    - src/acabot/runtime/contracts/context.py
    - src/acabot/runtime/pipeline.py
    - src/acabot/runtime/memory/long_term_memory/model_clients.py
    - tests/test_agent.py
    - tests/runtime/test_pipeline_runtime.py
    - tests/runtime/test_tool_broker.py
    - tests/runtime/test_long_term_memory_source.py
    - docs/01-system-map.md
    - docs/02-runtime-mainline.md
key-decisions:
  - "Carry `cost_usd` from `AgentResponse` through `AgentRuntimeResult` into `RunRecord.metadata['usage_cost_usd']`."
  - "Treat extraction-side LTM logging as first-class proof, not as an implied side effect of query logging."
patterns-established:
  - "Direct proof beats broad smoke: LOG-02 and LOG-05 both use focused tests in Phase 06."
requirements-completed: [LOG-01, LOG-02, LOG-05]
duration: historical + backfill refresh
completed: 2026-04-04
---

# Phase 3c Plan 02 Summary

**Wave 2 原本已经把大部分 emit site 打上结构化日志, Phase 06 再把 `cost_usd` 和 extraction 直接证明补齐**

## Accomplishments

- `2a202ac` 已经交付 `ToolBroker`、agent token log、pipeline token persistence、LTM query/embedding logging.
- Phase 06 把 `LOG-02` 从“只有 token 数量”补成“token 数量 + `cost_usd` + `usage_cost_usd` 持久化”.
- Phase 06 同时补了 `test_extractor_client_emits_structured_log`, 让 `LOG-05` 不再只靠 query-side 推断.

## Verification Results

- `git show --stat --summary 2a202ac`
  - 结果: Wave 2 的大部分 logging 实现和测试来自该提交
- `PYTHONPATH=src uv run pytest -q tests/test_structured_logging.py tests/runtime/test_tool_broker.py`
  - 结果: `20 passed in 6.43s`
- `PYTHONPATH=src uv run pytest -q tests/test_agent.py tests/runtime/test_pipeline_runtime.py -k 'structured_usage_log or token_usage_and_logs_it'`
  - 结果: `3 passed, 29 deselected in 3.14s`
- `PYTHONPATH=src uv run pytest -q tests/runtime/test_webui_api.py::test_logs_page_renders_structured_extra_fields tests/runtime/test_long_term_memory_source.py::test_extractor_client_emits_structured_log tests/runtime/test_long_term_memory_source.py::test_query_planner_client_emits_structured_log tests/runtime/test_long_term_memory_source.py::test_embedding_client_emits_structured_log tests/runtime/test_long_term_memory_source.py::test_long_term_memory_source_emits_structured_logs`
  - 结果: `5 passed in 10.66s`

## Task Commits

1. Historical Wave 2 logging delivery
   - `2a202ac` — `feat: complete phase 3`
2. Phase 06 proof-gap closure for `cost_usd` and extraction logs
   - not committed yet in this backfill session when this summary was written

## Notes

- 这次对生产代码的新增范围只到 `cost_usd` 贯通和 LTM manifest validation, 没重做 logging 架构.
- `docs/01-system-map.md` 和 `docs/02-runtime-mainline.md` 也同步补上了 `usage_cost_usd` 的主线路径描述.

## Self-Check: PASSED

- Found `src/acabot/agent/agent.py`
- Found `src/acabot/runtime/pipeline.py`
- Found `src/acabot/runtime/memory/long_term_memory/model_clients.py`
- Found `tests/test_agent.py`
- Found `tests/runtime/test_pipeline_runtime.py`
- Found commit: `2a202ac`
