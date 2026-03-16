# AcaBot 系统地图

这一篇不讲细节，只讲项目里各块东西分别是干什么的，依赖方向怎么走，哪里是经常被误改的边界。

## 顶层模块

`src/acabot` 下面现在主要有这些块:

- `main.py`
  启动入口。读配置，创建 gateway、agent 和 runtime app。
- `config.py`
  配置容器，负责读写 YAML 和相对路径解析。
- `types/`
  跨层共享的数据契约，重点是 `StandardEvent` 和 `Action`。
- `gateway/`
  平台协议适配层。当前正式实现是 NapCat / OneBot v11。
- `agent/`
  面向模型调用的抽象层。定义 `BaseAgent`、tool 契约、response 契约。
- `runtime/`
  现在最重要的目录。主流程、路由、记忆、工具、插件、控制面、模型解析都在这里，而且已经按 `contracts / control / inbound / memory / model / references / skills / storage / subagents` 拆成子目录。
- `webui/`
  本地 WebUI 静态资源。

## 真实的依赖方向

按职责看，建议脑中保持这条依赖方向:

`types -> gateway / agent -> runtime -> webui`

具体一点:

- `types` 只放通用对象，不该依赖 runtime 细节
- `gateway` 依赖 `types`
- `agent` 依赖自己的契约和少量通用对象
- `runtime` 依赖 `gateway / agent / types / config`
- `webui` 不直接碰 Python 内部状态，只通过 HTTP API

## 启动层

关键文件:

- `src/acabot/main.py`
- `src/acabot/runtime/bootstrap/`
- `src/acabot/runtime/app.py`

分工很清楚:

- `main.py` 负责“从配置出发把东西创建出来”
- `bootstrap/` 负责“把默认组件接成一套能跑的 runtime”
- `app.py` 负责“把 gateway 上来的 event 送进 runtime 主线”

如果你想给系统加一个新基础设施，第一反应应该是看 `bootstrap/`，不是先去 patch `main.py`。

## runtime 里最重要的几类文件

### 主线骨架

- `runtime/app.py`
- `runtime/router.py`
- `runtime/pipeline.py`
- `runtime/outbox.py`

### 状态与持久化

- `runtime/contracts/`
- `runtime/storage/stores.py`
- `runtime/storage/threads.py`
- `runtime/storage/runs.py`
- `runtime/storage/sqlite_stores.py`

### 记忆和上下文

- `runtime/memory/memory_broker.py`
- `runtime/memory/structured_memory.py`
- `runtime/memory/context_compactor.py`
- `runtime/memory/retrieval_planner.py`

### 工具、插件、子代理

- `runtime/tool_broker/`
- `runtime/plugin_manager.py`
- `runtime/skills/catalog.py`
- `runtime/subagents/contracts.py`
- `runtime/subagents/broker.py`
- `runtime/subagents/execution.py`
- `runtime/plugins/`

### 配置与控制面

- `runtime/control/control_plane.py`
- `runtime/control/snapshots.py`
- `runtime/control/ui_catalog.py`
- `runtime/control/model_ops.py`
- `runtime/control/workspace_ops.py`
- `runtime/control/reference_ops.py`
- `runtime/control/config_control_plane.py`
- `runtime/control/http_api.py`
- `runtime/control/profile_loader.py`
- `runtime/model/model_registry.py`
- `runtime/references/`

## 各层职责边界

### `types`

这里只定义对象，不做业务决策。

如果你发现某个文件开始出现“判断应该用哪个 agent”“判断某条消息要不要写 memory”之类逻辑，那就已经越界了。

### `gateway`

只处理协议层:

- 收平台事件
- 翻译成 `StandardEvent`
- 把 `Action` 发回平台
- 提供原生 `call_api`

不该处理:

- routing
- memory
- tools
- profile 选择

### `runtime`

这里才是业务主线。

只要是“消息进来之后系统怎么决定、怎么执行、怎么记录、怎么回复”，基本都属于 runtime。

### `webui`

前端展示和操作壳。真正的业务入口还是:

- `RuntimeHttpApiServer`
- `RuntimeControlPlane`
- `RuntimeConfigControlPlane`

## 现在系统里最关键的状态对象

### 事件

`StandardEvent`

外部世界进来的统一事件。这个对象如果改字段，会影响:

- gateway 翻译
- router
- event policy
- pipeline 的用户内容投影

### 动作

`Action`

系统对外发消息或执行平台动作的统一对象。这个对象如果改类型或 payload 约定，会影响:

- agent/tool 产出的动作
- outbox
- gateway.send

### 线程

`ThreadState`

当前对话线程的 working memory 容器。不是长期记忆仓库。

### run

`RunRecord` 和 `RunContext`

`RunRecord` 是正式生命周期记录。

`RunContext` 是“一次执行过程中需要带着跑的所有现场”。

### 持久化事实

- `ChannelEventRecord`: 外部事件事实
- `MessageRecord`: 真正送达的消息事实
- `MemoryItem`: 长期记忆项

## 什么时候该看 `agent-first/`

只有两种情况:

1. 你发现代码里还没实现某块，而 `agent-first/` 里正好有近期 TODO
2. 你要判断作者最近想把架构往哪推

别把它当实现说明书。

## 典型改动应该先找哪里

### WebUI 控制面板

先看:

- `src/acabot/webui/app.js`
- `src/acabot/runtime/control/http_api.py`
- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/snapshots.py`
- `src/acabot/runtime/control/ui_catalog.py`
- `src/acabot/runtime/control/model_ops.py`
- `src/acabot/runtime/control/workspace_ops.py`
- `src/acabot/runtime/control/reference_ops.py`
- `src/acabot/runtime/control/config_control_plane.py`

### 图片转述 / VLM

先看:

- `src/acabot/types/event.py`
- `src/acabot/gateway/napcat.py`
- `src/acabot/runtime/inbound/message_resolution.py`
- `src/acabot/runtime/inbound/message_projection.py`
- `src/acabot/runtime/inbound/message_preparation.py`
- `src/acabot/runtime/inbound/image_context.py`
- `src/acabot/runtime/pipeline.py`
- `src/acabot/runtime/computer/`
- `src/acabot/runtime/model/model_agent_runtime.py`
- `src/acabot/runtime/memory/memory_broker.py`

### 长期记忆

先看:

- `src/acabot/runtime/memory/memory_broker.py`
- `src/acabot/runtime/memory/structured_memory.py`
- `src/acabot/runtime/storage/stores.py`
- `src/acabot/runtime/control/event_policy.py`
- `src/acabot/runtime/pipeline.py`

## 一句话版本

这项目的核心不是“某个单文件很大”，而是“很多能力跨层接起来”。所以先判断层，再判断入口，再动代码。
