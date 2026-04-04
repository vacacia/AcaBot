---
phase: 02-plugin-reconciler
plan: 03
subsystem: plugin-webui
tags: [plugin-reconciler, webui, plugins-view, schema-driven-form, toast, error-modal, vite]
requires:
  - phase: 02-PLAN-01
    provides: plugin package metadata, config_schema, status model
  - phase: 02-PLAN-02
    provides: /api/system/plugins endpoints and plugin control-plane wiring
provides:
  - WebUI plugin management page backed by the new /api/system/plugins API
  - schema-driven config form generated from plugin package config_schema
  - inline enable/disable, reconcile, toast feedback, and failed-plugin error modal
affects: [verification, validation, webui, plugin-control-plane]
tech-stack:
  added: []
  patterns:
    - "PluginsView.vue renders plugin cards from package/spec/status and mutates state through /api/system/plugins."
    - "Schema-driven config editing uses config_schema properties instead of hardcoded per-plugin fields."
    - "WebUI smoke evidence for this wave is npm run build, not deleted legacy endpoint tests."
key-files:
  created: []
  modified:
    - webui/src/views/PluginsView.vue
    - webui/src/lib/api.ts
key-decisions:
  - "Wave 3 只记录 WebUI plugin page, 不重复 bootstrap、pipeline、legacy deletion 的历史描述."
  - "当前可复验的 WebUI 证据使用 cd webui && npm run build, 不把已经消失的旧 /api/system/plugins/config 测试当有效证明."
patterns-established:
  - "Failed plugin cards show status badge in the list and open a modal for full load_error details."
  - "Reconcile uses one POST /api/system/plugins/reconcile call plus frontend transitional state."
requirements-completed: [PLUG-11]
duration: historical backfill
completed: 2026-04-04
---

# Phase 02 Plan 03: Plugin WebUI Summary

**`webui/src/views/PluginsView.vue` 和 `webui/src/lib/api.ts` 把新插件系统的控制面接到 WebUI 里, 交付 schema-driven config form、status badge、enable/disable、reconcile、toast 和 error modal**

## Performance

- **Duration:** historical backfill
- **Started:** 2026-04-04T08:36:27Z
- **Completed:** 2026-04-04T08:36:27Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- 用 `b454029` 固定了旧 Wave 3 的真实边界: 这波只完成插件管理页 WebUI, 不再往前重复 plugin foundation、bootstrap、pipeline 和 legacy deletion。
- 把 `PluginsView.vue` 里真正可见的用户动作写实了: 列表展示、状态 badge、启用/停用、schema-driven 配置编辑、重新扫描、toast 提示、失败详情弹窗。
- 明确记录当前还能稳定复验这段历史的 smoke 是 `cd webui && npm run build`, 不是已经消失的旧 `/api/system/plugins/config` 接口测试。

## Task Commits

1. **Task 1: 回填 `02-PLAN-03-SUMMARY.md`，固定 WebUI 插件页证据** - 未提交
   - 历史实现证据: `b454029` (`feat`) `feat: rewrite plugin management WebUI page (Phase 2, Wave 3)`
   - 本次 backfill 只补 summary 文件, 当前共享 worktree 未做额外 commit

## Files Created/Modified

- `webui/src/views/PluginsView.vue` - 新插件页主体, 负责拉取插件列表、生成 schema-driven config form、处理 enable/disable/save/remove/reconcile、展示 badge / toast / error modal
- `webui/src/lib/api.ts` - 给 `/api/system/plugins` 这一组接口配置 WebUI 侧 API 路由行为

## Decisions Made

- `PLUG-11`: WebUI 证据只归这张 summary, 不把前两张 summary 已经固定的 runtime host、reconciler、HTTP API 再抄一遍。
- schema-driven config form 要和 `plugin.package.config_schema` 绑在一起写, 因为这是插件页从“写死表单”变成“按 manifest 渲染”的关键差别。
- failed badge 和 error modal 要一起写, 因为用户先在列表里看到失败状态, 再点开查看完整 `load_error`, 这才是完整的故障查看路径。
- `npm run build` 是当前还活着的 WebUI smoke。旧 `/api/system/plugins/config` 测试已经不在仓库里, 不能拿来装成现成证据。

## Historical Evidence

- `git log --oneline --grep='feat: rewrite plugin management WebUI page' -n 1` 命中 `b454029`
- `rg -n 'config_schema|toast|errorModal|reconcile|/api/system/plugins' webui/src/views/PluginsView.vue webui/src/lib/api.ts` 命中:
  - `PluginsView.vue` 里的 `config_schema` 表单生成逻辑
  - `apiGet` / `apiPut` / `apiDelete` / `apiPost` 对 `/api/system/plugins` 和 `/api/system/plugins/reconcile` 的调用
  - `toast` 展示与自动消失逻辑
  - `errorModal` 失败详情弹窗

## Requirement Evidence Map

- `PLUG-11`:
  - Files: `webui/src/views/PluginsView.vue`, `webui/src/lib/api.ts`
  - Current code facts:
    - `PluginsView.vue` 通过 `apiGet("/api/system/plugins")` 拉取 package/spec/status 组合视图
    - `apiPut("/api/system/plugins/${id}/spec")` 负责启用/停用和保存配置
    - `apiDelete("/api/system/plugins/${id}/spec")` 负责移除 spec
    - `apiPost("/api/system/plugins/reconcile", {})` 负责重新扫描
    - `plugin.package?.config_schema` 驱动动态表单字段
    - 列表 badge、toast、`errorModal` 组成完整反馈链
  - Smoke evidence:
    - `cd webui && npm run build`
  - Fact:
    - WebUI 插件页已经不再依赖旧插件接口, 而是围绕 `/api/system/plugins`、schema-driven config form、状态反馈和失败详情查看来工作

## Current Truth Checks

- `rg -n 'config_schema|toast|errorModal|reconcile|/api/system/plugins' webui/src/views/PluginsView.vue webui/src/lib/api.ts`
  - 命中 `config_schema`、`toast`、`errorModal`、`reconcile()` 和 `/api/system/plugins` 路由调用
- `webui/src/views/PluginsView.vue` 当前还保留:
  - status badge 渲染
  - enable / disable / save / remove 按钮
  - reconcile 按钮
  - schema-driven 配置字段生成
  - error modal

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- 当前仓库是共享 worktree, 已存在别人或前序流程的未提交修改。本次只补 summary, 没有回退任何现有变更, 也没有把本次 backfill 单独 commit。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `02-PLAN-03.md` 现在已经有 basename 精确匹配的 summary, Phase 02 三个旧 plan 都能被 verification 和 audit 直接引用。
- Phase-level verification 现在可以把 `PLUG-11` 明确指到这张 summary, 不再把 WebUI requirement 混进其他 wave。

## Self-Check: PASSED

- `node /home/acacia/.codex/get-shit-done/bin/gsd-tools.cjs verify-summary .planning/phases/02-plugin-reconciler/02-PLAN-03-SUMMARY.md` 返回 `passed: true`
- `rg -n '^requirements-completed: \[PLUG-11\]' .planning/phases/02-plugin-reconciler/02-PLAN-03-SUMMARY.md` 命中
- `rg -n 'PluginsView.vue|api.ts|schema-driven|npm run build|b454029' .planning/phases/02-plugin-reconciler/02-PLAN-03-SUMMARY.md` 命中
