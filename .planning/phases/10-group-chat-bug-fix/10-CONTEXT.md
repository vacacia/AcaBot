# Phase 10: Group Chat Bug Fix - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

修复群聊消息响应行为 — 让 bot 根据 session config 的 admission domain 配置，对群聊消息做出正确的响应：仅对 @ 机器人或回复机器人的消息回复，对普通群消息 silent_drop。

</domain>

<decisions>
## Implementation Decisions

### Root Cause
- **D-01:** Surface 命名不一致是 bug 的 root cause
  - Config 写的是: `message`, `message_mention`, `message_reply`
  - 代码期望的是: `message.plain`, `message.mention`, `message.reply_to_bot`
  - `_surface_candidates()` 生成候选链: `["message.plain"]` (普通) / `["message.mention", "message.plain"]` (@) / `["message.reply_to_bot", "message.plain"]` (回复)
  - `resolve_surface()` 查不到匹配的 surface，fallback 到全空 `SurfaceConfig()`
  - `resolve_admission()` 遇到 `domain is None` → 返回默认 `mode: respond`
  - Bot 回复所有群消息

### Fix Strategy
- **D-02:** 改 Config（不改代码）— 修改三个群组的 session.yaml surface 命名
  - `message` → `message.plain`
  - `message_mention` → `message.mention`
  - `message_reply` → `message.reply_to_bot`
  - 理由: 代码逻辑本身正确，只是 Config 命名不符合代码约定

### Groups Requiring Fix
- **D-03:** `runtime_config/sessions/qq/group/1039173249/session.yaml` — 需要修复
- **D-04:** `runtime_config/sessions/qq/group/1097619430/session.yaml` — 需要修复（测试群）
- **D-05:** `runtime_config/sessions/qq/group/742824007/session.yaml` — 需要修复

### Verification Approach
- **D-06:** 端到端测试 — 用 `scripts/send_test_event.py` 发伪造事件到测试群 1097619430，验证:
  1. 普通群消息 → bot 不回复
  2. @ 机器人消息 → bot 回复
  3. 回复机器人消息 → bot 回复
- **D-07:** pytest 单元测试 — 写 SessionRuntime 的 surface 匹配逻辑测试，防止 regression

### Claude's Discretion
- 具体 YAML diff 由 planner 生成
- 测试脚本的参数由 executor 决定

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Root Cause 证据
- `src/acabot/runtime/control/session_runtime.py` — `_surface_candidates()` 生成 surface 候选链 (L427-454)
- `src/acabot/runtime/control/session_runtime.py` — `resolve_surface()` surface 匹配逻辑 (L141-155)
- `src/acabot/runtime/control/session_runtime.py` — `resolve_admission()` domain=None 时默认 respond (L206-220)
- `src/acabot/gateway/napcat.py` — `reply_targets_self` 计算逻辑验证正确 (L219-223)

### Session Config
- `runtime_config/sessions/qq/group/1097619430/session.yaml` — 测试群配置（admission 逻辑正确但 surface 名不匹配）
- `runtime_config/sessions/qq/group/742824007/session.yaml` — aozi 群配置
- `runtime_config/sessions/qq/group/1039173249/session.yaml` — 第三个群配置

### Test Tools
- `scripts/send_test_event.py` — 端到端测试事件注入脚本

### 代码库约定
- `.planning/codebase/ARCHITECTURE.md` — Runtime 请求数据流（Gateway → RuntimeApp → RuntimeRouter → SessionRuntime → RouteDecision）
- `.planning/codebase/TESTING.md` — pytest 测试规范

</canonical_refs>

<code_context>
## Existing Code Insights

### napcat.py 翻译验证正确
- `mentions_self`, `reply_targets_self`, `targets_self` 计算经代码验证正确
- 普通群消息: `bot_relation = ambient_group`
- @ 消息: `bot_relation = mention_self`
- 回复消息: `bot_relation = reply_to_self`

### Surface 候选链（session_runtime.py:427-454）
```
普通消息 → ["message.plain"]
@ 消息   → ["message.mention", "message.plain"]
回复消息 → ["message.reply_to_bot", "message.plain"]
命令     → ["message.command", "message.plain"]
```

### Session Config 的 surface 域解析
- YAML 中 `message.admission.default.mode` 会被解析为 `AdmissionDomainConfig(default={"mode": "silent_drop"})`
- 当 surface 名字匹配时，admission 逻辑完全正确

### Reusable Assets
- `scripts/send_test_event.py` — WebSocket 测试事件注入，可直接用
- `tests/runtime/test_pipeline_runtime.py` — 有 `FakeAgentRuntime` 可复用

</code_context>

<specifics>
## Specific Ideas

- 测试群 1097619430 用于端到端验证，token 是 `80iV<RBrHtQdmp0r`，bot ID 是 `3482263824`
- 端到端测试命令示例:
  - 普通消息: `python3 scripts/send_test_event.py --group-id 1097619430 --text "普通消息" --message-type group`
  - @ 消息: `python3 scripts/send_test_event.py --group-id 1097619430 --text "hello" --message-type group --mention-self`
  - 回复消息: `python3 scripts/send_test_event.py --group-id 1097619430 --text "replying" --message-type group --reply-id <msg_id>`

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 10-group-chat-bug-fix*
*Context gathered: 2026-04-05*
