---
phase: 3c-logging-observability
validated: 2026-04-04T17:13:00Z
nyquist_compliant: true
status: ready-for-audit
scope: phase
---

# Phase 3c Validation

## Validation Architecture

Phase 3c 的验证分 4 层:

1. Wave summary 层
   - `3c-01-SUMMARY.md` 固定 `LOG-03`、`LOG-06`
   - `3c-02-SUMMARY.md` 固定 `LOG-01`、`LOG-02`、`LOG-05`
   - `3c-03-SUMMARY.md` 固定 `LOG-04`
2. Foundation command 层
   - `tests/test_structured_logging.py` + `tests/runtime/test_tool_broker.py`
3. Focused proof 层
   - `tests/test_agent.py` / `tests/runtime/test_pipeline_runtime.py` 锁定 cost
   - `/logs` browser proof
   - LTM extraction/query/embedding/source structured logs
4. Broad recheck 层
   - logging foundation + tool broker + agent + pipeline 52 个测试

## Per-Task Verification Map

| Task | Output | Requirement Coverage | Validation Method |
| --- | --- | --- | --- |
| Task 1 | [3c-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3c-logging-observability/3c-01-SUMMARY.md) | `LOG-03`, `LOG-06` | `tests/test_structured_logging.py` + historical commit `2a202ac` |
| Task 2 | [3c-02-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3c-logging-observability/3c-02-SUMMARY.md) | `LOG-01`, `LOG-02`, `LOG-05` | `tests/runtime/test_tool_broker.py` + focused token/cost proof + focused LTM proof |
| Task 3 | [3c-03-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3c-logging-observability/3c-03-SUMMARY.md) | `LOG-04` | focused `/logs` browser proof |
| Task 3 | [3c-VERIFICATION.md](/home/acacia/AcaBot/.planning/phases/3c-logging-observability/3c-VERIFICATION.md) | `LOG-01..06` | frontmatter `status: passed` + requirements coverage table |

## Wave 0 Requirements

这些条件现在都满足了:

- `LOG-02` 的 `cost_usd` 已有直接自动化断言
- `LOG-04` 的 `.extra-chip` 渲染已有 focused browser proof
- `LOG-05` 的 extraction side 已有 `test_extractor_client_emits_structured_log`
- `3c-VERIFICATION.md` 已存在且 `status: passed`

## Automated Validation Set

```bash
PYTHONPATH=src uv run pytest -q tests/test_structured_logging.py tests/runtime/test_tool_broker.py
```

Expected and recorded result: `20 passed in 6.43s`

```bash
PYTHONPATH=src uv run pytest -q tests/test_agent.py tests/runtime/test_pipeline_runtime.py -k 'structured_usage_log or token_usage_and_logs_it'
```

Expected and recorded result: `3 passed, 29 deselected in 3.14s`

```bash
PYTHONPATH=src uv run pytest -q tests/runtime/test_webui_api.py::test_logs_page_renders_structured_extra_fields tests/runtime/test_long_term_memory_source.py::test_extractor_client_emits_structured_log tests/runtime/test_long_term_memory_source.py::test_query_planner_client_emits_structured_log tests/runtime/test_long_term_memory_source.py::test_embedding_client_emits_structured_log tests/runtime/test_long_term_memory_source.py::test_long_term_memory_source_emits_structured_logs
```

Expected and recorded result: `5 passed in 10.66s`

## Manual-Only Verifications

All phase behaviors have automated verification.

## Audit Use

后续 audit 直接读取下面 5 个文件就够了:

- [3c-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3c-logging-observability/3c-01-SUMMARY.md)
- [3c-02-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3c-logging-observability/3c-02-SUMMARY.md)
- [3c-03-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/3c-logging-observability/3c-03-SUMMARY.md)
- [3c-VERIFICATION.md](/home/acacia/AcaBot/.planning/phases/3c-logging-observability/3c-VERIFICATION.md)
- [3c-VALIDATION.md](/home/acacia/AcaBot/.planning/phases/3c-logging-observability/3c-VALIDATION.md)
