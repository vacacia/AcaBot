---
phase: 04-unified-message-tool-playwright
verified: 2026-04-04T06:39:58Z
status: passed
score: 14/14 must-haves verified
gaps: []
---

# Phase 04: unified-message-tool-playwright Verification Report

**Phase Goal:** Give the agent complete messaging capabilities (reply, quote, react, recall, media, cross-session) via a unified tool backed by platform-agnostic actions flowing through Outbox, plus text-to-image rendering.
**Verified:** 2026-04-04T06:39:58Z
**Status:** passed
**Re-verification:** Yes — this pass specifically re-checked the previously reported cross-session working-memory gap after the Outbox projection fix landed.

## Goal Achievement

Phase 04 现在已经把主线闭合了：

- 统一 `message` builtin tool 已经稳定，`send` / `react` / `recall` 三个动作的 surface 没再漂
- `SEND_MESSAGE_INTENT` 已经通过 Outbox materialization 收口成真正的低层发送动作
- render service / Playwright backend / bootstrap wiring / shutdown cleanup 已接通
- 之前卡住的那条 cross-session continuity 断链，已经通过 `source_intent + OutboundMessageProjection + _ensure_thread_content()` 修掉

这次 re-verification 的关键结论不是 "`message.py` 终于自己生成了 `thread_content`"，而是更合理的那版：

- 真实 `message.send` 仍然可以只表达高层发送意图
- Outbox 在最终送达面统一生成 `fact_text` 和 `thread_text`
- 所以 facts、working memory、destination thread continuity 现在都在同一个收口点同步

## Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | 模型只能看到一个统一的 `message` builtin tool，`action` 默认是 `send`。 | ✓ VERIFIED | `tests/runtime/test_message_tool.py` 已锁定 schema 与注册行为 |
| 2 | `message.react` 和 `message.recall` 仍然是低层 direct action，不在 tool 里直接调用 Gateway。 | ✓ VERIFIED | `src/acabot/runtime/builtin_tools/message.py` |
| 3 | 未知 reaction emoji 会严格失败，不会静默降级成普通文本。 | ✓ VERIFIED | `tests/runtime/test_message_tool.py` |
| 4 | `message.send` 仍然物化成单条可发送的低层消息，并支持 quote、@、text、images、render、cross-session target。 | ✓ VERIFIED | `src/acabot/runtime/outbox.py`、`tests/runtime/test_outbox.py` |
| 5 | 只有内容型 `message.send` 会抑制默认 assistant 文本回复，`react` / `recall` 不会。 | ✓ VERIFIED | `src/acabot/runtime/model/model_agent_runtime.py`、`tests/runtime/test_model_agent_runtime.py` |
| 6 | cross-session send 的消息事实写到 destination thread，不会误记回来源 thread。 | ✓ VERIFIED | `tests/runtime/test_outbox.py::test_outbox_persists_cross_session_delivery_to_destination` |
| 7 | cross-session send 的 thread working memory 现在也会写到 destination thread。 | ✓ VERIFIED | `tests/runtime/test_pipeline_runtime.py::test_thread_pipeline_updates_destination_thread_from_real_message_tool_output` |
| 8 | 真实 `message.send` 就算上游没填 `thread_content`，Outbox 也会在送达后自动补齐 continuity 文本。 | ✓ VERIFIED | `tests/runtime/test_outbox.py::test_outbox_derives_thread_content_from_materialized_segments` |
| 9 | facts 和 working memory 已经分成两套摘要：`fact_text` 偏稳定检索，`thread_text` 偏连续性。 | ✓ VERIFIED | `src/acabot/runtime/outbound_projection.py`、`src/acabot/runtime/outbox.py` |
| 10 | render capability 仍然是 optional；没有 backend 时不会阻断 runtime。 | ✓ VERIFIED | `src/acabot/runtime/render/service.py`、`tests/runtime/test_render_service.py` |
| 11 | render 成功时，working memory 会保留原始 markdown / LaTeX，而不是只剩图片占位符。 | ✓ VERIFIED | `tests/runtime/test_outbox.py::test_outbox_thread_projection_preserves_render_source_while_fact_text_keeps_image_placeholders` |
| 12 | default bootstrap-built RenderService 会显式注册 `PlaywrightRenderBackend`，并把同一个实例注入 Outbox。 | ✓ VERIFIED | `tests/runtime/test_bootstrap.py` |
| 13 | RuntimeApp.stop() 会统一关闭 render service，render backend 生命周期已收口。 | ✓ VERIFIED | `tests/runtime/test_app.py` |
| 14 | NapCat 出站 file-like segments 会把裸本地路径规范成绝对 `file://` URI，便于发送 runtime 内部生成的 render artifact。 | ✓ VERIFIED | `src/acabot/gateway/napcat.py`、`tests/test_gateway.py` |

**Score:** 14/14 truths verified

## What Changed Since The Previous Verification

上一版 verification 卡住的是这条断链：

`message.send` -> `PlannedAction.thread_content=None` -> `ThreadPipeline._update_thread_after_send()` 跳过 working memory 回写

现在修法是：

1. `SEND_MESSAGE_INTENT` 在 materialize 之前把原始高层语义快照保存到 `PlannedAction.metadata["source_intent"]`
2. `src/acabot/runtime/outbound_projection.py` 统一把一条已送达消息投影成 `fact_text` 和 `thread_text`
3. `Outbox._ensure_thread_content()` 在最终 delivery action 出来后自动补齐 `plan.thread_content`
4. `ThreadPipeline` 继续只消费 `item.plan.thread_content`，但这次它真的拿得到值了

这版修法比“让 message tool 自己提前猜最终 continuity 文本”更稳，因为：

- 它收口在 Outbox 的最终发送面
- 它能看到最终 delivery action
- 它还能保留 materialize 前的 render 原文和高层语义

## Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `src/acabot/runtime/builtin_tools/message.py` | Unified message tool surface with send/react/recall handlers | ✓ VERIFIED | 保持高层 send intent surface，不强行在 tool 层做 continuity 预测 |
| `src/acabot/runtime/outbound_projection.py` | facts / working-memory dual projection | ✓ VERIFIED | 统一生成 `fact_text` / `thread_text` |
| `src/acabot/runtime/outbox.py` | send intent materialization + source_intent snapshot + auto thread_content补齐 | ✓ VERIFIED | continuity 收口点已经在这里稳定落地 |
| `src/acabot/runtime/pipeline.py` | destination thread working-memory update logic | ✓ VERIFIED | 逻辑保持不变，现在上游输入已经完整 |
| `src/acabot/runtime/render/service.py` | capability-based render service | ✓ VERIFIED | optional fallback / close 仍成立 |
| `src/acabot/gateway/napcat.py` | reaction + file-like send payload normalization | ✓ VERIFIED | reaction 与本地 file URI 规范化都在 |
| `tests/runtime/test_outbox.py` | materialization / continuity / render fallback coverage | ✓ VERIFIED | 已覆盖真实 continuity 投影与 render continuity |
| `tests/runtime/test_pipeline_runtime.py` | destination thread continuity end-to-end coverage | ✓ VERIFIED | 已覆盖真实 `message` tool 输出到 destination thread 的完整链路 |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Outbox continuity / cross-session / render fallback re-check | `PYTHONPATH=src uv run pytest -q tests/runtime/test_outbox.py -k 'thread_content or cross_session or render_fallback'` | `3 passed, 22 deselected in 4.72s` | ✓ PASS |
| Pipeline cross-session re-check | `PYTHONPATH=src uv run pytest -q tests/runtime/test_pipeline_runtime.py -k 'cross_session'` | `2 passed, 17 deselected in 4.71s` | ✓ PASS |
| Existing Phase 04 regression evidence | `PYTHONPATH=src uv run pytest -q tests/runtime/test_message_tool.py tests/runtime/test_builtin_tools.py tests/test_gateway.py tests/runtime/test_outbox.py tests/runtime/test_model_agent_runtime.py tests/runtime/test_pipeline_runtime.py tests/runtime/test_render_service.py tests/runtime/test_bootstrap.py tests/runtime/test_app.py` | Previous verification already recorded `155 passed in 4.67s`; this re-verification focused on the formerly failing gap | ✓ PASS |

## Requirements Coverage

| Requirement | Description | Status | Evidence |
| --- | --- | --- | --- |
| `MSG-01` | 文本回复 | ✓ SATISFIED | Outbox materializes text send |
| `MSG-02` | 引用回复 | ✓ SATISFIED | `reply_to` 继续走 `Action.reply_to` |
| `MSG-03` | `@mention` | ✓ SATISFIED | `at_user` 物化为 `at` segment |
| `MSG-04` | Emoji reaction | ✓ SATISFIED | `REACTION -> set_msg_emoji_like` |
| `MSG-05` | 撤回消息 | ✓ SATISFIED | `RECALL -> delete_msg` |
| `MSG-06` | 媒体/附件发送 | ✓ SATISFIED | image segments + file ref normalization |
| `MSG-07` | 工具层只表达意图 | ✓ SATISFIED | `message` tool 只返回 `ToolResult.user_actions` |
| `MSG-08` | 文转图渲染 | ✓ SATISFIED | injected render service + fallback |
| `MSG-09` | 跨会话消息发送 | ✓ SATISFIED | facts、LTM dirty、destination working memory 都已对齐目标 thread |
| `MSG-10` | schema / 字段设计 finalized | ✓ SATISFIED | schema tests 已锁死 |
| `PW-01` | `render_markdown_to_image()` 在 Outbox 层 | ✓ SATISFIED | Outbox 通过 injected render service 调用 |
| `PW-02` | Singleton browser 实例管理 | ✓ SATISFIED | lazy browser reuse + app shutdown close |
| `PW-03` | markdown-it-py -> HTML -> Playwright screenshot | ✓ SATISFIED | render backend pipeline 已接通 |

## Manual Verification Still Recommended

自动化已经把 Phase 04 的代码闭环跑通了，但下面 3 项还是值得真人看一眼：

1. 在真实 QQ 客户端里确认 quoted reply + @ 最终表现
2. 在真实目标会话里确认 cross-session send 的用户体验
3. 在真实客户端里确认 render 图片的可读性和公式显示

这些现在是 **manual UAT**，不是 phase 的代码 blocker。

## Final Verdict

Phase 04 现在可以判定为 **passed**。

之前唯一拦路的那个 gap 已经被关掉，而且修法是正确分层的那版：不把 continuity 规则塞回 tool surface，而是让 Outbox 基于 `source_intent + delivery action` 统一生成 `fact_text` / `thread_text`。这让 facts、working memory、cross-session destination contract、render continuity 都落在同一个收口点，后面继续扩消息能力时也不容易再裂。

---

_Verified: 2026-04-04T06:39:58Z_  
_Verifier: Codex (re-verified after Outbox projection fix)_
