# 核心数据契约

这一篇讲跨模块传来传去的那些对象。

如果你没搞清楚这些对象分别代表什么，后面基本都会改偏。

## `StandardEvent`

定义在 `src/acabot/types/event.py`。

这是外部事件进入 runtime 之后的统一格式。

重点字段:

- `event_type`
  现在不只是 message，也包括 poke、recall、member_join 之类 notice 事件。
- `source`
  里面有 `platform / message_type / user_id / group_id`
- `segments`
  原始消息段的 canonical 版本
- `attachments`
  统一附件引用，图片、文件、音频、视频都往这里收
- `reply_reference`
  被引用消息的信息
- `mentioned_user_ids / mentioned_everyone / targets_self`
  路由和响应策略经常会用到
- `metadata / raw_event`
  平台特殊字段兜底

### 什么时候该改它

- 平台新事件要标准化
- 需要新增统一附件类型
- 需要补充 reply / quote / mention 信息

### 改它会波及哪里

- `gateway/napcat.py`
- `runtime/router.py`
- `runtime/control/event_policy.py`
- `runtime/app.py`
- `runtime/pipeline.py`


## `Action`

定义在 `src/acabot/types/action.py`。

这是系统对外动作的统一格式。

重点字段:

- `action_type`
- `target`
- `payload`
- `reply_to`

当前常见动作:

- `SEND_TEXT`
- `SEND_SEGMENTS`
- `RECALL`
- `GROUP_BAN`
- `GROUP_KICK`
- `TYPING`
- `REACTION`

### 注意

新增动作类型不是只改枚举就完事，还要同时确认:

- agent / tool 会不会产出这种动作
- `Outbox` 要不要把它记成消息事实
- `Gateway.send()` 能不能翻译成平台 API

## `RouteDecision`

真实定义在 `runtime/contracts/routing.py`。

它是“这条事件接下来怎么跑”的最小决定书。

重点看这些字段:

- `thread_id`
- `actor_id`
- `agent_id`
- `channel_scope`
- `run_mode`
- `metadata`

很多后续逻辑其实都不重新算，而是吃这里已经算好的结果。

### `metadata` 很关键

这里会混入:

- binding rule 命中信息
- inbound rule 命中信息
- event policy 决定
- 其他路由时产生的附加信息

如果你要让后续阶段拿到某个路由判断结果，通常应该从这里传，不要在 pipeline 里再算一遍。

## `RunRecord`

真实定义在 `runtime/contracts/records.py`。

这是正式的执行生命周期记录，不是临时现场。

常见状态:

- `queued`
- `running`
- `waiting_approval`
- `interrupted`
- `completed`
- `completed_with_errors`
- `failed`
- `cancelled`

### 什么时候重点看它

- approval 中断
- 子任务 / 恢复执行
- 控制面查看 active runs

## `RunContext`

这是一轮执行的现场包。

可以把它理解成“主线里所有组件共享的上下文篮子”。

里面会逐步填进:

- `run`
- `event`
- `decision`
- `thread`
- `profile`
- `messages`
- `actions`
- `response`
- `delivery_report`
- `memory_blocks`
- `metadata`

### 改主线时的习惯

优先在 `RunContext` 上补充中间态，而不是发明一堆零散局部变量传来传去。这个项目已经在走这种风格。

## `ThreadState`

真实定义在 `runtime/contracts/records.py`，由 `ThreadManager` 管。

它表达的是当前线程运行时上下文，不是数据库记录。

核心字段:

- `working_messages`
- `working_summary`
- `last_event_at`
- `metadata`
- `lock`

### 这个对象最容易被误用

它不是:

- 长期记忆
- 历史全量消息档案
- event log

它只是当前 thread 的工作上下文容器。

## `ThreadRecord`

这是 `ThreadState` 的可持久化投影。

区别只有一个重点:

`ThreadRecord` 没有运行时锁，适合写库；`ThreadState` 才适合进 runtime 主线。

## `ChannelEventRecord`

这是外部事件事实表。

它代表“平台上真的发生过这个事件”，不是系统怎么理解它，也不是 assistant 回了什么。

常见用途:

- 控制面查看 thread 事件
- 后续检索 / 审计
- 记忆提取的事实来源

## `MessageRecord`

这是送达事实。

只有真正发出去并成功送达的 assistant 消息才该进这里。

如果某个能力只是内部草稿、审批中断、工具计划动作，还不该写这里。

## `MemoryItem`

这是长期记忆项，真实定义在 `runtime/contracts/records.py`。

重点字段:

- `scope / scope_key`
- `memory_type`
- `content`
- `edit_mode`
- `author`
- `confidence`
- `source_run_id / source_event_id`
- `tags`
- `metadata`

### 这套字段现在的真实定位

它还不是一个成熟的“长期记忆图谱系统”，更像是:

- 一个可持久化的记忆项仓库
- 支持最小 retrieval
- 支持最小 extraction

所以你要做长期记忆重构时，不要假设上层已经有很强的抽象。

## `AgentProfile`

这是 agent 的静态配置快照。

重点字段:

- `agent_id`
- `prompt_ref`
- `default_model`
- `enabled_tools`
- `skills`
- `computer_policy`
- `config`

### profile 的意义

它不是运行时状态，而是“这次 run 应该以什么身份和能力运行”的配置快照。

WebUI、profile loader、binding rule 最终都在影响这里。

## 一张简单对照表

### 进系统时

- `StandardEvent`

### 路由决定时

- `RouteDecision`

### 执行过程中

- `RunContext`
- `ThreadState`

### 持久化事实

- `ChannelEventRecord`
- `MessageRecord`
- `MemoryItem`
- `RunRecord`

## 改字段时最重要的原则

字段加了，不等于系统就真的支持了。

每次改契约，都要顺手确认:

1. 谁创建它
2. 谁消费它
3. 有没有旧兼容字段
4. 控制面 / WebUI 要不要跟着变
5. 持久化和日志会不会受影响
