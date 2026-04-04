---
phase: 02-plugin-reconciler
verified: 2026-04-04T08:57:00Z
status: passed
score: 13/13 requirements verified
gaps: []
verification_type: phase
---

# Phase 02 Verification

Phase 02 现在已经有 3 张 old plan summary, 再加上当前仓库里还能稳定执行的插件测试和 WebUI build, `PLUG-01..13` 都能落到可复验的 evidence 上。

## Verification Commands

### Quick Suite

```bash
PYTHONPATH=src uv run pytest -q \
  tests/runtime/test_plugin_package.py \
  tests/runtime/test_plugin_spec.py \
  tests/runtime/test_plugin_status.py \
  tests/runtime/test_plugin_runtime_host.py \
  tests/runtime/test_plugin_reconciler.py \
  tests/runtime/test_plugin_integration.py \
  tests/runtime/test_bootstrap.py \
  tests/runtime/test_app.py
```

Result: `95 passed in 8.93s`

### API + Transitional Plugin Smoke

```bash
PYTHONPATH=src uv run pytest -q \
  tests/runtime/test_webui_api.py::test_runtime_http_api_server_serves_status_and_session_crud \
  tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent \
  tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable
```

Result: `3 passed in 4.44s`

### WebUI Smoke

```bash
cd webui && npm run build
```

Result: `vite build` 成功, `91 modules transformed`, `built in 3.64s`

### Historical Deletion Evidence

```bash
git show --stat --summary 1dfe340
```

Result:

- `src/acabot/runtime/plugin_manager.py` deleted
- `src/acabot/runtime/plugins/napcat_tools.py` deleted
- `src/acabot/runtime/plugins/ops_control.py` deleted
- `tests/runtime/test_plugin_integration.py` created

## Requirements Coverage

| Requirement | Status | Evidence |
| --- | --- | --- |
| `PLUG-01` | ✓ VERIFIED | [02-PLAN-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-01-SUMMARY.md) 记录 `plugin_protocol.py`、`plugin_package.py`、`plugin_spec.py`、`plugin_runtime_host.py` 的 `plugin_id` 主键迁移; quick suite 覆盖 `tests/runtime/test_plugin_package.py`、`tests/runtime/test_plugin_runtime_host.py` |
| `PLUG-02` | ✓ VERIFIED | [02-PLAN-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-01-SUMMARY.md) 记录 `PackageCatalog` 和 `extensions/plugins/sample_tool/plugin.yaml`; quick suite 中 `tests/runtime/test_plugin_package.py` 通过 |
| `PLUG-03` | ✓ VERIFIED | [02-PLAN-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-01-SUMMARY.md) 记录 `plugin_spec.py`; quick suite 中 `tests/runtime/test_plugin_spec.py` 通过 |
| `PLUG-04` | ✓ VERIFIED | [02-PLAN-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-01-SUMMARY.md) 记录 `plugin_status.py`; quick suite 中 `tests/runtime/test_plugin_status.py` 通过 |
| `PLUG-05` | ✓ VERIFIED | [02-PLAN-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-01-SUMMARY.md) 记录 `plugin_reconciler.py` desired-state convergence; quick suite 中 `tests/runtime/test_plugin_reconciler.py` 通过 |
| `PLUG-06` | ✓ VERIFIED | [02-PLAN-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-01-SUMMARY.md) 记录 `plugin_runtime_host.py` 负责 load / unload / teardown / `run_hooks`; quick suite 中 `tests/runtime/test_plugin_runtime_host.py`、`tests/runtime/test_app.py` 通过 |
| `PLUG-07` | ✓ VERIFIED | [02-PLAN-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-01-SUMMARY.md) 记录单插件异常隔离; quick suite 中 `tests/runtime/test_plugin_reconciler.py`、`tests/runtime/test_plugin_runtime_host.py` 通过 |
| `PLUG-08` | ✓ VERIFIED | [02-PLAN-02-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-02-SUMMARY.md) 记录 monolith 删除; `git show --stat --summary 1dfe340` 明确显示 `src/acabot/runtime/plugin_manager.py` 删除; 当前 quick suite 里的 `tests/runtime/test_bootstrap.py` 和 `tests/runtime/test_app.py` 证明新装配已接管 |
| `PLUG-09` | ✓ VERIFIED | [02-PLAN-02-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-02-SUMMARY.md) 记录 legacy plugin 删除和 `BackendBridgeToolPlugin` 保留; `git show --stat --summary 1dfe340` 明确显示 `ops_control.py`、`napcat_tools.py` 删除; smoke 中 `tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent` 和 `tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable` 通过 |
| `PLUG-10` | ✓ VERIFIED | [02-PLAN-02-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-02-SUMMARY.md) 记录 5 个 `/api/system/plugins` 端点替换旧接口; smoke 中 `tests/runtime/test_webui_api.py::test_runtime_http_api_server_serves_status_and_session_crud` 通过; 当前代码 `src/acabot/runtime/control/http_api.py` 和 `webui/src/lib/api.ts` 仍指向 `/api/system/plugins` |
| `PLUG-11` | ✓ VERIFIED | [02-PLAN-03-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-03-SUMMARY.md) 记录 `webui/src/views/PluginsView.vue`、`webui/src/lib/api.ts`、schema-driven config form、status badge、enable/disable、reconcile、toast、error modal; `cd webui && npm run build` 成功 |
| `PLUG-12` | ✓ VERIFIED | [02-PLAN-02-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-02-SUMMARY.md) 记录 bootstrap 装配 `PackageCatalog`、`SpecStore`、`StatusStore`、`PluginRuntimeHost`、`PluginReconciler`; quick suite 中 `tests/runtime/test_bootstrap.py`、`tests/runtime/test_app.py` 通过 |
| `PLUG-13` | ✓ VERIFIED | [02-PLAN-02-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-02-SUMMARY.md) 记录 pipeline 和 app lifecycle 切到 `plugin_runtime_host` / `plugin_reconciler`; quick suite 中 `tests/runtime/test_app.py`、`tests/runtime/test_plugin_integration.py` 通过 |

## Requirement-to-Artifact Map

| Wave | Summary | Covered Requirements |
| --- | --- | --- |
| Wave 1 | [02-PLAN-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-01-SUMMARY.md) | `PLUG-01..07` |
| Wave 2 | [02-PLAN-02-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-02-SUMMARY.md) | `PLUG-08`, `PLUG-09`, `PLUG-10`, `PLUG-12`, `PLUG-13` |
| Wave 3 | [02-PLAN-03-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-03-SUMMARY.md) | `PLUG-11` |

## Notes

- `PLUG-08` 和 `PLUG-09` 的删除类 requirement 不能只靠当前 pytest 证明, 所以这里补了 `git show --stat --summary 1dfe340` 作为历史删除证据。
- WebUI 这一段当前可用 smoke 只有 `cd webui && npm run build`。旧 `/api/system/plugins/config` 测试已经不在仓库里, 这里故意不把它们写成验证结果。
- `BackendBridgeToolPlugin` 现在仍是过渡代码, 所以验证里既要证明旧 builtin 插件删掉了, 也要证明这个过渡插件还能被导入并按默认 agent 暴露。

## Final Verdict

Phase 02 通过。

现在三张 summary、phase-level verification、phase-level validation 都补齐了, `PLUG-01..13` 每一条都有 summary 指针, 也有当前仓库还能跑通的命令结果。

---

_Verified: 2026-04-04T08:57:00Z_  
_Verifier: Codex_
