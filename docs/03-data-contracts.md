# 核心数据契约

这一篇只讲跨模块会传来传去的那些对象。

如果你没搞清楚这些对象分别代表什么，后面很容易改偏。现在最重要的不是旧 rule 那套名字，而是下面这四层：

1. 外部输入和输出
2. 会话决策
3. 执行现场
4. 持久化事实

可以先记一句话：

- 外部世界先变成 `StandardEvent`
- `SessionRuntime` 把它变成一组决策结果
- `RuntimeApp` 和 `ThreadPipeline` 把这些决策塞进 `RunContext`
- 最后再把该保存的东西写成 `RunRecord`、`ThreadRecord`、`ChannelEventRecord`、`MessageRecord`、`MemoryItem`

---

## 一、外部输入和输出契约

## `StandardEvent`

定义在：

- `src/acabot/types/event.py`

这是外部事件进入 runtime 之后的统一格式。

它表达的是：

> **平台上刚刚发生了什么。**

常见重点字段有：

- `event_id`
- `event_type`
- `platform`
- `timestamp`
- `source`
  - 里面会带 `platform / message_type / user_id / group_id`
- `segments`
- `attachments`
- `reply_reference`
- `mentions_self`
- `reply_targets_self`
- `targets_self`
- `bot_relation`
- `target_reasons`
- `text`
- `metadata`
- `raw_event`

### 它的边界

`StandardEvent` 只负责把平台事件标准化。

它不是：

- 路由结果
- profile 决策
- memory 结果
- thread 上下文

### 改它会影响哪里

如果你改了 `StandardEvent` 的字段，通常要一起检查：

- gateway 翻译层
- `RuntimeRouter`
- `SessionRuntime.build_facts(...)`
- `RuntimeApp.handle_event()`
- `ThreadPipeline`
- 消息整理相关服务

---

## `Action`

定义在：

- `src/acabot/types/action.py`

这是系统对外动作的统一格式。

它表达的是：

> **系统打算对外做什么。**

常见重点字段有：

- `action_type`
- `target`
- `payload`
- `reply_to`

常见动作类型包括：

- `SEND_TEXT`
- `SEND_SEGMENTS`
- `RECALL`
- `GROUP_BAN`
- `GROUP_KICK`
- `TYPING`
- `REACTION`

### 它的边界

`Action` 只是动作本身，不包含：

- 这是谁规划出来的
- 这次动作在 thread 里要不要写 working memory
- 发出去后要不要记成消息事实

这些都在别的契约里表达。

---

## 二、会话决策契约

这一层是现在最容易看错、也最值得先搞懂的一层。

当前系统不是旧的 `binding / inbound / event policy` 主线了。
现在真正的决策主线是：

- `EventFacts`
- `MatchSpec`
- `SessionConfig`
- `SurfaceResolution`
- 各种 domain decision
- `RouteDecision`

这些对象主要定义在：

- `src/acabot/runtime/contracts/session_config.py`
- `src/acabot/runtime/contracts/routing.py`

---

## `EventFacts`

定义在：

- `runtime/contracts/session_config.py`

它表达的是：

> **把 `StandardEvent` 收成当前决策系统能稳定消费的一组事实。**

常见字段有：

- `platform`
- `event_kind`
- `scene`
- `actor_id`
- `channel_scope`
- `thread_id`
- `targets_self`
- `mentions_self`
- `reply_targets_self`
- `mentioned_everyone`
- `sender_roles`
- `attachments_present`
- `attachment_kinds`
- `message_subtype`
- `notice_type`
- `notice_subtype`
- `metadata`

### 它和 `StandardEvent` 的区别

- `StandardEvent` 更像平台事件原始标准化结果
- `EventFacts` 更像给 `SessionRuntime` 用的决策输入

比如：

- `actor_id`
- `channel_scope`
- `thread_id`

这些已经是 runtime 自己的稳定标识了，不再只是平台字段。

---

## `MatchSpec`

定义在：

- `runtime/contracts/session_config.py`

它表达的是：

> **一条针对 `EventFacts` 的匹配条件。**

它会被 `SessionRuntime` 用来判断：

- 当前消息命中了哪个 selector
- 当前 domain case 能不能生效

常见匹配字段包括：

- `platform`
- `event_kind`
- `scene`
- `actor_id`
- `channel_scope`
- `thread_id`
- `targets_self`
- `mentions_self`
- `reply_targets_self`
- `mentioned_everyone`
- `sender_roles`
- `attachments_present`
- `attachment_kinds`
- `message_subtype`
- `notice_type`
- `notice_subtype`

### 它的作用

`MatchSpec` 是共享 matcher。
它自己不表达“该怎么做”，只表达“这条消息像不像某种情况”。

---

## `SessionConfig`

定义在：

- `runtime/contracts/session_config.py`

它表达的是：

> **某个会话当前使用的配置真源。**

常见字段有：

- `session_id`
- `template_id`
- `title`
- `frontstage_profile`
- `selectors`
- `surfaces`
- `metadata`

### 它不是万能大桶

`SessionConfig` 不是把所有逻辑都写成一堆平铺字段，而是按 surface 和 domain 来组织：

- 哪类消息先命中哪个 surface
- 命中之后，各个 domain 再分别给出 routing / admission / context / persistence / extraction / computer 的结果

这也是现在和旧 rule 系统最大的区别之一。

---

## `SurfaceConfig` 和 `SurfaceResolution`

也定义在：

- `runtime/contracts/session_config.py`

### `SurfaceConfig`

它表达的是：

> **某个 surface 下，各个决策域默认该怎么配。**

它会带这些域：

- `routing`
- `admission`
- `context`
- `persistence`
- `extraction`
- `computer`

### `SurfaceResolution`

它表达的是：

> **当前消息最后命中了哪个 surface。**

常见字段有：

- `surface_id`
- `exists`
- `source`
- `metadata`

### 这两个对象的区别

- `SurfaceConfig` 是配置
- `SurfaceResolution` 是当前这条消息命中的结果

---

## `DomainCase` 和各类 `DomainConfig`

也定义在：

- `runtime/contracts/session_config.py`

### `DomainCase`

表示某个决策域下的一条局部 case。

常见字段：

- `case_id`
- `when`
- `when_ref`
- `use`
- `priority`
- `metadata`

### 各类 `DomainConfig`

当前有：

- `RoutingDomainConfig`
- `AdmissionDomainConfig`
- `ContextDomainConfig`
- `PersistenceDomainConfig`
- `ExtractionDomainConfig`
- `ComputerDomainConfig`

它们都继承同一套形状：

- `default`
- `cases`

也就是说：

- 先吃默认配置
- 再按 case 做局部覆盖

---

## 各种 decision 对象

这些对象都定义在：

- `runtime/contracts/session_config.py`

它们表达的是：

> **当前这条消息，在某个决策域最后算出来的结果。**

当前最重要的有：

- `RoutingDecision`
- `AdmissionDecision`
- `ContextDecision`
- `PersistenceDecision`
- `ExtractionDecision`
- `ComputerPolicyDecision`

### `RoutingDecision`

它会告诉后面：

- 当前该走哪个 profile
- 当前 actor lane 是什么
- 命中了哪条 case

### `AdmissionDecision`

它最重要的字段是：

- `mode`

当前主线最关心的几个模式是：

- `respond`
- `record_only`
- `silent_drop`

### `ContextDecision`

它会告诉后面：

- sticky note 作用域
- prompt slots
- retrieval tags
- context labels
- notes

### `PersistenceDecision`

它会告诉后面：

- 这条 event 要不要持久化

### `ExtractionDecision`

它会告诉后面：

- 要不要提取长期记忆
- memory scopes 是什么
- tags 是什么

### `ComputerPolicyDecision`

它会告诉后面：

- 当前 world 用哪个 backend
- 当前能不能 `bash`
- 当前能不能开内部 shell session
- `/workspace /skills /self` 哪些 root 可见
- 当前可见 skill 列表

这个对象后面会直接影响：

- `ComputerRuntime`
- Work World 构造
- 前台 builtin tools 的真实可见性

---

## `RouteDecision`

定义在：

- `runtime/contracts/routing.py`

它表达的是：

> **router 最终交给 app / pipeline 的统一决策结果。**

常见字段有：

- `thread_id`
- `actor_id`
- `agent_id`
- `channel_scope`
- `run_mode`
- `metadata`
- `event_facts`
- `surface_resolution`
- `routing_decision`
- `admission_decision`
- `context_decision`
- `persistence_decision`
- `extraction_decision`
- `computer_policy_decision`

### 它的意义

`RouteDecision` 不是一条轻飘飘的“路由结果”，而是当前消息大部分关键决策的统一承载对象。

后面 `RuntimeApp`、`ThreadPipeline`、`ComputerRuntime` 都会直接吃它。

---

## 三、执行现场契约

这一层的对象主要定义在：

- `runtime/contracts/routing.py`
- `runtime/contracts/context.py`
- `runtime/contracts/records.py`

它们表达的是：

> **这一轮执行现在进行到哪一步了，手里有哪些材料。**

---

## `AgentProfile`

定义在：

- `runtime/contracts/routing.py`

它表达的是：

> **这次 run 应该以什么身份和能力运行。**

常见字段有：

- `agent_id`
- `name`
- `prompt_ref`
- `default_model`
- `enabled_tools`
- `skills`
- `computer_policy`
- `config`

### 它的边界

`AgentProfile` 是静态配置快照，不是运行中的状态对象。

它不该承载：

- 本轮临时决策
- 当前 memory 检索结果
- 当前工具调用现场

---

## `ThreadState` 和 `ThreadRecord`

定义在：

- `runtime/contracts/records.py`

### `ThreadState`

它表达的是：

> **当前 thread 在 runtime 里的工作上下文。**

常见字段有：

- `thread_id`
- `channel_scope`
- `thread_kind`
- `working_messages`
- `working_summary`
- `last_event_at`
- `metadata`
- `lock`

### `ThreadRecord`

它表达的是：

> **`ThreadState` 的可持久化版本。**

它和 `ThreadState` 最大的区别就是：

- `ThreadRecord` 没有运行时锁
- `ThreadState` 才能直接进主线

### 这两个对象最容易被误用

它们都不是：

- 长期记忆
- 全量聊天档案
- 平台事实日志

它们只负责：

- 当前 thread 的工作上下文

---

## `RunRecord`

定义在：

- `runtime/contracts/records.py`

它表达的是：

> **一次正式执行的生命周期记录。**

常见字段有：

- `run_id`
- `thread_id`
- `actor_id`
- `agent_id`
- `trigger_event_id`
- `status`
- `started_at`
- `finished_at`
- `error`
- `approval_context`
- `metadata`

常见状态包括：

- `queued`
- `running`
- `waiting_approval`
- `interrupted`
- `completed`
- `completed_with_errors`
- `failed`
- `cancelled`

### 它常在哪些地方重要

如果你在看这些能力，通常都要看 `RunRecord`：

- approval
- 续执行
- 恢复启动
- active run 查询
- control plane run 列表

---

## `RunContext`

定义在：

- `runtime/contracts/context.py`

它表达的是：

> **`ThreadPipeline` 执行这一轮 run 时共享的现场对象。**

你可以把它理解成这次执行的总篮子。

当前最重要的字段包括：

- 基础现场：
  - `run`
  - `event`
  - `decision`
  - `thread`
  - `profile`
- 模型请求：
  - `model_request`
  - `summary_model_request`
- 会话决策：
  - `event_facts`
  - `surface_resolution`
  - `routing_decision`
  - `admission_decision`
  - `context_decision`
  - `persistence_decision`
  - `extraction_decision`
  - `computer_policy_decision`
- computer 现场：
  - `world_view`
  - `workspace_state`
  - `attachment_snapshots`
  - `computer_backend_kind`
  - `computer_policy_effective`
- 消息整理：
  - `resolved_message`
  - `resolved_images`
  - `message_projection`
- 模型输入和记忆：
  - `messages`
  - `retrieval_plan`
  - `memory_blocks`
  - `prompt_slots`
  - `memory_user_content`
  - `system_prompt`
- 执行结果：
  - `response`
  - `actions`
  - `delivery_report`
  - `metadata`

### 现在改主线时的习惯

如果你需要在 pipeline 里共享一个中间结果，优先考虑把它正式放进 `RunContext`。

不要一层层发明临时局部变量再手工往下传，那样后面会越来越难看。

---

## `PendingApproval`、`PendingApprovalRecord`、`RecoveryReport`

分别定义在：

- `runtime/contracts/context.py`
- `runtime/contracts/records.py`

### `PendingApproval`

它表达的是：

> **当前 run 被工具打断后，等待审批的现场信息。**

常见字段有：

- `approval_id`
- `reason`
- `tool_name`
- `tool_call_id`
- `tool_arguments`
- `required_action_ids`
- `metadata`

### `PendingApprovalRecord`

它表达的是：

> **重启恢复后，系统重新识别出来的待审批记录。**

它比 `PendingApproval` 更偏恢复和管理。

### `RecoveryReport`

它表达的是：

> **一次启动恢复之后，总共恢复出了什么。**

常见字段有：

- `interrupted_run_ids`
- `pending_approvals`

---

## `AgentRuntimeResult`

定义在：

- `runtime/contracts/context.py`

它表达的是：

> **一次 agent runtime 执行完后，系统拿到的结果。**

常见字段有：

- `status`
- `text`
- `actions`
- `artifacts`
- `usage`
- `tool_calls`
- `model_used`
- `error`
- `pending_approval`
- `metadata`
- `raw`

### 它的边界

它不是最终送达结果。

它表达的是：

- 模型和 agent 这一层给 runtime 的返回

真正发送后的结果在 `DispatchReport` 里。

---

## `PlannedAction`、`DeliveryResult`、`OutboxItem`、`DispatchReport`

定义在：

- `runtime/contracts/context.py`

这几个对象一起表达：

> **系统打算发什么，实际发成了什么。**

### `PlannedAction`

表示一条待发送动作的规划结果。

常见字段有：

- `action_id`
- `action`
- `thread_content`
- `commit_when`
- `metadata`

### `DeliveryResult`

表示单个动作的投递结果。

常见字段有：

- `action_id`
- `ok`
- `platform_message_id`
- `error`
- `raw`

### `OutboxItem`

表示 Outbox 真正发送的一条项目。

常见字段有：

- `thread_id`
- `run_id`
- `agent_id`
- `plan`
- `metadata`

### `DispatchReport`

表示一批动作整体发完后的汇总结果。

常见字段有：

- `results`
- `delivered_items`
- `failed_action_ids`
- `has_failures`

---

## `RunStep`

定义在：

- `runtime/contracts/context.py`

它表达的是：

> **一次 run 内部发生过的一个步骤记录。**

常见字段有：

- `step_id`
- `run_id`
- `step_type`
- `status`
- `thread_id`
- `payload`
- `created_at`

这个对象现在很重要，因为很多 computer、approval、恢复、pipeline 收尾的细节都会往这里写。

---

## `ResolvedMessage`、`ResolvedImageInput`、`MessageProjection`、`RetrievalPlan`

这些对象主要定义在：

- `runtime/contracts/context.py`

它们表达的是当前消息整理和上下文组装的中间结果。

### `ResolvedImageInput`

表示当前 run 里已经解析好的单张图片输入。

### `ResolvedMessage`

表示当前消息和 reply、图片等材料都已经补齐之后的结果。

### `MessageProjection`

表示同一条消息按不同用途投影后的结果，比如：

- history 版本
- model 版本
- 给 memory 用的候选材料

### `RetrievalPlan`

表示进入模型前的上下文准备计划。

它会带：

- requested scopes
- requested tags
- sticky note scopes
- compaction 后保留下来的消息
- dropped messages
- prompt slots
- metadata

如果你要改：

- 消息怎么进 history
- 图片怎么进入模型输入
- retrieval 前后上下文怎么拼

这些对象都值得先看。

---

## 四、持久化事实契约

这一层的对象主要定义在：

- `runtime/contracts/records.py`

它们表达的是：

> **系统最后真正保存下来的事实。**

---

## `ChannelEventRecord`

它表达的是：

> **平台上真的发生过这条事件。**

常见字段有：

- `event_uid`
- `thread_id`
- `actor_id`
- `channel_scope`
- `platform`
- `event_type`
- `message_type`
- `content_text`
- `payload_json`
- `timestamp`
- `run_id`
- `raw_message_id`
- `operator_id`
- `target_message_id`
- `metadata`
- `raw_event`

它不是 assistant 回复事实，也不是 memory 项。

---

## `MessageRecord`

它表达的是：

> **系统真的发送成功了一条消息。**

常见字段有：

- `message_uid`
- `thread_id`
- `actor_id`
- `platform`
- `role`
- `content_text`
- `content_json`
- `timestamp`
- `run_id`
- `platform_message_id`
- `metadata`

如果某个动作没有真正送达，就不该假装写成 `MessageRecord`。

---

## `MemoryItem`

它表达的是：

> **一条可持久化的长期记忆项。**

常见字段有：

- `memory_id`
- `scope`
- `scope_key`
- `memory_type`
- `content`
- `edit_mode`
- `author`
- `confidence`
- `source_run_id`
- `source_event_id`
- `tags`
- `metadata`
- `created_at`
- `updated_at`

### 它当前的真实定位

它现在更像：

- 一个能存记忆项的仓库
- 一个能做最小 retrieval 和 extraction 的基础结构

它还不是一个已经完整成型的复杂记忆图谱系统。

---

## 最后给一张够用的对照表

### 外部世界进来

- `StandardEvent`

### 会话决策阶段

- `EventFacts`
- `MatchSpec`
- `SessionConfig`
- `SurfaceResolution`
- 各种 decision
- `RouteDecision`

### 一次执行的现场

- `AgentProfile`
- `ThreadState`
- `RunRecord`
- `RunContext`
- `PendingApproval`
- `AgentRuntimeResult`
- `PlannedAction`
- `DispatchReport`
- `RunStep`

### 最终保存下来的事实

- `ThreadRecord`
- `ChannelEventRecord`
- `MessageRecord`
- `MemoryItem`
- `PendingApprovalRecord`
- `RecoveryReport`

---

## 改契约时最重要的几件事

字段加了，不等于系统就真的支持了。

每次改数据契约，至少顺手确认这五件事：

1. 谁创建它
2. 谁消费它
3. 谁保存它
4. control plane / WebUI 会不会受影响
5. 测试里有没有还在按旧字段理解它

如果你不确定从哪里开始，先看这几个目录：

- `src/acabot/runtime/contracts/`
- `src/acabot/runtime/control/session_runtime.py`
- `src/acabot/runtime/app.py`
- `src/acabot/runtime/pipeline.py`
- `src/acabot/runtime/storage/`
