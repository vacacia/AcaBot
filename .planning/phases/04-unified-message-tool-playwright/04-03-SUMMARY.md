---
phase: 04-unified-message-tool-playwright
plan: 3
subsystem: runtime
tags: [playwright, markdown-it-py, latex2mathml, render, runtime]
requires:
  - phase: 04-02
    provides: SEND_MESSAGE_INTENT materialization and destination-thread send semantics
provides:
  - project-scoped render dependencies in pyproject and uv.lock
  - internal runtime render artifact helpers under runtime_data/render_artifacts
  - optional RenderService registry and lazy Playwright markdown-to-image backend
affects: [04-04, outbox, bootstrap, runtime-shutdown, message-runtime]
tech-stack:
  added: [playwright, markdown-it-py, mdit-py-plugins, latex2mathml]
  patterns: [optional capability registry, internal runtime artifacts, lazy browser singleton]
key-files:
  created:
    [
      src/acabot/runtime/render/__init__.py,
      src/acabot/runtime/render/protocol.py,
      src/acabot/runtime/render/service.py,
      src/acabot/runtime/render/artifacts.py,
      src/acabot/runtime/render/playwright_backend.py,
      tests/runtime/test_render_service.py
    ]
  modified: [pyproject.toml, uv.lock, Dockerfile, Dockerfile.lite]
key-decisions:
  - "Render capability 保持 optional: RenderService 在没有 backend 时返回 unavailable, 不阻断 runtime 启动"
  - "Render artifacts 固定落在 runtime_data/render_artifacts, 不复用 /workspace/attachments 或 Work World"
  - "Playwright backend 缓存 browser/playwright 对象, 第一次 render 才 lazy-init, 同时落 html snapshot + png artifact"
patterns-established:
  - "Pattern: runtime capability 先暴露 registry service, 再在后续 bootstrap plan 里接默认 backend"
  - "Pattern: markdown + math 渲染链固定为 markdown-it-py + dollarmath + latex2mathml, 再交给 Playwright screenshot"
  - "Pattern: render backend 测试全部用 fake browser/playwright stub, 不强依赖真实 Chromium"
requirements-completed: [PW-02, PW-03]
duration: 5m
completed: 2026-04-04
---

# Phase 04 Plan 03: Render Foundation Summary

**Project-scoped Playwright render foundation with internal runtime artifacts, optional backend registry, and math-aware markdown screenshot tests**

## Performance

- **Duration:** 5m
- **Started:** 2026-04-04T02:15:15+08:00
- **Completed:** 2026-04-03T18:20:06Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- 把 `playwright`、`markdown-it-py`、`mdit-py-plugins`、`latex2mathml` 收进正式项目依赖图, 不再靠 Dockerfile-only 临时安装漂移。
- 新建 `src/acabot/runtime/render/` 子模块, 提供 protocol、service registry、internal artifact helper 和 lazy Playwright backend。
- 用纯 fake browser / fake playwright 测试锁死 unavailable、lazy singleton reuse、markdown+math HTML pipeline 和 internal artifact path 语义。

## Task Commits

Each task was committed atomically:

1. **Task 1: Move render dependencies into the real project dependency graph** - `97d4f37`
2. **Task 2: Build the render module, internal artifact helpers, and Playwright backend tests** - `1bcb3e9`, `dfe13b9`

## Files Created/Modified

- `pyproject.toml` - 把 4 个 render 相关依赖纳入主依赖
- `uv.lock` - 锁定 render 依赖及其解析结果
- `Dockerfile` - 改为在项目依赖安装后执行 `python -m playwright install --with-deps chromium`
- `Dockerfile.lite` - 同步 browser 安装链, 去掉 ad-hoc `pip install playwright`
- `src/acabot/runtime/render/protocol.py` - 定义 `RenderRequest`、`RenderResult`、`RenderBackend`
- `src/acabot/runtime/render/service.py` - 提供 explicit backend registry API 和 unavailable fallback
- `src/acabot/runtime/render/artifacts.py` - 统一 internal render artifact 路径分配
- `src/acabot/runtime/render/playwright_backend.py` - 实现 markdown+math -> HTML -> Playwright screenshot 流水线和 lazy browser reuse
- `src/acabot/runtime/render/__init__.py` - 暴露 render 子模块公共接口
- `tests/runtime/test_render_service.py` - 用 fake backend fixtures 覆盖 render foundation 行为

## Decisions Made

- `RenderService` 不偷偷 hardcode backend, 只维护 registry; 没有 backend 时返回 `unavailable` 结果对象。
- render 产物路径固定为 `runtime_data/render_artifacts/<conversation_id>/<run_id>/...`, 保持和 Work World 附件彻底分离。
- backend 在每次 render 前先写 HTML snapshot, 再截图成 png, 方便后续 Outbox wiring 和 debug 看见中间产物。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 04-04 可以直接把 `RenderService` 和 `PlaywrightRenderBackend` 接进 bootstrap、Outbox 和 `RuntimeApp.stop()` 生命周期。
- `tests/runtime/test_render_service.py` 已经把 backend contract 锁住, 下一 plan 只需要补 wiring 和回归覆盖, 不用重造 render 底座。

## Self-Check: PASSED

- Found `.planning/phases/04-unified-message-tool-playwright/04-03-SUMMARY.md`
- Found commits `97d4f37`, `1bcb3e9`, `dfe13b9`
