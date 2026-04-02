# Runtime 主线

本文档说明一条外部消息从进入系统到回复送达的完整执行路径。

```
Gateway → RuntimeApp → RuntimeRouter → SessionRuntime → ThreadPipeline → ModelAgentRuntime → Outbox
```

## 关键入口文件

| 文件 | 职责 |
|------|------|
| `src/acabot/main.py` | 启动接线：创建 gateway/agent，调 `build_runtime_components()` |
| `src/acabot/runtime/bootstrap/__init__.py` | 装配中心：接好全部 runtime 组件 |
| `src/acabot/runtime/app.py` | 接住 gateway 事件、做入口分流、组装 RunContext、交给 pipeline |
| `src/acabot/runtime/router.py` | 调 SessionRuntime 并把结果收口成 RouteDecision |
| `src/acabot/runtime/control/session_runtime.py` | 按 SessionConfig 计算 surface/routing/admission/context/persistence/extraction/computer 决策 |
| `src/acabot/runtime/pipeline.py` | 执行一次 run 的完整主线 |

## 总流程

1. `main.py` 读配置，创建 gateway 和 agent
2. `build_runtime_components()` 组装 runtime
3. `RuntimeApp.start()` 启动 gateway，确保 plugin manager 已启动
4. Gateway 收到平台事件，翻译成 `StandardEvent`
5. `RuntimeApp.handle_event()` 接住事件
6. `RuntimeRouter.route()` 调 `SessionRuntime` 算出 `RouteDecision`
7. `RuntimeApp` 根据决策加载 agent、解析模型请求、创建 thread 和 run
8. `RuntimeApp` 构造 `RunContext`
9. `ThreadPipeline.execute()` 跑完整执行流程
10. `ModelAgentRuntime` 调模型，生成动作
11. `Outbox` 发送动作并记录消息事实
12. Pipeline 收尾：保存 thread，结束 run

## 启动阶段

### main.py

只做启动接线（创建 gateway/agent、调 bootstrap、启动 app），不是业务主线。

### bootstrap

装配中心，接好：profile/prompt loader、SessionRuntime、RuntimeRouter、thread/run manager、stores、memory broker/retrieval planner/context compactor、ComputerRuntime、ToolBroker、builtin tools、runtime plugins、ThreadPipeline、RuntimeApp、control plane/http api。

两个关键事实：
- **core tool 不是 plugin**：bootstrap 直接调 `register_core_builtin_tools(...)` 把 `builtin:computer`、`builtin:skills`、`builtin:subagents` 注册进 ToolBroker。前台基础工具固定为 read/write/edit/bash。
- **runtime plugin 只代表外部扩展**：plugin manager 不再承载基础工具。

### RuntimeApp

runtime 总入口。接住 gateway 事件、打日志、检查后台硬入口、调 router 计算 RouteDecision、处理 silent_drop、创建/获取 ThreadState、加载 agent、解析模型请求、创建 RunRecord、保存 channel event、构造 RunContext、调 pipeline。职责是接线和分流，不是承载完整业务。

管理员后台入口也在这里做最小分流，但只有 bootstrap 真正构造出 configured backend session service 时后台入口才打开。

## 路由阶段

### RuntimeRouter

很薄的一层：把 `StandardEvent` 交给 SessionRuntime，把算出来的决策收口成 `RouteDecision`。真正的消息决策中心是 SessionRuntime。

### SessionRuntime

按顺序执行：

1. `build_facts(event)` — 标准化成 EventFacts
2. `load_session(facts)` — 定位并读取 SessionConfig
3. `resolve_surface(...)` — 算命中的 surface
4. `resolve_routing(...)` — 算要走哪个 agent
5. `resolve_admission(...)` — 算 respond / record_only / silent_drop
6. `resolve_context(...)` — 算 retrieval tags、sticky note targets、context labels
7. `resolve_persistence(...)` — 算 event 是否持久化
8. `resolve_extraction(...)` — 算长期记忆 tags
9. `resolve_computer(...)` — 算 computer/backend 决策

### run_mode

三种关键模式：
- **respond**：正常进入完整主线
- **record_only**：记录但不调模型、不发送回复
- **silent_drop**：尽早退出，不创建 run、不进 pipeline、不改 thread working memory

## RunContext 组装

RuntimeApp 拿到 RouteDecision 后继续：创建/获取 ThreadState → 加载 ResolvedAgent → 解析主模型和 summary 模型请求 → 创建 RunRecord → 保存 ChannelEventRecord → 组装 RunContext。

RunContext 携带 SessionRuntime 算出的全部决策（event_facts、surface_resolution、routing/admission/context/persistence/extraction/computer_policy_decision），pipeline 接手时决策已经齐了。

## Pipeline 阶段

`ThreadPipeline.execute()` 的执行顺序：

| 步骤 | 内容 |
|------|------|
| 1 | mark_running |
| 2 | ON_EVENT hooks |
| 3 | `computer_runtime.prepare_run_context(ctx)` — 准备 world、workspace、附件 staging |
| 4 | `message_preparation_service.prepare(ctx)` — 整理消息的 history/model/memory 三版 |
| 5 | 用户输入写进 thread working memory |
| 6 | record_only 提前收尾 |
| 7 | context compaction |
| 8 | retrieval plan 准备 |
| 9 | MemoryBroker 取 /self、sticky notes、长期记忆 |
| 10 | PRE_AGENT hooks |
| 11 | `agent_runtime.execute(ctx)` |
| 12 | POST_AGENT hooks |
| 13 | Outbox 发送动作 |
| 14 | 更新 thread |
| 15 | 收尾 run |

关键细节：
- **computer 准备在最前面**：world、workspace、附件 staging、可见工具状态都在 pipeline 早期由 ComputerRuntime 准备。改 `/workspace`、`/skills`、`/self`、附件或 backend 时先看 ComputerRuntime。
- **消息整理和模型输入分开**：`message_preparation_service` 产出 history 版、model 版和 memory_candidates 版，pipeline 再决定各版本去向。改图片理解、reply 展开、history 投影时看 preparation service。
- **compaction/retrieval/memory 都在 agent 前**：模型看到的上下文是 compaction 后的工作记忆 + retrieval planner 的 retained history/summary + memory broker 取回的记忆 + 当前轮 model_content。
- **hook 是正式扩展点**：ON_EVENT、PRE_AGENT、POST_AGENT、BEFORE_SEND、ON_SENT。横切逻辑优先用 hook。

## Agent 阶段

`ModelAgentRuntime.execute(ctx)` 的最终上下文链路：

```
PromptLoader.load(...)  →  ToolBroker.build_tool_runtime(...)
    →  ContextAssembler.assemble(...)  →  PayloadJsonWriter.write(...)  →  BaseAgent.run(...)
```

前台 builtin tool（read/write/edit/bash）经过 `register_core_builtin_tools(...)` → ToolBroker → `visible_tools(...)` → ModelAgentRuntime 进入模型。

`ask_backend` 是特殊工具（前台到后台 maintainer 的桥），不属于 `builtin:computer`，依赖 backend session 是否 configured，不是所有 agent 都能看见。

## Outbox 阶段

`src/acabot/runtime/outbox.py` 把 `PlannedAction` 真正发出去并记录送达的消息事实。原则：只有真正产生消息事实的动作才写入 MessageStore，状态动作和管理动作不伪装成 assistant message。

## 收尾阶段

run 结束后还有三件事：
1. **更新 thread**：working messages、summary、时间戳回写
2. **收尾 run**：状态从 running 变成 completed / failed / waiting_approval
3. **长期记忆写回**：extraction 在 run 收尾之后做（不是模型调用前）

## 改主线时的入口速查

| 想改什么 | 看哪里 |
|---------|-------|
| 协议翻译 | `gateway/` |
| session / surface / agent 选择 | `SessionRuntime`、`RuntimeRouter` |
| 该不该回复 / 只记录 / 丢弃 | `SessionRuntime.resolve_admission(...)`、`RuntimeRouter.route()` |
| 上下文构成 | `SessionRuntime.resolve_context(...)`、retrieval_planner、memory_broker、message_preparation_service |
| computer / world / backend | `SessionRuntime.resolve_computer(...)`、`ComputerRuntime`、`builtin_tools/computer.py` |
| 模型看到哪些工具 | `register_core_builtin_tools(...)`、`ToolBroker`、`ModelAgentRuntime` |
| 回复发送和消息事实 | `Outbox`、`gateway/` |

## 源码阅读顺序

1. `src/acabot/runtime/bootstrap/__init__.py`
2. `src/acabot/runtime/app.py`
3. `src/acabot/runtime/router.py`
4. `src/acabot/runtime/control/session_runtime.py`
5. `src/acabot/runtime/pipeline.py`
6. `src/acabot/runtime/model/model_agent_runtime.py`
7. `src/acabot/runtime/outbox.py`
