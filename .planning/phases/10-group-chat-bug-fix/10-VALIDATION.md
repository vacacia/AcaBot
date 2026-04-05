---
phase: 10
slug: group-chat-bug-fix
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-05
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0+ / pytest-asyncio 0.23+ |
| **Config file** | `pyproject.toml` with `asyncio_mode = "auto"` |
| **Quick run command** | `pytest tests/runtime/test_session_runtime.py -x -q` |
| **Full suite command** | `pytest tests/runtime/ -x -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/runtime/test_session_runtime.py -x -q`
- **After every plan wave:** Run `pytest tests/runtime/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 1 | GROUP-01 | unit | `pytest tests/runtime/test_session_runtime.py::test_surface_naming_resolves_admission_correctly -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/runtime/test_session_runtime.py` — add `test_surface_naming_resolves_admission_correctly` for GROUP-01 regression coverage

*Wave 0 task: Add a new test that validates the surface key naming convention (wrong key `message` → fallback → default respond behavior).*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Bot 不回复普通群消息（silent_drop 生效） | GROUP-01 | 需要真实 WebSocket 连接到测试群 1097619430 | `python3 scripts/send_test_event.py --group-id 1097619430 --text "普通消息" --message-type group` — 验证无回复 |
| Bot 回复 @ 消息（respond 生效） | GROUP-01 | 需要真实 WebSocket 连接 | `python3 scripts/send_test_event.py --group-id 1097619430 --text "hello" --message-type group --mention-self` — 验证有回复 |
| Bot 回复回复消息（respond 生效） | GROUP-01 | 需要真实 WebSocket 连接 | `python3 scripts/send_test_event.py --group-id 1097619430 --text "replying" --message-type group --reply-id <msg_id>` — 验证有回复 |

*E2E tests require live bot connection. Unit tests cover surface resolution chain.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
