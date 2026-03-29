---
phase: 01-system-runtime-paths
plan: 03
subsystem: ui
tags: [vue, webui, system-view, router, navigation, cache]
requires:
  - phase: 01-01
    provides: `/api/system/configuration` 与统一 apply-result 语义
  - phase: 01-02
    provides: `EditableListField.vue` 单项列表编辑模式
provides:
  - 真正可编辑共享系统配置的 `SystemView`
  - 收敛到 `/system` 的系统/管理员导航入口
  - 与系统配置快照联动的缓存失效和最终源码回归覆盖
affects: [system-view, router, sidebar, webui-runtime-bundle]
tech-stack:
  added: []
  patterns:
    - 系统页读取统一快照并按分区保存
    - apply-result 四态反馈
    - 共享入口收敛到 `/system`
key-files:
  created: []
  modified:
    - webui/src/views/SystemView.vue
    - webui/src/router.ts
    - webui/src/components/AppSidebar.vue
    - webui/src/lib/api.ts
    - tests/runtime/test_webui_api.py
    - src/acabot/webui/index.html
    - src/acabot/webui/assets/*
key-decisions:
  - "系统页成为共享网关、扫描根、共享管理员和维护动作的正式入口"
  - "旧 `/config/admins` 入口保留路由兼容，但统一重定向到 `/system`"
  - "系统配置写入后必须同时失效 `/api/system/configuration` 缓存"
patterns-established:
  - "Pattern: 系统页以统一反馈区呈现 applied / restart_required / apply_failed / hard error"
  - "Pattern: 高级信息以折叠区展示路径真源和运行时数据落点"
requirements-completed: [SYS-01, SYS-03, OPS-02]
duration: 11min
completed: 2026-03-30
---

# Phase 01 Plan 03: system-runtime-paths Summary

**系统页已经从只读状态卡进化成真正的共享控制面，Phase 1 也因此完整闭环。**

## Performance

- **Duration:** 11 min
- **Started:** 2026-03-29T16:36:00Z
- **Completed:** 2026-03-29T16:47:10Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments

- 重构 `SystemView.vue`，让系统页直接读取 `/api/system/configuration`，并正式承载共享网关、catalog 扫描根、共享管理员、维护动作和高级路径总览
- 把保存结果映射成统一的人话反馈，明确区分“已保存并已生效”“已保存，但需重启”“保存失败”“已写入，但应用失败”
- 收敛导航：`/config/admins` 与旧 bot 配置入口统一重定向到 `/system`，侧边栏也不再把管理员页当成并列真源
- 更新 WebUI 缓存失效逻辑和构建产物，让系统配置相关保存动作会同步刷新系统配置快照
- 补上系统页源码级断言，并通过前端构建与后端回归测试

## Task Commits

1. **任务 1-3：系统页重构、导航收敛和最终验证一起落地** - `57a183c` (`feat`)

## Files Created/Modified

- `webui/src/views/SystemView.vue` - 重构成共享系统配置控制面，并加入高级信息 / 路径总览折叠区
- `webui/src/router.ts` - 把 `/config/admins` 和旧 `/config/bot` 入口统一收敛到 `/system`
- `webui/src/components/AppSidebar.vue` - 移除单独的管理员导航项
- `webui/src/lib/api.ts` - 补齐系统配置相关写操作对 `/api/system/configuration` 的缓存失效
- `tests/runtime/test_webui_api.py` - 增加系统页共享入口和高级区的源码回归断言
- `src/acabot/webui/index.html` / `src/acabot/webui/assets/*` - 更新 runtime 内嵌 WebUI 构建产物

## Decisions & Deviations

关键决定：
- 系统页继续沿用当前 `ds-*` 设计系统，而不是额外造一套“后台运维页”视觉分支
- 高级区允许展示技术路径，但所有主标签都保持产品语言，不把内部字段名直接暴露成主文案
- 维护动作只保留低强调度位，不去抢系统配置保存按钮的主入口地位

偏离计划：
- 原计划把源码验证和构建验证拆成独立任务节奏，但实际实现里它们和系统页重构高度耦合，所以一起在同一轮代码提交里闭合

## Verification

- `npm --prefix webui run build`
- `PYTHONPATH=src pytest tests/runtime/test_webui_api.py -q -k "SystemView or webui_real_pages or admins or filesystem"`

## Next Phase Readiness

- Phase 1 已完成，系统级共享真源和路径可见性基础已经落稳
- Phase 2 可以开始把首页、日志和全局反馈真正接到可信运行态数据
- 下一步最适合执行 `gsd-discuss-phase 2` 或直接 `gsd-plan-phase 2`
