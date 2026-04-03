---
phase: 04-unified-message-tool-playwright
plan: 4
subsystem: runtime
tags: [message-tool, render-service, playwright, outbox, shutdown]
requires:
  - phase: 04-03
    provides: render service foundation, Playwright backend, runtime render artifacts
provides:
  - bootstrap-built default RenderService with explicit Playwright backend registration
  - Outbox render materialization through injected render service with raw-markdown fallback
  - RuntimeApp shutdown hook that closes the shared render service
  - docs synced for message intent, gateway boundary, and internal render artifact path
affects: [message-runtime, gateway-boundary, computer-boundary, future-render-features]
tech-stack:
  added: []
  patterns:
    - explicit default backend registration in bootstrap
    - constructor-injected shared render service for Outbox and RuntimeApp
    - shutdown-owned resource cleanup for optional runtime capabilities
key-files:
  created: []
  modified:
    - src/acabot/runtime/outbox.py
    - src/acabot/runtime/bootstrap/__init__.py
    - src/acabot/runtime/bootstrap/components.py
    - src/acabot/runtime/render/service.py
    - src/acabot/runtime/app.py
    - tests/runtime/test_outbox.py
    - tests/runtime/test_bootstrap.py
    - tests/runtime/test_app.py
    - docs/01-system-map.md
    - docs/03-data-contracts.md
    - docs/07-gateway-and-channel-layer.md
    - docs/12-computer.md
key-decisions:
  - "bootstrap 显式注册 PlaywrightRenderBackend 为默认 render backend, 不靠隐式发现"
  - "Outbox 只通过注入的 RenderService 处理 render, backend unavailable/error 时回退原始 markdown"
  - "RuntimeApp.stop() 负责关闭共享 render service, render artifact 继续留在 runtime_data/render_artifacts"
patterns-established:
  - "Render wiring pattern: bootstrap 构造 service -> 注册默认 backend -> 注入 Outbox -> RuntimeApp 负责 close"
  - "SEND_MESSAGE_INTENT materialization pattern: send intent 在 Outbox 编译成单条 SEND_SEGMENTS"
requirements-completed: [MSG-08, PW-01]
duration: 6min
completed: 2026-04-04
---

# Phase 04 Plan 4: Unified Message Tool Playwright Summary

**Bootstrap 显式接通 Playwright render service, Outbox 用共享 service 发图并在失败时回退原始 markdown, RuntimeApp 停机时统一回收 render 生命周期**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-03T18:25:58Z
- **Completed:** 2026-04-03T18:31:58Z
- **Tasks:** 2
- **Files modified:** 12

## Accomplishments

- bootstrap 现在会创建默认 `RenderService`, 显式注册 `PlaywrightRenderBackend`, 并把同一实例注入 `Outbox`
- `Outbox` 现在通过注入的 render service 处理 `render`, 成功发 image segment, unavailable/error 时回退 raw markdown text
- `RuntimeApp.stop()` 现在会关闭共享 render service, 同步把主线文档里的 message/render/gateway/computer 边界写实

## Task Commits

Each task was committed atomically:

1. **Task 1: Explicitly register `PlaywrightRenderBackend` into the default bootstrap render service and inject it into Outbox**
   - `29ffcf3` (`test`) - red: bootstrap wiring 和 Outbox render materialization failing tests
   - `387c67a` (`feat`) - green: default render service wiring, Outbox render materialization, bootstrap test temp roots
2. **Task 2: Close the render service during shutdown and document the new runtime boundary**
   - `cf22e85` (`test`) - red: RuntimeApp shutdown render close failing tests
   - `3592138` (`feat`) - green: RuntimeApp render shutdown hook + docs boundary sync

## Files Created/Modified

- `src/acabot/runtime/bootstrap/__init__.py` - 构造默认 RenderService, 显式注册 Playwright backend, 注入 Outbox 和 RuntimeApp
- `src/acabot/runtime/bootstrap/components.py` - 暴露 `render_service` 供 bootstrap 测试和后续接线直接证明同一实例
- `src/acabot/runtime/render/service.py` - 支持显式 default backend 语义
- `src/acabot/runtime/outbox.py` - 用注入的 render service materialize `render` 字段并做 raw-text fallback
- `src/acabot/runtime/app.py` - shutdown 时 close render service
- `tests/runtime/test_outbox.py` - 锁定 injected render service 调用和 unavailable/error fallback
- `tests/runtime/test_bootstrap.py` - 锁定默认 backend 注册、同实例注入, 并修正临时 runtime_root
- `tests/runtime/test_app.py` - 锁定 render service shutdown close 和错误传播
- `docs/01-system-map.md` - 明确 `message` tool -> `SEND_MESSAGE_INTENT` -> Outbox materialization -> Gateway
- `docs/03-data-contracts.md` - 写清 send intent materialization、destination conversation/thread 语义和 fallback
- `docs/07-gateway-and-channel-layer.md` - 写清 reaction 仍是 NapCat-specific low-level action, render 不属于 gateway
- `docs/12-computer.md` - 写清 render artifacts 不进入 `/workspace/attachments`

## Decisions Made

- bootstrap 使用显式 `register_backend(..., is_default=True)` 设定默认 render backend, 让 wiring 证据直接落在代码里
- `Outbox` 遇到 render service unavailable、error 或异常时都退回原始 markdown 文本, 不让发送链因为 render 断掉
- render artifacts 继续留在 `runtime_data/render_artifacts`, 不混进 Work World attachment 语义

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 把 bootstrap 测试的 runtime_root 固定到 tmp_path**
- **Found during:** Task 1
- **Issue:** `tests/runtime/test_bootstrap.py` 里多处最小配置只写了 `filesystem.base_dir`, 没给 `runtime_root`, 测试会误写项目根下 `runtime_data/` 并在当前环境触发权限错误
- **Fix:** 给相关 bootstrap 测试配置补上 `runtime_root = tmp_path / "runtime_data"`, 把临时目录语义收回测试沙箱
- **Files modified:** `tests/runtime/test_bootstrap.py`
- **Verification:** `PYTHONPATH=src uv run pytest -q tests/runtime/test_outbox.py tests/runtime/test_bootstrap.py`
- **Committed in:** `387c67a`

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** 这是验证阻塞修复, 没改业务边界, 只是把测试环境重新关回临时目录.

## Issues Encountered

- Task 1 红测阶段暴露 bootstrap 测试环境路径问题, 已在 green 阶段一起修掉

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- default render path 现在已经闭环, 后续 phase 可以直接复用 bootstrap 注入的 render service 做更多内容型消息能力
- message/render/gateway/computer 的边界文档已对齐, 后续扩展 reaction/send variants 时不需要再重新界定 render 所属层

---
*Phase: 04-unified-message-tool-playwright*
*Completed: 2026-04-04*

## Self-Check: PASSED
