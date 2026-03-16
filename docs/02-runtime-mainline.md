# runtime 主线怎么走

这一篇只讲一件事: 一条外部消息是怎么穿过系统的。

如果你要改主流程，先把这条线过一遍。

## 总流程

从启动到处理消息，大致是这样:

1. `main.py` 读配置
2. `build_runtime_components()` 组装 runtime
3. `RuntimeApp.start()` 启动 gateway、plugin 和恢复逻辑
4. Gateway 收到平台事件，翻译成 `StandardEvent`
5. `RuntimeApp.handle_event()` 接住事件
6. `RuntimeRouter.route()` 算出 `RouteDecision`
7. `ThreadManager` 找到或创建 `ThreadState`
8. `RunManager.open()` 创建 `RunRecord`
9. `ThreadPipeline.execute()` 跑完整主线
10. `Outbox` 发消息并落消息事实
11. `RunManager` 收尾，必要时触发 memory extraction

## 启动阶段

### `src/acabot/main.py`

这里只做三件事:

- 创建 gateway
- 创建 agent
- 调 `build_runtime_components()`

它不是业务入口，不要把主线逻辑塞回来。

### `src/acabot/runtime/bootstrap.py`

这是默认装配中心。

它负责把下面这些东西接起来:

- router
- thread manager
- run manager
- stores
- memory broker
- retrieval planner
- context compactor
- tool broker
- plugin manager
- control plane
- outbox
- pipeline
- app

如果你新增一个“系统级能力”，最合适的接入点通常在这里。

## 事件进入系统

### 1. Gateway 先做翻译

当前是 `NapCatGateway.translate()` 把 OneBot payload 翻译成 `StandardEvent`。

到这一步为止，应该只发生协议层事情:

- message / notice 类型识别
- segments 提取
- attachments 提取
- reply / mention / attachments 归一化
- `mentions_self` / `reply_targets_self` / `targets_self` 归一化
- 把这条消息和 bot 的关系整理成 `bot_relation` / `target_reasons`

### 2. `RuntimeApp.handle_event()`

这个方法是新的统一入口。

它主要做这些事:

- 打日志
- 调 plugin manager 确保启动
- 调 router 算路由
- 按路由创建 / 获取 thread
- 加载 profile 和 model request
- 创建 run
- 保存 channel event
- 构造 `RunContext`
- 调 pipeline

这里很适合放“入口级保护”或“路由失败兜底”，但不适合塞复杂业务。

## 路由阶段

### `RuntimeRouter.route()`

它会算出:

- `thread_id`
- `actor_id`
- `channel_scope`
- `agent_id`
- `run_mode`
- 这条消息和 bot 的关系元数据
- event policy 派生出来的 metadata

默认规则很直接:

- `actor_id = {platform}:user:{user_id}`
- `channel_scope = qq:group:{group_id}` 或 `qq:user:{user_id}`
- `thread_id` 现在默认和 `channel_scope` 一样

这意味着:

- 如果你改 thread 切分策略，会影响整个上下文隔离方式
- 如果你改 actor_id / channel_scope 格式，会影响 binding rule、memory scope、控制面查询

### 三种 `run_mode`

- `respond`
  正常进入完整主线
- `record_only`
  只记录，不调模型，不发回复
- `silent_drop`
  直接丢弃

很多人第一次看代码时会忽略 `record_only`。如果你在做“只记日志 / 只提取记忆 / 不回消息”的能力，这个模式很重要。

`silent_drop` 还有一个很重要的边界:

- 它会在 `RuntimeApp.handle_event()` 里尽早退出
- 不创建 run
- 不下载附件
- 不拉 reply
- 不写 thread working memory
- 不做 memory extraction

所以如果你在做“群里和 bot 无关的路过消息”，先看 route，而不是先看 pipeline。

## Pipeline 阶段

### `ThreadPipeline.execute()`

这是现在最需要小心改的文件之一。

顺序大致是:

1. `mark_running`
2. 跑 `ON_EVENT` hooks
3. 提前准备 `computer runtime`，把当前消息附件先 staging 到本地
4. 调 `MessagePreparationService.prepare()`:
   - `MessageResolutionService` 先把这条消息需要的材料拿全
   - 当前消息附件已经在本地时直接复用
   - 如果有 reply 而且配置允许，会重新取 reply 消息并把 reply 图片落到本地
   - `MessageProjectionService` 再生成这条消息的 history 版本、model 版本和给 memory 参考的候选材料
5. 把 history 版本 append 到 `thread.working_messages`
6. 如果是 `record_only`，提前收尾
7. 做 context compaction
8. 生成 retrieval plan，组装上下文
9. 注入长期记忆
10. 把当前轮最终要给模型看的那一版 user message 应用到 `ctx.messages`
11. 跑 `PRE_AGENT` hooks
12. 调 `agent_runtime.execute()`
13. 跑 `POST_AGENT` hooks
14. 通过 `Outbox` 发送动作
15. 更新 thread
16. 收尾 run
17. 触发 memory extraction

### 这里哪些点最常被改

#### 用户输入入线程

`_append_incoming_message()`

如果你要改“用户消息怎样投影到上下文”，通常会碰这里。

现在要注意一点:

- 它不再总是直接写 `event.working_memory_text`
- 如果消息整理层已经生成了 history 版本, 就优先写那一版
- 图片说明这类系统补充内容会带显式标记, 不伪装成用户原话

#### retrieval 前后

如果你要加图片理解、额外 memory block、上下文注入规则，一般会碰:

- `prepare_run_context`
- `MessagePreparationService.prepare()`
- `MessageResolutionService`
- `MessageProjectionService`
- `ImageContextService`
- `_inject_memories`
- `MessagePreparationService.apply_model_message()`
- retrieval planner

#### agent 前后 hook

如果能力更像“横切逻辑”，而不是主线硬编码，优先考虑 plugin hook，而不是直接改 pipeline 中段。

#### 发送与落库

如果你改回复动作的结构、消息事实记录方式，重点看 `Outbox`，不要只改 agent 输出。

## Agent 阶段

### `ModelAgentRuntime.execute()`

这个文件负责把 `RunContext` 变成一次 `BaseAgent.run()` 调用。

它做的事:

- 读 `prompt_ref`
- 解析当前 run 的 tools
- 校验模型能力
- 调真正的 agent
- 把 agent response 变成 runtime 认识的结果

它不负责:

- memory retrieval
- tool policy
- approval 策略

如果你想接 VLM 或图片输入，往往要同时考虑:

- 这里的模型能力判断
- `ctx.messages` 里塞进去的消息格式
- `computer / attachment` 准备逻辑

当前实现里，图片能力不是只改 `ModelAgentRuntime`：

- working memory 里的图片描述先在消息整理阶段生成, 再写进 thread
- 当前轮真正的 vision image parts 也是消息整理阶段先准备好, `_inject_memories()` 之后再应用到最后一条 user message

## Outbox 阶段

### `src/acabot/runtime/outbox.py`

这里只有一条原则最重要:

只有真正产生“消息事实”的动作，才写入 `MessageStore`。

所以:

- `SEND_TEXT`
- `SEND_SEGMENTS`

会写消息事实。

但像群管理动作、状态动作，不该伪装成 assistant message。

## 收尾阶段

主线跑完后还有两件常被忽略的事:

### 1. thread 收尾

`ThreadState` 会被更新并保存。你如果只盯着回复逻辑，不看 thread 收尾，很容易把 working memory 搞乱。

### 2. memory extraction

memory write-back 不在 agent 前做，而是在 run 收尾后由 `MemoryBroker.extract_after_run()` 触发。

所以长期记忆相关改动，不要只盯 retrieval。

## 改主线时的实用建议

### 想插一个新能力，先判断它属于哪种

- 协议翻译: 改 gateway
- 路由和 run_mode: 改 router / profile / event policy
- 上下文准备: 改 pipeline / retrieval / compactor
- 模型调用: 改 model agent runtime / agent
- 工具调用: 改 tool broker / plugin
- 回复发送: 改 outbox / gateway

### 尽量不要在 `RuntimeApp.handle_event()` 里越改越多

那个文件最适合做入口级编排，不适合承载“真正业务逻辑”。

### `pipeline.py` 能不硬编码就别硬编码

如果能力本质上像:

- hook
- tool
- plugin
- 可选组件

优先走这些扩展点。否则主线会越来越难看。
