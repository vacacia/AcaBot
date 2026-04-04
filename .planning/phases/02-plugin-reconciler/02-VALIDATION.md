---
phase: 02-plugin-reconciler
validated: 2026-04-04T08:57:00Z
nyquist_compliant: true
status: ready-for-audit
scope: phase
---

# Phase 02 Validation

## Validation Architecture

Phase 02 的 validation 现在分 4 层:

1. **Wave summary 层**
   - `02-PLAN-01-SUMMARY.md` 固定 foundation requirements `PLUG-01..07`
   - `02-PLAN-02-SUMMARY.md` 固定 integration / deletion requirements `PLUG-08`, `PLUG-09`, `PLUG-10`, `PLUG-12`, `PLUG-13`
   - `02-PLAN-03-SUMMARY.md` 固定 WebUI requirement `PLUG-11`
2. **Current executable checks 层**
   - quick suite 验证 foundation、reconciler、runtime host、bootstrap、app lifecycle
   - API smoke 验证新 `/api/system/plugins` 路由和 transitional plugin 行为
   - `cd webui && npm run build` 验证 WebUI 插件页仍能完成生产构建
3. **Historical evidence 层**
   - `git show --stat --summary 1dfe340` 验证 `plugin_manager.py` 和 legacy plugin 删除
   - `git log --oneline --grep='feat: rewrite plugin management WebUI page' -n 1` 验证 Wave 3 对应 `b454029`
4. **Non-blocker exception 层**
   - 当前和 Phase 02 无关、或者已经确认不适合作为 gate 的漂移项, 必须明确写出, 防止 audit 把噪音当 blocker

## Per-Task Verification Map

| Task | Output | Requirement Coverage | Validation Method |
| --- | --- | --- | --- |
| Task 1 | [02-PLAN-03-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-03-SUMMARY.md) | `PLUG-11` | `verify-summary` + summary grep + 当前 `PluginsView.vue` / `api.ts` 代码引用 |
| Task 2 | [02-VERIFICATION.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-VERIFICATION.md) | `PLUG-01..13` | quick suite + API smoke + WebUI build + historical deletion evidence |
| Task 2 | [02-VALIDATION.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-VALIDATION.md) | audit support | frontmatter completeness + required section names + explicit non-blocker recording |

## Wave 0 Requirements

这些是 phase-level audit 之前必须满足的基础条件, 现在都满足了:

- 三张 old plan summary 都存在, basename 能和 `02-PLAN-01.md`、`02-PLAN-02.md`、`02-PLAN-03.md` 直接对应
- `02-VERIFICATION.md` 已经把 `PLUG-01..13` 全量列入表格
- `02-VALIDATION.md` 已经明确写出 `## Validation Architecture`
- 当前仓库里仍然存在可执行的插件测试、API smoke 和 WebUI build 命令

## Automated Validation Set

### Required Commands

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

Expected and recorded result: `95 passed in 8.93s`

```bash
PYTHONPATH=src uv run pytest -q \
  tests/runtime/test_webui_api.py::test_runtime_http_api_server_serves_status_and_session_crud \
  tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent \
  tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable
```

Expected and recorded result: `3 passed in 4.44s`

```bash
cd webui && npm run build
```

Expected and recorded result: success, `91 modules transformed`, `built in 3.64s`

## Manual-Only Verifications

这些项值得真人看, 但现在不是 Phase 02 blocker:

- 在真实 WebUI 里点一遍插件页, 确认 schema-driven form、toast 和 error modal 的交互手感
- 在真实运行态里切换 enable/disable 后, 看插件列表状态 badge 是否和 reconcile 结果一致
- 用真实失败插件复查一次 error modal 展示的 `load_error` 是否足够可读

## Non-Blockers And Exclusions

### `tests/test_main.py` 的 `render_service` fixture 漂移

- 这不是 Phase 02 gate
- 原因很简单: 它属于后续 render service 接线漂移, 不是插件系统 requirement 本身
- Phase 02 的验证已经用 `tests/runtime/test_bootstrap.py`、`tests/runtime/test_app.py`、`tests/runtime/test_plugin_integration.py` 覆盖了新插件装配和生命周期
- audit 可以记录这项漂移, 但不能拿它否定 `PLUG-01..13`

### 依赖真实 `pi` 可执行文件的 backend tests

- 这不是 Phase 02 gate
- 仓库规则里已经明确: `tests/runtime/backend/test_pi_adapter.py` 需要真实 `pi` 可执行文件, 开发环境里没有
- 这些测试验证的是 backend adapter 外部依赖, 不是插件重构是否成立
- 所以 Phase 02 verification 明确不把它们纳入硬门槛

## Audit Use

后续 audit 直接读取下面 5 个文件就够了:

- [02-PLAN-01-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-01-SUMMARY.md)
- [02-PLAN-02-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-02-SUMMARY.md)
- [02-PLAN-03-SUMMARY.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-PLAN-03-SUMMARY.md)
- [02-VERIFICATION.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-VERIFICATION.md)
- [02-VALIDATION.md](/home/acacia/AcaBot/.planning/phases/02-plugin-reconciler/02-VALIDATION.md)

这 5 个文件已经把历史 wave、当前可执行命令、手工复查项、非 blocker 漂移项全部补齐。
