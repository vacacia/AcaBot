---
phase: 05-foundation-artifact-backfill
slug: foundation-artifact-backfill
status: ready-for-audit
validated: 2026-04-04T08:47:20Z
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-04
---

# Phase 05 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `pytest 9.0.2` + `pytest-asyncio` auto mode, plus `npm run build` for WebUI compile smoke |
| **Config file** | `pyproject.toml`, `webui/package.json` |
| **Quick run command** | `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_package.py tests/runtime/test_plugin_spec.py tests/runtime/test_plugin_status.py tests/runtime/test_plugin_runtime_host.py tests/runtime/test_plugin_reconciler.py tests/runtime/test_plugin_integration.py tests/runtime/test_bootstrap.py tests/runtime/test_app.py` |
| **Full suite command** | `bash -lc 'PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_package.py tests/runtime/test_plugin_spec.py tests/runtime/test_plugin_status.py tests/runtime/test_plugin_runtime_host.py tests/runtime/test_plugin_reconciler.py tests/runtime/test_plugin_integration.py tests/runtime/test_bootstrap.py tests/runtime/test_app.py && PYTHONPATH=src uv run pytest -q tests/runtime/test_webui_api.py::test_runtime_http_api_server_serves_status_and_session_crud tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable && cd webui && npm run build'` |
| **Estimated runtime** | ~25 seconds |

---

## Sampling Rate

- **After every task commit:** Run the smallest relevant command from the verification map for the requirement cluster touched by that task.
- **After every plan wave:** Run `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_package.py tests/runtime/test_plugin_spec.py tests/runtime/test_plugin_status.py tests/runtime/test_plugin_runtime_host.py tests/runtime/test_plugin_reconciler.py tests/runtime/test_plugin_integration.py tests/runtime/test_bootstrap.py tests/runtime/test_app.py`.
- **Before `$gsd-verify-work`:** Run the full suite command, then regenerate milestone audit evidence checks against the new artifacts.
- **Max feedback latency:** 25 seconds for the quick suite on this machine.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | REF-01 | static + git | `bash -lc 'test -z "$(find src/acabot/runtime/references -type f ! -path '\''*/__pycache__/*'\'' -print -quit 2>/dev/null)" && test ! -f src/acabot/runtime/plugins/reference_tools.py && test ! -f src/acabot/runtime/control/reference_ops.py && ! rg -n "reference_backend|ReferenceBackend|ReferenceToolsPlugin|reference_tools|reference_ops" src tests config.example.yaml'` | ✅ | ✅ green |
| 05-01-02 | 01 | 1 | REF-02 | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable` | ✅ | ✅ green |
| 05-01-03 | 01 | 1 | REF-03 | static | `bash -lc '! rg -n "^[[:space:]]*reference:" config.example.yaml && ! rg -n "reference_backend|ReferenceBackend" src/acabot/runtime/bootstrap src/acabot/runtime/app.py'` | ✅ | ✅ green |
| 05-02-01 | 02 | 2 | PLUG-01, PLUG-02 | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_package.py tests/runtime/test_plugin_runtime_host.py` | ✅ | ✅ green |
| 05-02-02 | 02 | 2 | PLUG-03, PLUG-04 | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_spec.py tests/runtime/test_plugin_status.py` | ✅ | ✅ green |
| 05-02-03 | 02 | 2 | PLUG-05, PLUG-06, PLUG-07 | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_reconciler.py tests/runtime/test_plugin_runtime_host.py` | ✅ | ✅ green |
| 05-03-01 | 03 | 3 | PLUG-08, PLUG-09 | static + git | `bash -lc 'test ! -f src/acabot/runtime/plugin_manager.py && test ! -f src/acabot/runtime/plugins/ops_control.py && test ! -f src/acabot/runtime/plugins/napcat_tools.py' && git show --stat --summary 1dfe340 -- src/acabot/runtime/plugin_manager.py | rg "delete mode 100644"` | ✅ | ✅ green |
| 05-03-02 | 03 | 3 | PLUG-10, PLUG-11 | API smoke + build | `bash -lc 'PYTHONPATH=src uv run pytest -q tests/runtime/test_webui_api.py::test_runtime_http_api_server_serves_status_and_session_crud && rg -n '\''segments == \\[\"system\", \"plugins\"\\]|segments == \\[\"system\", \"plugins\", \"reconcile\"\\]|segments\\[:2\\] == \\[\"system\", \"plugins\"\\]'\'' src/acabot/runtime/control/http_api.py && cd webui && npm run build && rg -n '\''/api/system/plugins|plugin_id|/spec|reconcile'\'' src/views/PluginsView.vue'` | ✅ | ✅ green |
| 05-03-03 | 03 | 3 | PLUG-12, PLUG-13 | unit + static | `bash -lc 'PYTHONPATH=src uv run pytest -q tests/runtime/test_bootstrap.py::test_build_runtime_components_creates_plugin_reconciler tests/runtime/test_app.py::test_runtime_app_plugin_host_available_on_event && rg -n '\''plugin_reconciler\\.reconcile_all|plugin_runtime_host\\.run_hooks'\'' src/acabot/runtime/app.py src/acabot/runtime/pipeline.py'` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/runtime/test_webui_api.py` — 如果 verifier 认为 `PLUG-10` 的 HTTP 证据太薄, 增加对 `GET /api/system/plugins/{id}`、`PUT /api/system/plugins/{id}/spec`、`DELETE /api/system/plugins/{id}/spec`、`POST /api/system/plugins/reconcile` 的 focused smoke
- [ ] `tests/test_main.py` — 当前 `RuntimeComponents` fixture 缺 `render_service`, 不要拿 repo-wide full pytest 当 Phase 05 gate, 除非先在别处修掉这条漂移

---

## Manual-Only Verifications

All phase behaviors have automated verification.

---

## Validation Audit

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 9 |
| Escalated | 0 |

- `05-VERIFICATION.md` 已存在, frontmatter `status: passed`
- `.planning/REQUIREMENTS.md` 已把 foundation 16 条 requirement 改成 `[x]` + `Validated`
- `.planning/v1.0-MILESTONE-AUDIT.md` 已重跑 foundation tri-source aggregation, foundation orphan gap 已清空
- 当前环境没有 `gsd-validate-phase` shell alias, 这次按同一份 validate workflow 规则直接更新现有 `05-VALIDATION.md`, 只调整文档状态和 audit 记录, 没有跳过必填 section

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 25s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** complete
