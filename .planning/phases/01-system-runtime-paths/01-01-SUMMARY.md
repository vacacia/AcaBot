---
phase: 01-system-runtime-paths
plan: 01
subsystem: api
tags: [control-plane, webui, config, filesystem, gateway]
requires: []
provides:
  - 统一的 `/api/system/configuration` 系统配置快照
  - gateway/filesystem/admins 的显式 apply-result 语义
  - 系统页可直接消费的运行时路径总览契约
affects: [system-view, webui, phase-01-02, phase-01-03]
tech-stack:
  added: []
  patterns:
    - 后端权威系统配置快照
    - 显式 apply-result payload
key-files:
  created: []
  modified:
    - src/acabot/runtime/control/config_control_plane.py
    - src/acabot/runtime/control/control_plane.py
    - src/acabot/runtime/control/http_api.py
    - tests/runtime/test_webui_api.py
key-decisions:
  - "路径总览统一在后端生成，前端不复制路径解析规则"
  - "gateway 保存返回 restart_required，filesystem/admins 保存返回 applied 或 apply_failed"
patterns-established:
  - "Pattern: 系统页通过 /api/system/configuration 读取统一系统快照"
  - "Pattern: 配置写入结果统一包含 apply_status、restart_required、message 和可选 technical_detail"
requirements-completed: [SYS-02, SYS-03, OPS-02]
duration: 26min
completed: 2026-03-30
---

# Phase 01 Plan 01: system-runtime-paths Summary

**后端现在能一次性给出系统配置快照、路径总览和明确的保存生效语义，系统页终于有了唯一可信真源。**

## Performance

- **Duration:** 26 min
- **Started:** 2026-03-29T16:05:00Z
- **Completed:** 2026-03-29T16:30:58Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- 新增 `/api/system/configuration`，把 gateway、filesystem、admins 和 paths 聚合成系统页可直接读取的快照
- 在后端补齐运行时路径总览，包括配置文件、catalog 扫描根、sticky notes、LTM、backend session 等关键路径
- 统一 gateway / filesystem / admins 的 apply-result 语义，并补齐对应 WebUI API 回归测试

## Task Commits

1. **任务 1-3：系统配置快照、apply-result 语义与测试一起落地** - `8856a62` (`feat`)

## Files Created/Modified

- `src/acabot/runtime/control/config_control_plane.py` - 增加运行时路径总览 helper，并统一 gateway/filesystem 的 apply-result 返回
- `src/acabot/runtime/control/control_plane.py` - 暴露统一系统配置快照，并把 admins 保存结果接入 apply-result 语义
- `src/acabot/runtime/control/http_api.py` - 新增 `/api/system/configuration` HTTP 入口
- `tests/runtime/test_webui_api.py` - 覆盖系统配置快照、gateway restart_required、filesystem apply_failed、admins applied 等关键契约

## Decisions & Deviations

关键决定：
- 路径总览继续沿用现有 `Config.resolve_path()`、filesystem helper 和 runtime path helper，不在前端重算
- `apply_failed` 被视为“已写入但热应用失败”，仍返回 200，让系统页能给出明确解释而不是把用户扔进模糊错误态

偏离计划：
- 原计划按 task 原子提交，但这 3 个任务在实现上是同一个后端契约面，拆开会产生中间态失败，所以合并成一个代码提交完成

## Next Phase Readiness

- `01-02` 现在可以放心做可复用列表编辑器，不需要再猜保存返回形状
- `01-03` 可以直接围绕 `/api/system/configuration` 重构 `SystemView.vue`
- 暂无阻塞项，下一步适合继续执行 `01-02`
