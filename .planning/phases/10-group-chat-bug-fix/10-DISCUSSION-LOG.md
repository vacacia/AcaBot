# Phase 10: Group Chat Bug Fix - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 10-group-chat-bug-fix
**Areas discussed:** Root Cause, Session Config, Fix Strategy, Verification

---

## Root Cause Analysis

**Hypothesis 1 (session-config 默认值):** Session config 的 `message.plain` admission 默认值是 respond
**Hypothesis 2 (napcat.py 字段计算):** `mentions_self` / `reply_targets_self` 计算不可靠

验证过程:
1. 读取了 `session.yaml` 配置（742824007 和 1097619430）
2. 配置中 `message.admission.default.mode: silent_drop`，但 surface 命名是 `message` 而非 `message.plain`
3. napcat.py 翻译逻辑验证正确 — `mentions_self` / `reply_targets_self` 计算无误
4. SessionRuntime surface 候选链和匹配逻辑验证 — 候选名与 config 名完全对不上

| Surface (Config) | Surface (Code expected) | Match Result |
|---|---|---|
| `message` | `message.plain` | ❌ No match |
| `message_mention` | `message.mention` | ❌ No match |
| `message_reply` | `message.reply_to_bot` | ❌ No match |

**Root cause confirmed:** Surface 命名不一致，导致所有 surface 匹配失败 → fallback → 空 SurfaceConfig → admission=None → 默认 respond

---

## Fix Strategy Discussion

| Option | Description | Selected |
|--------|-------------|----------|
| 改 Config | 修改 session.yaml surface 名称: message→message.plain, message_mention→message.mention, message_reply→message.reply_to_bot | ✓ |
| 改代码 | 在 resolve_surface() 中加兼容映射层 | ✗ |
| 两者都改 | Config 改成标准命名 + 代码加 fallback | ✗ |

**User's choice:** 改 Config（不改代码）

---

## Groups Requiring Fix

| Group ID | Status |
|----------|--------|
| 1039173249 | NEEDS FIX |
| 1097619430 | NEEDS FIX (test group) |
| 742824007 | NEEDS FIX |

---

## Verification Approach

| Option | Description | Selected |
|--------|-------------|----------|
| 端到端测试 | scripts/send_test_event.py 发伪造事件验证行为 | ✓ |
| pytest 单元测试 | 写 SessionRuntime surface 匹配测试 | ✓ |
| 两者都要 | 端到端 + 单元测试 | ✓ |

**User's choice:** 两者都要

---

## Deferred Ideas

None.

---

*End of discussion log*
