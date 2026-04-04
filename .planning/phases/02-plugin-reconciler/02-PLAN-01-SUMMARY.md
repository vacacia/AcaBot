---
phase: 02-plugin-reconciler
plan: 01
subsystem: plugin-runtime
tags: [plugin-reconciler, plugin-foundation, plugin-id, manifest, spec-store, status-store, runtime-host, pytest]
requires: []
provides:
  - plugin_id-based runtime plugin protocol split out of the legacy monolith
  - manifest scanning from extensions/plugins via plugin.yaml
  - runtime_config/plugins spec persistence and runtime_data/plugins status persistence
  - desired-state reconciler and runtime host foundation with per-plugin failure isolation
  - sample_tool reference plugin and focused foundation test suite
affects: [02-PLAN-02, 02-PLAN-03, runtime-bootstrap, pipeline, verification]
tech-stack:
  added: []
  patterns:
    - "Plugin identity uses stable plugin_id instead of import path strings."
    - "Package catalog, spec store, status store, reconciler, and host are split into focused modules."
    - "Single-plugin load failure is recorded in status and does not stop other plugins."
key-files:
  created:
    - src/acabot/runtime/plugin_protocol.py
    - src/acabot/runtime/plugin_package.py
    - src/acabot/runtime/plugin_spec.py
    - src/acabot/runtime/plugin_status.py
    - src/acabot/runtime/plugin_runtime_host.py
    - src/acabot/runtime/plugin_reconciler.py
    - extensions/plugins/sample_tool/__init__.py
    - extensions/plugins/sample_tool/plugin.yaml
    - tests/runtime/test_plugin_package.py
    - tests/runtime/test_plugin_spec.py
    - tests/runtime/test_plugin_status.py
    - tests/runtime/test_plugin_runtime_host.py
    - tests/runtime/test_plugin_reconciler.py
  modified:
    - docs/29-plugin-control-plane.md
key-decisions:
  - "Wave 1 只固化 plugin foundation, 不把 bootstrap、HTTP API、WebUI 接线提前混进来."
  - "sample_tool 和五组 foundation pytest 一起归入同一 wave, 因为它们和基础模块在 ba16ed1 同一提交里落地."
patterns-established:
  - "Manifest scan reads plugin.yaml under extensions/plugins/* and derives PluginPackage metadata from files, not config import paths."
  - "Spec and status are separate persisted objects: desired state in runtime_config/plugins, observed state in runtime_data/plugins."
requirements-completed: [PLUG-01, PLUG-02, PLUG-03, PLUG-04, PLUG-05, PLUG-06, PLUG-07]
duration: historical backfill
completed: 2026-04-04
---

# Phase 02 Plan 01: Plugin Foundation Summary

**`plugin_protocol.py`、`plugin_package.py`、`plugin_spec.py`、`plugin_status.py`、`plugin_runtime_host.py`、`plugin_reconciler.py` 加上 `sample_tool` 和 foundation tests，一次性把 plugin desired-state foundation 从旧 monolith 里拆出来**

## Performance

- **Duration:** historical backfill
- **Started:** 2026-04-04T08:36:27Z
- **Completed:** 2026-04-04T08:36:27Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- 用 `ba16ed1` 固定了 Phase 02 Wave 1 的真实边界: 这波只交付 plugin foundation 模块、`sample_tool` 模板插件和对应 pytest, 不包含 bootstrap、HTTP API、WebUI。
- 把 `plugin_id` 迁移、manifest 扫描、spec/status 持久化、host/reconciler 行为、单插件异常隔离拆成独立证据块, 让 PLUG-01..07 可以直接从 summary frontmatter 和正文引用。
- 记录了 `extensions/plugins/sample_tool/` 在同一 wave 里落地的事实, 后续 verification 不需要再从 commit 历史反推 sample plugin 属于哪一段。

## Task Commits

1. **Task 1: 回填 `02-PLAN-01-SUMMARY.md`，固定 plugin foundation 证据** - 未提交
   - 历史实现证据: `ba16ed1` (`feat`) `feat: add plugin reconciler foundation modules (Phase 2, Wave 1)`
   - 本次 backfill 只补 summary 文件, 当前共享 worktree 未做额外 commit

## Files Created/Modified

- `src/acabot/runtime/plugin_protocol.py` - 定义 `RuntimePlugin`、`RuntimePluginContext`、`RuntimeHookPoint`、`RuntimeHookResult` 等协议, 把旧 `plugin_manager.py` 里的稳定接口抽出来
- `src/acabot/runtime/plugin_package.py` - 扫描 `extensions/plugins/` 下的 `plugin.yaml`, 产出 `PluginPackage` 清单
- `src/acabot/runtime/plugin_spec.py` - 把期望态 `PluginSpec` 持久化到 `runtime_config/plugins/`
- `src/acabot/runtime/plugin_status.py` - 把运行态 `PluginStatus` 持久化到 `runtime_data/plugins/`
- `src/acabot/runtime/plugin_runtime_host.py` - 负责 load / unload / teardown / `run_hooks` / tool 注册
- `src/acabot/runtime/plugin_reconciler.py` - 负责 desired-state convergence, 把 catalog + spec + status + host 串起来
- `extensions/plugins/sample_tool/__init__.py` - 真实 sample plugin, 作为开发模板和基础 smoke artifact
- `extensions/plugins/sample_tool/plugin.yaml` - sample plugin manifest, 证明 manifest 驱动扫描已经不是空壳
- `tests/runtime/test_plugin_package.py` - 锁定 manifest 扫描和 package metadata 行为
- `tests/runtime/test_plugin_spec.py` - 锁定 spec 文件读写和 schema
- `tests/runtime/test_plugin_status.py` - 锁定 status 文件读写和 phase / error 记录
- `tests/runtime/test_plugin_runtime_host.py` - 锁定 host 的 load / unload / teardown / hook / tool 行为
- `tests/runtime/test_plugin_reconciler.py` - 锁定 reconciler 的 convergence 和错误隔离
- `docs/29-plugin-control-plane.md` - 同一提交里修正 Phase 1 删除后的 ADR 漂移

## Decisions Made

- `PLUG-01`: plugin identity 迁移落在 `plugin_protocol.py`、`plugin_package.py`、`plugin_spec.py`、`plugin_runtime_host.py` 这一组基础模块里, 证据重点是稳定 `plugin_id`, 不是旧 import path 配置兼容。
- `PLUG-02`: `PluginPackage` 的历史事实必须和 `sample_tool/plugin.yaml` 一起写, 因为 manifest 扫描如果没有 repo 内置插件例子, verification 会失去最直接的引用物。
- `PLUG-03` 和 `PLUG-04`: `PluginSpec` / `PluginStatus` 分别持久化到 `runtime_config/plugins/` 和 `runtime_data/plugins/`, 两者职责分开, 不混成一个“插件状态文件”。
- `PLUG-05` 和 `PLUG-06`: desired-state convergence 属于 `plugin_reconciler.py`, runtime lifecycle 和 `run_hooks` 属于 `plugin_runtime_host.py`, 这两个要求必须拆开写, 不然后面很容易把 host 和 reconciler 混成一团。
- `PLUG-07`: 单插件异常隔离不是口号, 它落在 host / reconciler 的异常捕获与 status 记录路径, 并由 `test_plugin_runtime_host.py`、`test_plugin_reconciler.py` 兜底。

## Historical Evidence

- `git log --oneline --grep='feat: add plugin reconciler foundation modules' -n 1` 命中 `ba16ed1`
- `git show --stat --summary --oneline ba16ed1 -- . ':(exclude)webui'` 显示同一 wave 新建了:
  - `src/acabot/runtime/plugin_protocol.py`
  - `src/acabot/runtime/plugin_package.py`
  - `src/acabot/runtime/plugin_spec.py`
  - `src/acabot/runtime/plugin_status.py`
  - `src/acabot/runtime/plugin_runtime_host.py`
  - `src/acabot/runtime/plugin_reconciler.py`
  - `extensions/plugins/sample_tool/__init__.py`
  - `extensions/plugins/sample_tool/plugin.yaml`
  - `tests/runtime/test_plugin_package.py`
  - `tests/runtime/test_plugin_spec.py`
  - `tests/runtime/test_plugin_status.py`
  - `tests/runtime/test_plugin_runtime_host.py`
  - `tests/runtime/test_plugin_reconciler.py`

## Requirement Evidence Map

- `PLUG-01`:
  - Files: `src/acabot/runtime/plugin_protocol.py`, `src/acabot/runtime/plugin_package.py`, `src/acabot/runtime/plugin_spec.py`, `src/acabot/runtime/plugin_runtime_host.py`
  - Fact: identity 以 `plugin_id` 为主键贯穿 package / spec / host, 不再以 import path 作为 runtime 身份
- `PLUG-02`:
  - Files: `src/acabot/runtime/plugin_package.py`, `extensions/plugins/sample_tool/plugin.yaml`, `tests/runtime/test_plugin_package.py`
  - Fact: `PackageCatalog` 从 `extensions/plugins/` 扫描 `plugin.yaml`
- `PLUG-03`:
  - Files: `src/acabot/runtime/plugin_spec.py`, `tests/runtime/test_plugin_spec.py`
  - Fact: `PluginSpec` 落盘到 `runtime_config/plugins/`
- `PLUG-04`:
  - Files: `src/acabot/runtime/plugin_status.py`, `tests/runtime/test_plugin_status.py`
  - Fact: `PluginStatus` 落盘到 `runtime_data/plugins/`
- `PLUG-05`:
  - Files: `src/acabot/runtime/plugin_reconciler.py`, `tests/runtime/test_plugin_reconciler.py`
  - Fact: reconciler 负责 desired-state convergence
- `PLUG-06`:
  - Files: `src/acabot/runtime/plugin_runtime_host.py`, `tests/runtime/test_plugin_runtime_host.py`
  - Fact: host 负责 load / unload / teardown / `run_hooks`
- `PLUG-07`:
  - Files: `src/acabot/runtime/plugin_runtime_host.py`, `src/acabot/runtime/plugin_reconciler.py`, `tests/runtime/test_plugin_runtime_host.py`, `tests/runtime/test_plugin_reconciler.py`
  - Fact: 单插件异常会被记录并隔离, 不会拖垮整个 runtime

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- 当前仓库是共享 worktree, 已存在大量别人或前序流程的未提交修改。本次只补 summary, 没有回退任何现有变更, 也没有把本次 backfill 单独 commit。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `02-PLAN-01.md` 现在已经有 basename 精确匹配的 summary, Phase 05 后续 verification 可以直接抓取 `requirements-completed` 和正文证据。
- Wave 2 可以在不重写 Wave 1 内容的前提下, 单独引用 bootstrap / HTTP API / legacy deletion 证据。

## Self-Check: PASSED

- `node /home/acacia/.codex/get-shit-done/bin/gsd-tools.cjs verify-summary .planning/phases/02-plugin-reconciler/02-PLAN-01-SUMMARY.md` 返回 `passed: true`
- `rg -n '^requirements-completed: \[PLUG-01, PLUG-02, PLUG-03, PLUG-04, PLUG-05, PLUG-06, PLUG-07\]' .planning/phases/02-plugin-reconciler/02-PLAN-01-SUMMARY.md` 命中
- `rg -n 'plugin_protocol.py|plugin_package.py|plugin_spec.py|plugin_status.py|plugin_runtime_host.py|plugin_reconciler.py|sample_tool' .planning/phases/02-plugin-reconciler/02-PLAN-01-SUMMARY.md` 命中
