---
phase: 04
slug: unified-message-tool-playwright
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-04
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `pytest 9.0.2` + `pytest-asyncio 1.3.0` |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `PYTHONPATH=src uv run pytest -q tests/test_gateway.py tests/runtime/test_outbox.py tests/runtime/test_model_agent_runtime.py tests/runtime/test_bootstrap.py tests/runtime/test_app.py tests/runtime/test_pipeline_runtime.py` |
| **Full suite command** | `PYTHONPATH=src uv run pytest --ignore=tests/runtime/backend/test_pi_adapter.py` |
| **Estimated runtime** | ~120 seconds |

---

## Sampling Rate

- **After every task commit:** Run the smallest relevant subset of `PYTHONPATH=src uv run pytest -q tests/test_gateway.py tests/runtime/test_outbox.py tests/runtime/test_model_agent_runtime.py tests/runtime/test_bootstrap.py tests/runtime/test_app.py tests/runtime/test_pipeline_runtime.py`
- **After every plan wave:** Run `PYTHONPATH=src uv run pytest -q tests/test_gateway.py tests/runtime/test_outbox.py tests/runtime/test_model_agent_runtime.py tests/runtime/test_bootstrap.py tests/runtime/test_app.py tests/runtime/test_pipeline_runtime.py`
- **Before `$gsd-verify-work`:** Full suite must be green with `PYTHONPATH=src uv run pytest --ignore=tests/runtime/backend/test_pi_adapter.py`
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | MSG-01 | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_message_tool.py::test_message_send_text` | ❌ Wave 0 | ⬜ pending |
| 04-01-02 | 01 | 1 | MSG-10 | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_message_tool.py::test_message_tool_schema_matches_locked_fields` | ❌ Wave 0 | ⬜ pending |
| 04-01-03 | 01 | 1 | MSG-04 | unit | `PYTHONPATH=src uv run pytest -q tests/test_gateway.py::test_build_reaction` | ❌ Wave 0 | ⬜ pending |
| 04-02-01 | 02 | 2 | MSG-02 | unit | `PYTHONPATH=src uv run pytest -q tests/test_gateway.py::test_build_send_with_reply` | ✅ | ⬜ pending |
| 04-02-02 | 02 | 2 | MSG-03 | unit | `PYTHONPATH=src uv run pytest -q tests/test_gateway.py::test_build_send_with_at_segment` | ❌ Wave 0 | ⬜ pending |
| 04-02-03 | 02 | 2 | MSG-06 | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_outbox.py::test_outbox_materializes_images` | ❌ Wave 0 | ⬜ pending |
| 04-02-04 | 02 | 2 | MSG-07 | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_message_tool.py::test_message_tool_returns_user_actions_only` | ❌ Wave 0 | ⬜ pending |
| 04-02-05 | 02 | 2 | MSG-09 | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_outbox.py::test_outbox_persists_cross_session_delivery_to_destination` | ❌ Wave 0 | ⬜ pending |
| 04-03-01 | 03 | 3 | MSG-08 | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_render_service.py` | ❌ Wave 0 | ⬜ pending |
| 04-03-02 | 03 | 3 | PW-01 | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_outbox.py::test_outbox_calls_render_service_in_materialization` | ❌ Wave 0 | ⬜ pending |
| 04-03-03 | 03 | 3 | PW-02 | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_render_service.py::test_playwright_backend_reuses_single_browser` | ❌ Wave 0 | ⬜ pending |
| 04-03-04 | 03 | 3 | PW-03 | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_render_service.py::test_render_markdown_to_image_pipeline` | ❌ Wave 0 | ⬜ pending |
| 04-03-05 | 03 | 3 | MSG-05 | unit | `PYTHONPATH=src uv run pytest -q tests/test_gateway.py::test_build_recall` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/runtime/test_message_tool.py` — 覆盖 schema、tool surface、默认回复抑制触发条件
- [ ] `tests/runtime/test_render_service.py` — 覆盖 backend lazy init、screenshot pipeline、fallback
- [ ] `tests/test_gateway.py` — 补 reaction / at segment 用例
- [ ] `tests/runtime/test_outbox.py` — 补 materialization、cross-session persistence、render fallback 用例
- [ ] `tests/runtime/test_pipeline_runtime.py` — 补 cross-session working memory 行为用例
- [ ] render backend test fixtures — 需要 stub render service / fake browser，避免单元测试强依赖真实 Chromium

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| quoted reply + @mention 在真实 QQ 会话里正确显示 | MSG-02, MSG-03 | NapCat / QQ 客户端最终表现需要实机确认 | 启动 bot，触发 `message.send`，传入 `reply_to` 与 `at_user`，在 QQ 客户端确认引用和 @ 都落在同一条消息里 |
| cross-session send 真正发往目标会话且不串到来源 thread | MSG-09 | 需要真实会话路由与目标容器验证 | 在 A 会话触发工具，指定 `target=qq:group:...` 或 `qq:user:...`，确认目标会话收到消息，来源会话不额外收到平台消息，随后检查事实落库行为 |
| render 图像在真实客户端可读 | MSG-08, PW-01, PW-03 | 截图内容的视觉可读性难靠纯自动化断言完全覆盖 | 发送包含 markdown 标题、列表、inline math、block math 的 `render` 内容，确认图片显示正常，公式不乱码 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
