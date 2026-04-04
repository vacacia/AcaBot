---
phase: 02-plugin-reconciler
plan: 02
subsystem: plugin-integration
tags: [plugin-reconciler, bootstrap, http-api, pipeline, legacy-deletion, backend-bridge, runtime-host]
requires:
  - phase: 02-PLAN-01
    provides: plugin foundation modules and persisted plugin state model
provides:
  - bootstrap wiring for package catalog, spec store, status store, runtime host, and reconciler
  - pipeline hook execution moved from plugin_manager to plugin_runtime_host
  - REST API replacement from legacy plugin endpoints to /api/system/plugins endpoints
  - deletion of plugin_manager.py and legacy runtime plugins while preserving BackendBridgeToolPlugin
affects: [02-PLAN-03, app-lifecycle, control-plane, http-api, verification]
tech-stack:
  added: []
  patterns:
    - "Bootstrap constructs plugin catalog, stores, host, and reconciler as first-class runtime components."
    - "Pipeline hook execution goes through PluginRuntimeHost instead of the deleted monolith."
    - "Legacy built-in plugins are removed while BackendBridgeToolPlugin stays as transitional code."
key-files:
  created: []
  modified:
    - src/acabot/runtime/bootstrap/__init__.py
    - src/acabot/runtime/bootstrap/components.py
    - src/acabot/runtime/app.py
    - src/acabot/runtime/pipeline.py
    - src/acabot/runtime/control/control_plane.py
    - src/acabot/runtime/control/http_api.py
    - src/acabot/runtime/plugins/backend_bridge_tool.py
    - src/acabot/runtime/plugins/__init__.py
    - src/acabot/runtime/__init__.py
  deleted:
    - src/acabot/runtime/plugin_manager.py
    - src/acabot/runtime/plugins/ops_control.py
    - src/acabot/runtime/plugins/napcat_tools.py
key-decisions:
  - "Wave 2 专门记录 integration 和 deletion, 不把 WebUI plugin page 提前写进这份 summary."
  - "BackendBridgeToolPlugin 作为过渡代码保留, 但不回到新 plugin reconciler 体系里."
patterns-established:
  - "HTTP API 统一落到 /api/system/plugins* 五个端点."
  - "RuntimeApp start/stop 和 pipeline hook dispatch 都直接依赖 PluginRuntimeHost / PluginReconciler."
requirements-completed: [PLUG-08, PLUG-09, PLUG-10, PLUG-12, PLUG-13]
duration: historical backfill
completed: 2026-04-04
---

# Phase 02 Plan 02: Plugin Integration Summary

**bootstrap、app、pipeline、control plane、HTTP API 一起切到 `PluginRuntimeHost` / `PluginReconciler`, 同时删掉 `plugin_manager.py`、`ops_control.py`、`napcat_tools.py`, 只保留过渡期 `BackendBridgeToolPlugin`**

## Performance

- **Duration:** historical backfill
- **Started:** 2026-04-04T08:36:27Z
- **Completed:** 2026-04-04T08:36:27Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- 用 `1dfe340` 固定了旧 Wave 2 的真实边界: 这波是 integration + deletion, 不包含后面的 WebUI plugin management page。
- 把 `PLUG-08`、`PLUG-09`、`PLUG-10`、`PLUG-12`、`PLUG-13` 分别绑到 bootstrap、HTTP API、pipeline、legacy deletion 的具体文件和命令证据上。
- 明确记录 `BackendBridgeToolPlugin` 是保留的过渡代码, 这样 verification 不会误把它也算进 legacy plugin 删除范围。

## Task Commits

1. **Task 1: 回填 `02-PLAN-02-SUMMARY.md`，固定 integration 和 legacy deletion 证据** - 未提交
   - 历史实现证据: `1dfe340` (`refactor`) `refactor: wire new plugin system and delete legacy code (Phase 2, Wave 2)`
   - 本次 backfill 只补 summary 文件, 当前共享 worktree 未做额外 commit

## Files Created/Modified

- `src/acabot/runtime/bootstrap/__init__.py` - bootstrap 改为装配 package catalog、spec store、status store、runtime host、reconciler
- `src/acabot/runtime/bootstrap/components.py` - `RuntimeComponents` 暴露新的 plugin 组件
- `src/acabot/runtime/app.py` - runtime start/stop 接到 `plugin_reconciler.reconcile_all()` 和 `plugin_runtime_host.teardown_all()`
- `src/acabot/runtime/pipeline.py` - hook 调度从 `plugin_manager.run_hooks` 改到 `plugin_runtime_host.run_hooks`
- `src/acabot/runtime/control/control_plane.py` - 控制面改为基于 catalog / spec_store / status_store / host / reconciler 组装插件视图
- `src/acabot/runtime/control/http_api.py` - 删除旧 4 个插件端点, 换成 `/api/system/plugins*` 5 个新端点
- `src/acabot/runtime/plugins/backend_bridge_tool.py` - 导入改到 `plugin_protocol`, 并明确标注为过渡代码
- `src/acabot/runtime/plugins/__init__.py` - 只导出 `BackendBridgeToolPlugin`
- `src/acabot/runtime/__init__.py` - facade 改导出新 plugin 模块, 移除 `RuntimePluginManager`
- `src/acabot/runtime/plugin_manager.py` - 删除 959 行 monolith
- `src/acabot/runtime/plugins/ops_control.py` - 删除 legacy plugin
- `src/acabot/runtime/plugins/napcat_tools.py` - 删除 legacy plugin

## Decisions Made

- `PLUG-08`: 旧 `plugin_manager.py` 删除这件事要和 `src/acabot/runtime/__init__.py`、bootstrap、pipeline 的导入切换一起写, 单写“文件删了”不够。
- `PLUG-09`: legacy plugin 删除只覆盖 `ops_control.py`、`napcat_tools.py` 和可能的 `reference_tools.py`; `BackendBridgeToolPlugin` 必须单独标成保留的过渡代码。
- `PLUG-10`: 新 REST API 不是“插件 API 重构”这种空话, 必须明确是 5 个 `/api/system/plugins` 端点替掉旧 4 个端点。
- `PLUG-12`: bootstrap 接线要落在 `build_runtime_components()` 这一层, 这样后续 verification 才知道该查哪组 runtime 组件。
- `PLUG-13`: pipeline 接线证据要同时写 `src/acabot/runtime/pipeline.py` 和 `src/acabot/runtime/app.py`, 因为 start 阶段 reconcile 与 runtime hook dispatch 是两条不同链路。

## Historical Evidence

- `git log --oneline --grep='refactor: wire new plugin system and delete legacy code' -n 1` 命中 `1dfe340`
- `git show --stat --summary 1dfe340 -- src/acabot/runtime` 显示:
  - 修改: `src/acabot/runtime/bootstrap/__init__.py`, `src/acabot/runtime/bootstrap/components.py`, `src/acabot/runtime/app.py`, `src/acabot/runtime/pipeline.py`, `src/acabot/runtime/control/control_plane.py`, `src/acabot/runtime/control/http_api.py`, `src/acabot/runtime/plugins/backend_bridge_tool.py`, `src/acabot/runtime/plugins/__init__.py`, `src/acabot/runtime/__init__.py`
  - 删除: `src/acabot/runtime/plugin_manager.py`, `src/acabot/runtime/plugins/ops_control.py`, `src/acabot/runtime/plugins/napcat_tools.py`

## Requirement Evidence Map

- `PLUG-08`:
  - Files: `src/acabot/runtime/plugin_manager.py` deleted, `src/acabot/runtime/__init__.py`, `src/acabot/runtime/bootstrap/__init__.py`
  - Command evidence: `git show --stat --summary 1dfe340 -- src/acabot/runtime`
  - Fact: monolith 被完整替换并从 runtime 代码树删除
- `PLUG-09`:
  - Files: `src/acabot/runtime/plugins/ops_control.py` deleted, `src/acabot/runtime/plugins/napcat_tools.py` deleted, `src/acabot/runtime/plugins/backend_bridge_tool.py`, `src/acabot/runtime/plugins/__init__.py`
  - Fact: legacy plugins 删除, `BackendBridgeToolPlugin` 作为过渡代码保留
- `PLUG-10`:
  - Files: `src/acabot/runtime/control/http_api.py`, `src/acabot/runtime/control/control_plane.py`
  - Current command evidence: `rg -n '/api/system/plugins|/api/system/plugins/.*/spec' src/acabot/runtime/control/http_api.py webui/src`
  - Fact: 5 个新端点替换旧 4 个插件端点
- `PLUG-12`:
  - Files: `src/acabot/runtime/bootstrap/__init__.py`, `src/acabot/runtime/bootstrap/components.py`, `src/acabot/runtime/app.py`
  - Fact: bootstrap 组装 catalog / spec_store / status_store / host / reconciler, app lifecycle 直接调用它们
- `PLUG-13`:
  - Files: `src/acabot/runtime/pipeline.py`, `src/acabot/runtime/app.py`
  - Current command evidence: `rg -n 'run_hooks|plugin_runtime_host' src/acabot/runtime/pipeline.py src/acabot/runtime/app.py`
  - Fact: pipeline 从 `plugin_manager.run_hooks` 切到 `plugin_runtime_host.run_hooks`, app start/stop 也切到新 runtime host

## Current Truth Checks

- `rg -n 'run_hooks|plugin_runtime_host|/api/system/plugins|BackendBridgeToolPlugin|plugin_manager' src/acabot/runtime webui/src`
  - 命中当前 `pipeline.py`、`app.py`、`bootstrap/__init__.py`、`control_plane.py`、`http_api.py`、`PluginsView.vue`
  - 当前代码里 `plugin_runtime_host.run_hooks` 和 `/api/system/plugins` 新端点都还在
- `BackendBridgeToolPlugin` 现在仍由 `src/acabot/runtime/bootstrap/__init__.py` 直接注册, 没有被删掉

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- 当前仓库是共享 worktree, 已存在大量别人或前序流程的未提交修改。本次只补 summary, 没有回退任何现有变更, 也没有把本次 backfill 单独 commit。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `02-PLAN-02.md` 现在已经有 basename 精确匹配的 summary, 后面的 phase verification 可以直接引用 `requirements-completed` 和 integration / deletion 证据。
- `02-PLAN-03` 可以只关注 WebUI plugin management page, 不需要再背着 bootstrap 和 legacy deletion 的历史包袱。

## Self-Check: PASSED

- `node /home/acacia/.codex/get-shit-done/bin/gsd-tools.cjs verify-summary .planning/phases/02-plugin-reconciler/02-PLAN-02-SUMMARY.md` 返回 `passed: true`
- `rg -n '^requirements-completed: \[PLUG-08, PLUG-09, PLUG-10, PLUG-12, PLUG-13\]' .planning/phases/02-plugin-reconciler/02-PLAN-02-SUMMARY.md` 命中
- `rg -n 'plugin_manager.py|ops_control.py|napcat_tools.py|BackendBridgeToolPlugin|/api/system/plugins|run_hooks' .planning/phases/02-plugin-reconciler/02-PLAN-02-SUMMARY.md` 命中
