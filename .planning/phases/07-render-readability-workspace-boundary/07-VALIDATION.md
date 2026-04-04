---
phase: 07
slug: render-readability-workspace-boundary
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-04
---

# Phase 07 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >= 8.0 + pytest-asyncio >= 0.23 |
| **Config file** | pyproject.toml (`[tool.pytest.ini_options]`) |
| **Quick run command** | `python -m pytest tests/runtime/test_render_service.py -x --ignore=tests/runtime/backend/test_pi_adapter.py` |
| **Full suite command** | `python -m pytest tests/ -x --ignore=tests/runtime/backend/test_pi_adapter.py` |
| **Estimated runtime** | ~15 seconds (render tests), ~60 seconds (full suite) |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/runtime/test_render_service.py -x --ignore=tests/runtime/backend/test_pi_adapter.py`
- **After every plan wave:** Run `python -m pytest tests/ -x --ignore=tests/runtime/backend/test_pi_adapter.py`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | MSG-08 | unit | `python -m pytest tests/runtime/test_render_service.py -x --ignore=tests/runtime/backend/test_pi_adapter.py` | ❌ W0 | ⬜ pending |
| 07-01-02 | 01 | 1 | MSG-08 | unit | `python -m pytest tests/runtime/test_render_service.py -x --ignore=tests/runtime/backend/test_pi_adapter.py` | ❌ W0 | ⬜ pending |
| 07-01-03 | 01 | 1 | MSG-08 | unit | `python -m pytest tests/runtime/test_render_service.py -x --ignore=tests/runtime/backend/test_pi_adapter.py` | ✅ | ⬜ pending |
| 07-02-01 | 02 | 1 | MSG-08 | unit | grep 验证 prompt 文件 | ✅ | ⬜ pending |
| 07-02-02 | 02 | 1 | MSG-08 | unit | grep 验证 tool description | ✅ | ⬜ pending |
| 07-03-01 | 03 | 2 | MSG-08 | manual | 真实 QQ 验收 | N/A | ⬜ pending |
| 07-03-02 | 03 | 2 | MSG-08 | manual | 文档同步检查 | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/runtime/test_render_service.py` — 新增: device_scale_factor 传参测试、viewport_width 传参测试、context 正确关闭测试

*现有基础设施覆盖大部分 phase requirements, 上述为需补充的测试桩。*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| QQ 客户端图片可读性 | MSG-08 | 需要真实 QQ 客户端和人工判断 | 发送 8 类内容到 QQ, 验证标题/段落/列表/行内公式/块公式/代码块/引用块/表格全部可读 |
| workspace 规则生效 | MSG-08 | 需要真实模型交互验证 | 让模型在工作区操作并尝试发文件, 确认它使用 /workspace 路径 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
