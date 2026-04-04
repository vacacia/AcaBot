# 核心数据契约

本文档说明跨模块传递的关键数据对象。按四层组织：外部输入输出 → 会话决策 → 执行现场 → 持久化事实。

数据流总览：
```
StandardEvent → EventFacts → SessionConfig/SurfaceResolution → 各 Decision → RouteDecision
    → RunContext（含 ResolvedAgent、ThreadState、RunRecord）
    → AgentRuntimeResult → PlannedAction → DispatchReport
    → 持久化：ChannelEventRecord、MessageRecord、ThreadRecord
```

契约定义集中在 `src/acabot/runtime/contracts/` 下的 `session_config.py`、`routing.py`、`context.py`、`records.py`。

---

## 一、外部输入和输出

### StandardEvent

`src/acabot/types/event.py`。平台事件进入 runtime 后的统一格式，表示"平台上刚发生了什么"。

关键字段：`event_id`、`event_type`、`platform`、`timestamp`、`source`（platform/message_type/user_id/group_id）、`segments`、`attachments`、`reply_reference`、`mentions_self`、`reply_targets_self`、`targets_self`、`bot_relation`、`target_reasons`、`text`、`metadata`、`raw_event`。

只负责平台事件标准化，不是路由结果、profile 决策或 memory 结果。改字段时要一起检查 gateway 翻译层、RuntimeRouter、SessionRuntime.build_facts、RuntimeApp.handle_event、ThreadPipeline、消息整理服务。

### Action

`src/acabot/types/action.py`。系统对外动作的统一格式。

关键字段：`action_type`（SEND_MESSAGE_INTENT / SEND_TEXT / SEND_SEGMENTS / RECALL / GROUP_BAN / GROUP_KICK / TYPING / REACTION）、`target`、`payload`、`reply_to`。Action 只表达动作本身，不包含规划来源、thread 回写策略或消息事实记录决策。

其中 `SEND_MESSAGE_INTENT` 是统一 `message` builtin tool 的高层发送意图，只给 `message.action="send"` 用。它先保留 `text`、`images`、`render`、`at_user`、`target` 这些上层字段，真正物化成平台消息的动作发生在 Outbox：`text/images` 直接编译成 segment，`render` 先通过 render service 产出图片 artifact，成功时转成 image segment，失败时回退成原始 markdown 文本。`REACTION` 和 `RECALL` 继续是底层直通动作，不走高层内容编排链。

---

## 二、会话决策

这一层是理解"一条消息为什么这样跑"的关键。定义在 `contracts/session_config.py` 和 `contracts/routing.py`。

### EventFacts

把 StandardEvent 收成决策系统可消费的事实集。比 StandardEvent 多了 runtime 稳定标识（actor_id、channel_scope、thread_id），是 SessionRuntime 所有 resolve 方法的输入。

关键字段：`platform`、`event_kind`、`scene`、`actor_id`、`channel_scope`、`thread_id`、`targets_self`、`mentions_self`、`reply_targets_self`、`mentioned_everyone`、`sender_roles`、`attachments_present`、`attachment_kinds`、`message_subtype`、`notice_type`、`notice_subtype`、`metadata`。

### MatchSpec

针对 EventFacts 的匹配条件，被 SessionRuntime 用来判断当前消息命中哪个 selector / case。是共享 matcher，只表达"这条消息像不像某种情况"，不表达"该怎么做"。字段与 EventFacts 对应。

### SessionConfig

某个会话当前使用的配置真源。关键字段：`session_id`、`template_id`、`title`、`frontstage_agent_id`、`selectors`、`surfaces`、`metadata`。按 surface + domain 组织，不是平铺规则。

### SurfaceConfig / SurfaceResolution

`SurfaceConfig` 定义某个 surface 下各决策域的默认配置（routing、admission、context、persistence、extraction、computer）。`SurfaceResolution` 表示当前消息最后命中了哪个 surface（`surface_id`、`exists`、`source`、`metadata`）。前者是配置，后者是命中结果。

### DomainCase / DomainConfig

`DomainCase` 是某个决策域下的一条局部 case（`case_id`、`when`/`when_ref`、`use`、`priority`、`metadata`）。六种 DomainConfig（Routing / Admission / Context / Persistence / Extraction / Computer）都是 `default` + `cases` 结构：先吃默认配置，再按 case 做局部覆盖。

### Decision 对象

当前消息在各决策域最终算出的结果：

| Decision | 关键内容 |
|----------|---------|
| `RoutingDecision` | 走哪个 agent、actor lane、命中的 case |
| `AdmissionDecision` | mode（respond / record_only / silent_drop） |
| `ContextDecision` | sticky note targets、prompt slots、retrieval tags、context labels |
| `PersistenceDecision` | event 是否持久化 |
| `ExtractionDecision` | 是否提取长期记忆、tags |
| `ComputerPolicyDecision` | backend、bash 权限、shell session、可见 world roots、可见 skills |

### RouteDecision

`contracts/routing.py`。router 最终交给 app/pipeline 的统一决策结果，携带 `thread_id`、`actor_id`、`agent_id`、`channel_scope`、`run_mode`，以及上面所有 decision 对象。后面 RuntimeApp、ThreadPipeline、ComputerRuntime 都直接消费它。

---

## 三、执行现场

定义在 `contracts/routing.py`、`contracts/context.py`、`contracts/records.py`。

### ResolvedAgent

`contracts/routing.py`。当前 run 的身份和能力快照（`agent_id`、`name`、`prompt_ref`、`enabled_tools`、`skills`、`visible_subagents`、`computer_policy`、`config`）。是静态配置快照，不承载本轮临时决策或运行中状态。

### ThreadState / ThreadRecord

`contracts/records.py`。`ThreadState` 是当前 thread 在 runtime 里的工作上下文（`thread_id`、`channel_scope`、`thread_kind`、`working_messages`、`working_summary`、`last_event_at`、`metadata`、`lock`）。`ThreadRecord` 是其可持久化版本（无运行时锁）。两者都只负责当前 thread 的工作上下文，不是长期记忆或全量聊天档案。

### RunRecord

`contracts/records.py`。一次正式执行的生命周期记录（`run_id`、`thread_id`、`actor_id`、`agent_id`、`trigger_event_id`、`status`、`started_at`、`finished_at`、`error`、`approval_context`、`metadata`）。状态流转：queued → running → completed / completed_with_errors / failed / waiting_approval / interrupted / cancelled。

### RunContext

`contracts/context.py`。ThreadPipeline 执行一轮 run 时的共享现场对象——"这次执行的总篮子"。主要字段分组：

| 分组 | 字段 |
|------|------|
| 基础现场 | `run`、`event`、`decision`、`thread`、`agent` |
| 模型请求 | `model_request`、`summary_model_request` |
| 会话决策 | `event_facts`、`surface_resolution`、所有 decision |
| computer | `world_view`、`workspace_state`、`attachment_snapshots`、`computer_backend_kind`、`computer_policy_effective` |
| 消息整理 | `resolved_message`、`resolved_images`、`message_projection` |
| 模型输入和记忆 | `messages`、`retrieval_plan`、`shared_memory_request`、`memory_broker_result`、`memory_blocks`、`memory_user_content`、`system_prompt` |
| 执行结果 | `response`、`actions`、`delivery_report`、`metadata` |

需要在 pipeline 里共享中间结果时，优先放进 RunContext，不要发明临时局部变量逐层传递。

### 消息整理相关

`ResolvedImageInput`（解析好的单张图片输入）、`ResolvedMessage`（消息 + reply + 图片补齐后的结果）、`MessageProjection`（同一条消息按 history/model/memory 三种用途投影的结果）、`RetrievalPlan`（进入模型前的上下文准备计划，携带 sticky_note_targets、retained history、dropped messages、prompt slots）。

### 动作和投递

`PlannedAction`（待发送动作规划，含 `action_id`、`action`、`thread_content`、`commit_when`）→ `DeliveryResult`（单个动作投递结果，含 `ok`、`platform_message_id`、`error`）→ `OutboxItem`（Outbox 发送项）→ `OutboundMessageProjection`（同一条出站消息按 facts / working memory 生成的摘要）→ `DispatchReport`（一批动作的汇总结果，含 `results`、`delivered_items`、`failed_action_ids`、`has_failures`）。

统一 `message` tool 的 `action="send"` 还额外带一层 `source_intent` 语义：
- 高层 `SEND_MESSAGE_INTENT` 在 Outbox materialize 之前，会把 `text`、`images`、`render`、`at_user`、`reply_to`、`target` 保存在 `PlannedAction.metadata["source_intent"]`
- 低层 delivery action 继续只保留真正发送所需的 `SEND_SEGMENTS` / `SEND_TEXT`
- `OutboundMessageProjection.fact_text` 用于 `MessageRecord.content_text`，强调稳定、可搜索
- `OutboundMessageProjection.thread_text` 用于 thread working memory continuity，render 成功时也保留原始 markdown / LaTeX 文本，不退化成纯图片占位符
- 真实 `message.send` 不要求 tool 自己先产出 `thread_content`；只要 delivery action 能落地，Outbox 就会基于 `source_intent + delivery action` 自动补齐 continuity 文本

`OutboxItem` 现在显式保留两套目标语义：
- `origin_thread_id`：本轮 run 的来源 thread，也就是用户当前正在触发的 runtime thread。
- `destination_conversation_id`：真正要投递到的外部对话容器 ID。它是平台侧语义，告诉 Gateway 往哪个 conversation 发。
- `destination_thread_id`：真正落工作记忆、消息事实、LTM dirty 标记的 runtime thread。它是 runtime 侧语义，不一定等于来源 thread。
- `append_to_origin_thread`：当前送达内容是否还要补回来源 thread。普通同会话回复为 `True`，cross-session send 为 `False`。

`thread_id` 仍暂时保留给旧代码兼容，但新逻辑必须优先使用 `origin_thread_id` / `destination_thread_id`，不能再把 `conversation_id` 和 `thread_id` 当成一个字段混着传。

### 审批和恢复

`PendingApproval`（run 被工具打断后的审批现场）、`PendingApprovalRecord`（重启恢复后识别出的待审批记录）、`RecoveryReport`（启动恢复汇总）。

### AgentRuntimeResult

`contracts/context.py`。agent runtime 执行完后的返回（`status`、`text`、`actions`、`artifacts`、`usage`、`tool_calls`、`model_used`、`error`、`pending_approval`、`metadata`、`raw`）。不是最终送达结果——真正发送后的结果在 DispatchReport 里。

默认 assistant 文本回复是否要追加，也在这一层决定：`ModelAgentRuntime._to_runtime_result()` 只要看到已提交动作里存在 `ActionType.SEND_MESSAGE_INTENT` 且 `metadata["suppresses_default_reply"] is True`，就不再额外补一条 `SEND_TEXT`。`REACTION` / `RECALL` 这类非内容型动作即使 metadata 里带了同名标记，也不会触发抑制。

### RunStep

`contracts/context.py`。run 内部的步骤记录（`step_id`、`run_id`、`step_type`、`status`、`thread_id`、`payload`、`created_at`）。computer、approval、恢复、pipeline 收尾的细节都会写到这里。

---

## 四、持久化事实

定义在 `contracts/records.py`。

### ChannelEventRecord

平台上真的发生过这条事件。关键字段：`event_uid`、`thread_id`、`actor_id`、`channel_scope`、`platform`、`event_type`、`message_type`、`content_text`、`payload_json`、`timestamp`、`run_id`、`raw_message_id`。不是 assistant 回复事实。

### MessageRecord

系统真的发送成功了一条消息。关键字段：`message_uid`、`thread_id`、`actor_id`、`platform`、`role`、`content_text`、`content_json`、`timestamp`、`run_id`、`platform_message_id`。没有真正送达的动作不该写成 MessageRecord。

对统一 `message.send` 来说，当前持久化约定是：
- `content_text` 记录稳定 facts 摘要，图片继续记成 `[图片]`
- `content_json` 记录最终 delivery payload
- `metadata["thread_content"]` 记录 working memory continuity 文本
- `metadata["source_intent"]` 保留 materialize 之前的高层发送语义
- `content_text` 和 `metadata["thread_content"]` 可以不同步: 前者偏事实检索，后者偏连续性输入

---

## 总览对照表

| 阶段 | 对象 |
|------|------|
| 外部输入输出 | StandardEvent、Action |
| 会话决策 | EventFacts、MatchSpec、SessionConfig、SurfaceResolution、各 Decision、RouteDecision |
| 执行现场 | ResolvedAgent、ThreadState、RunRecord、RunContext、PendingApproval、AgentRuntimeResult、PlannedAction、DispatchReport、RunStep |
| 持久化事实 | ThreadRecord、ChannelEventRecord、MessageRecord、PendingApprovalRecord、RecoveryReport |

## 改契约时的检查清单

每次改数据契约，确认五件事：
1. 谁创建它
2. 谁消费它
3. 谁保存它
4. control plane / WebUI 会不会受影响
5. 测试里有没有还在按旧字段理解它
