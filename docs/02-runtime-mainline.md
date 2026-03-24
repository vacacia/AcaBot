# runtime 主线怎么走

这一篇只讲一件事：

**一条外部消息现在是怎么穿过系统的。**

如果你要改主流程，先把这条线过一遍。不要先翻旧的 rule、旧 shell、旧 webui 壳。
当前真正的主线是：

`Gateway -> RuntimeApp -> RuntimeRouter -> SessionRuntime -> ThreadPipeline -> AgentRuntime -> Outbox`

---

## 先讲结论

现在最重要的几个入口文件是：

- `src/acabot/main.py`
- `src/acabot/runtime/bootstrap/__init__.py`
- `src/acabot/runtime/app.py`
- `src/acabot/runtime/router.py`
- `src/acabot/runtime/control/session_runtime.py`
- `src/acabot/runtime/pipeline.py`

它们分别负责：

- `main.py`
  - 启动程序
  - 创建 gateway 和 agent
  - 调 `build_runtime_components()`
- `bootstrap/__init__.py`
  - 把整套 runtime 组件接起来
- `app.py`
  - 接住 gateway 送进来的标准事件
  - 做最小入口分流
  - 创建 `RunContext`
  - 把执行交给 pipeline
- `router.py`
  - 把 `SessionRuntime` 的结果收口成 `RouteDecision`
- `control/session_runtime.py`
  - 真正按 `SessionConfig` 计算 surface、routing、admission、context、persistence、extraction、computer 决策
- `pipeline.py`
  - 执行一次 run 的完整主线

---

## 总流程

从启动到处理消息，当前主线大致是这样：

1. `main.py` 读配置，创建 gateway 和 agent
2. `build_runtime_components()` 组装 runtime
3. `RuntimeApp.start()` 启动 gateway，并确保 plugin manager 已经启动
4. Gateway 收到平台事件，翻译成 `StandardEvent`
5. `RuntimeApp.handle_event()` 接住事件
6. `RuntimeRouter.route()` 调 `SessionRuntime` 算出 `RouteDecision`
7. `RuntimeApp` 根据决策加载 profile、解析模型请求、创建 thread 和 run
8. `RuntimeApp` 构造 `RunContext`
9. `ThreadPipeline.execute()` 跑完整执行流程
10. `AgentRuntime` 调模型，生成动作
11. `Outbox` 发送动作并记录消息事实
12. pipeline 收尾，保存 thread，结束 run

这条线里，真正容易看错的地方有两个：

- **路由决策中心已经是 `SessionRuntime`，不是旧 rule 系统。**
- **前台工具已经是 builtin tool + ToolBroker + ComputerRuntime，不是旧的 computer tool adapter plugin。**

---

## 启动阶段

## `src/acabot/main.py`

这里只做启动接线：

- 创建 gateway
- 创建 agent
- 调 `build_runtime_components()`
- 启动 app

它不是业务主线本体。不要把“该不该回复”“怎么路由”“怎么构造 world”这种逻辑塞回这里。

## `src/acabot/runtime/bootstrap/__init__.py`

这里是默认装配中心。

当前它会接好这些东西：

- profile loader / prompt loader
- `SessionRuntime`
- `RuntimeRouter`
- thread manager / run manager
- stores
- memory broker / retrieval planner / context compactor
- `ComputerRuntime`
- `ToolBroker`
- builtin tools
- runtime plugins
- `ThreadPipeline`
- `RuntimeApp`
- control plane / http api

如果你新增一个系统级能力，最先应该看这里要不要接线。

### 现在这里有两个很重要的事实

#### 1. core tool 已经不是 plugin 了

启动时会直接调用：

- `register_core_builtin_tools(...)`

把这些基础工具注册进 `ToolBroker`：

- `builtin:computer`
- `builtin:skills`
- `builtin:subagents`

前台基础工具现在固定是：

- `read`
- `write`
- `edit`
- `bash`

#### 2. runtime plugin 现在只代表外部扩展

plugin manager 还在，但它不再承载 `read / write / edit / bash` 这种基础工具。

---

## 事件进入系统

## 1. Gateway 先做协议翻译

平台事件先进入 gateway。

比如 NapCat 这层会把 OneBot payload 翻译成统一的 `StandardEvent`。

到这一步为止，应该只发生协议层事情，例如：

- message / notice 类型识别
- segments 提取
- attachments 提取
- reply / mention / attachments 归一化
- `mentions_self` / `reply_targets_self` / `targets_self` 归一化
- 整理 `bot_relation` 和 `target_reasons`

这一步不该承载“该不该回复”“该走哪个 profile”“要不要提取记忆”这些运行时决策。

## 2. `RuntimeApp.handle_event()`

这是当前统一入口。

它主要做这些事：

- 打日志
- 先检查后台硬入口
- 确保 plugin manager 已启动
- 调 router 计算 `RouteDecision`
- 处理 `silent_drop`
- 创建或获取 `ThreadState`
- 加载 profile
- 解析当前 run 要用的模型请求
- 创建 `RunRecord`
- 保存 channel event
- 构造 `RunContext`
- 调 `ThreadPipeline.execute()`

这里的职责是：

> **接线、分流、组装上下文。**

它不该慢慢长成一个大业务文件。

### 后台硬入口也在这里

当前实现里，管理员后台入口仍然是在 `RuntimeApp.handle_event()` 这里做最小分流。

但要注意一点：

- 不是只要 backend bridge 对象存在就能进后台
- 只有 bootstrap 真的构造出 configured backend session service 时，后台入口才打开

也就是说，后台入口属于 app 的最小接线，不属于前台主流程本体。

---

## 路由阶段

## `RuntimeRouter.route()`

`RuntimeRouter` 现在很薄。

它自己不再维护一套复杂规则系统，而是做这件事：

- 把 `StandardEvent` 交给 `SessionRuntime`
- 把 `SessionRuntime` 算出来的各类决策收口成 `RouteDecision`

所以现在真正的消息决策中心不是 router 本身，而是：

- `src/acabot/runtime/control/session_runtime.py`

## `SessionRuntime`

`SessionRuntime` 当前会按顺序做这些事：

1. `build_facts(event)`
   - 把平台事件标准化成 `EventFacts`
2. `load_session(facts)`
   - 定位并读取当前消息对应的 `SessionConfig`
3. `resolve_surface(facts, session)`
   - 算当前消息命中的 surface
4. `resolve_routing(...)`
   - 算当前消息要走哪个 profile / actor lane
5. `resolve_admission(...)`
   - 算 `respond / record_only / silent_drop`
6. `resolve_context(...)`
   - 算 retrieval tags、sticky note scopes、context labels 这些上下文输入
7. `resolve_persistence(...)`
   - 算 event 是否持久化
8. `resolve_extraction(...)`
   - 算当前 event 带哪些长期记忆 tags
9. `resolve_computer(...)`
   - 算当前 run 的 computer/backend 决策

最后 `RuntimeRouter` 再把这些东西装成 `RouteDecision`。

### 这里现在最重要的结论

如果你想改：

- 这条消息该不该回复
- 这条消息该走哪个 profile
- 这条消息该用 host 还是 docker
- 这条消息是否只记录不回复
- 这条消息命中哪个 frontstage surface

先看：

- `src/acabot/runtime/control/session_runtime.py`

而不是去找旧的：

- `binding rule`
- `inbound rule`
- `event policy`

这些已经不是当前主线了。

### 当前 `run_mode`

现在最关键的三种模式还是：

- `respond`
  - 正常进入完整主线
- `record_only`
  - 记录，但不调模型、不发送回复
- `silent_drop`
  - 尽早退出

其中 `silent_drop` 很关键，因为它会让 `RuntimeApp` 在很前面就停下：

- 不创建正常 run 主线
- 不进入 pipeline
- 不做附件准备
- 不改 thread working memory
- 不继续后面的前台运行主线

所以如果你在改“和 bot 无关的路过消息”，先看 route，不要先改 pipeline。

---

## `RunContext` 是怎么组出来的

`RuntimeApp.handle_event()` 在拿到 `RouteDecision` 之后，会继续做这些事：

- 创建或获取 `ThreadState`
- 加载 `AgentProfile`
- 解析当前 run 的主模型和 summary 模型请求
- 创建 `RunRecord`
- 保存 `ChannelEventRecord`
- 组装 `RunContext`

`RunContext` 里现在已经不只是 thread 和 run，还会带上这些由 `SessionRuntime` 算出来的东西：

- `event_facts`
- `surface_resolution`
- `routing_decision`
- `admission_decision`
- `context_decision`
- `persistence_decision`
- `extraction_decision`
- `computer_policy_decision`

也就是说，pipeline 接手时，当前 run 的主要决策已经基本齐了。

---

## Pipeline 阶段

## `ThreadPipeline.execute()`

这是当前最应该小心改的主流程文件之一。

它负责把一条 `RunContext` 真的执行完。

当前顺序大致是：

1. `mark_running`
2. 跑 `ON_EVENT` hooks
3. `computer_runtime.prepare_run_context(ctx)`
4. `message_preparation_service.prepare(ctx)`
5. 把用户输入写进 thread working memory
6. 如果是 `record_only`，提前收尾
7. 做 context compaction
8. 准备 retrieval plan
9. 通过 `MemoryBroker` 取 `/self`、sticky notes 和长期记忆
10. 跑 `PRE_AGENT` hooks
11. 调 `agent_runtime.execute(ctx)`
12. 跑 `POST_AGENT` hooks
13. 通过 `Outbox` 发送动作
14. 更新 thread
15. 收尾 run

## 这里现在真正重要的几个点

### 1. computer 准备已经进主线了

现在 pipeline 很早就会调：

- `computer_runtime.prepare_run_context(ctx)`

这一步会准备：

- 当前 run 的 world
- workspace 状态
- 附件 staging
- 当前可见的 computer 工具状态

所以如果你要改：

- `/workspace /skills /self`
- 附件怎么进 world
- 当前 run 能不能看到 `bash`
- 当前 run 的 backend 是什么

先看 `ComputerRuntime` 和 session 的 computer 决策，不要直接在 pipeline 中段硬写条件。

### 2. 消息整理和模型输入整理已经分开了

`message_preparation_service.prepare(ctx)` 会先把：

- 当前消息
- reply 内容
- 图片输入
- history 版本
- model 版本

这些东西补齐。

后面 pipeline 再决定：

- 哪一版写入 thread
- 哪一版给 retrieval 用
- 哪一版给模型用

所以如果你在改图片理解、reply 展开、history 投影，不要只盯 `_append_incoming_message()`。

### 3. compaction、retrieval、memory 注入都在 agent 前

也就是说，模型真正看到的上下文不是简单的 thread 最近几轮，而是：

- compaction 后的工作记忆
- retrieval planner 准备的 retained history / summary / 检索条件
- memory broker 取回的 `/self`、sticky notes、长期记忆
- 当前轮消息整理后的 `model_content`

如果你想改上下文构成，重点看：

- `context_compactor`
- `retrieval_planner`
- `memory_broker`
- `context_assembly`
- `message_preparation_service`

### 4. hook 还是主线里的正式扩展点

现在 pipeline 里明确保留了这些 hook 点：

- `ON_EVENT`
- `PRE_AGENT`
- `POST_AGENT`
- `BEFORE_SEND`
- `ON_SENT`

如果一个能力本质上是横切逻辑，优先考虑 hook，而不是继续往主线里插大段 if/else。

---

## Agent 阶段

## `AgentRuntime` / `ModelAgentRuntime`

这层负责把 `RunContext` 变成一次真正的模型调用。

它会做这些事：

- 读 `prompt_ref`
- 解析当前 run 真实可见的 tools
- 调 `ContextAssembler` 生成最终 `system_prompt` / `messages`
- 在模型调用前通过 `PayloadJsonWriter` 写最终 payload json
- 检查模型能力
- 调 agent
- 把 agent response 变成 runtime 认识的结果

### 现在模型调用前的最后一跳

当前 `ModelAgentRuntime.execute(ctx)` 里，最终上下文主线已经收成：

- `PromptLoader.load(...)`
- `ToolBroker.build_tool_runtime(...)`
- `ContextAssembler.assemble(...)`
- `PayloadJsonWriter.write(...)`
- `BaseAgent.run(...)`

所以如果你要改“最后到底喂给模型什么”，优先看：

- `src/acabot/runtime/context_assembly/assembler.py`
- `src/acabot/runtime/context_assembly/payload_json_writer.py`
- `src/acabot/runtime/model/model_agent_runtime.py`

### 当前前台工具面

现在前台 builtin tool 已经固定成：

- `read`
- `write`
- `edit`
- `bash`

它们经过这条链进入模型：

- `register_core_builtin_tools(...)`
- `ToolBroker`
- `visible_tools(...)` / `_visible_tools_for_run(...)`
- `ModelAgentRuntime`

也就是说，现在前台工具不再是旧的：

- `ls`
- `grep`
- `exec`
- `bash_open`
- `bash_write`
- `bash_read`
- `bash_close`

### `ask_backend` 还是一个特殊入口

当前实现里，`ask_backend` 还是一个特殊工具。

它的定位是：

- 前台 Aca 通往后台 maintainer 的桥

但它和 `read / write / edit / bash` 不一样：

- 它不是 `builtin:computer`
- 它依赖 backend session 是否真的 configured
- 它不是所有 profile 都能看见

如果你要改后台桥接，不要把它和普通前台 builtin computer tools 混成一回事。

---

## Outbox 阶段

## `src/acabot/runtime/outbox.py`

Outbox 的职责是：

- 把 `PlannedAction` 真正发出去
- 记录真正送达的消息事实

这里最重要的一条原则还是：

> **只有真正产生消息事实的动作，才写入 `MessageStore`。**

所以：

- 发送文本
- 发送 segments

会写消息事实。

但像状态动作、管理动作，不该伪装成 assistant message。

---

## 收尾阶段

一次 run 跑完后，主线不会在“发完回复”就结束。

后面还有至少三件事：

### 1. 更新 thread

thread 的 working messages、summary、时间戳这些状态要回写。

如果你只盯回复，不看 thread 收尾，很容易把上下文顺序搞乱。

### 2. 收尾 run

run 状态会从 running 变成 completed / failed / waiting_approval 等最终状态。

### 3. 提取长期记忆

长期记忆写回不是在模型调用前做，而是在 run 收尾之后做。

所以如果你想改长期记忆，不要只盯 retrieval，也要看 extraction 的收尾链路。

---

## 现在改主线时，应该先看哪一层

## 如果你要改这些东西

### 协议翻译
看：

- gateway

### 当前消息该走哪个 session / surface / profile
看：

- `SessionRuntime`
- `RuntimeRouter`

### 当前消息该不该回复，还是只记录，还是直接丢掉
看：

- `SessionRuntime.resolve_admission(...)`
- `RuntimeRouter.route()`

### 当前消息要带哪些上下文
看：

- `SessionRuntime.resolve_context(...)`
- `ThreadPipeline`
- `retrieval_planner`
- `memory_broker`
- `message_preparation_service`

### 当前 run 的 computer / world / backend
看：

- `SessionRuntime.resolve_computer(...)`
- `ComputerRuntime`
- `builtin_tools/computer.py`

### 模型看到哪些工具
看：

- `register_core_builtin_tools(...)`
- `ToolBroker`
- `ModelAgentRuntime`

### 回复发送和消息事实记录
看：

- `Outbox`
- gateway

---

## 改主流程时最常见的误区

### 1. 把 `RuntimeApp` 当成业务层

不是。

它负责入口接线和最小分流，不负责承载完整业务语义。

### 2. 还按旧 rule 系统理解路由

现在不是 `binding / inbound / event policy` 主线。

当前主线是：

- `SessionConfig`
- `SessionRuntime`
- `RouteDecision`

### 3. 只改 pipeline，不看上游决策已经变了什么

pipeline 接手时，很多决策已经在 `SessionRuntime` 里算完了。

### 4. 只改工具表面，不看 `ComputerRuntime`

前台看到的是 `read / write / edit / bash`，但真正干活的是：

- `ComputerRuntime`

### 5. 只看模型调用，不看消息整理

图片、reply、history、model message 这些事情，很多都在 agent 前就已经准备好了。

---

## 现在最值得优先看的几份源码

如果你要改 runtime 主线，建议按这个顺序看：

1. `src/acabot/runtime/bootstrap/__init__.py`
2. `src/acabot/runtime/app.py`
3. `src/acabot/runtime/router.py`
4. `src/acabot/runtime/control/session_runtime.py`
5. `src/acabot/runtime/pipeline.py`
6. `src/acabot/runtime/model/model_agent_runtime.py`
7. `src/acabot/runtime/outbox.py`

如果你只需要一句话记住当前主线，那就是：

> **RuntimeApp 接住事件，RuntimeRouter 调 SessionRuntime 算决策，ThreadPipeline 执行整次 run，AgentRuntime 出动作，Outbox 真正发送。**
