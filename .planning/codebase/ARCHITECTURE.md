# 架构

## 模式概览

- 这个仓库的整体结构是一套分层的 runtime engine，启动时显式装配，主要领域模块集中在 `src/acabot/runtime/`。
- 每条入站事件都会先走配置驱动的路由决策，再进入正式执行主线。这个决策接缝主要由 `src/acabot/runtime/router.py` 和 `src/acabot/runtime/control/session_runtime.py` 负责。
- 运行时更偏向“组合 + 依赖注入”，而不是把所有行为塞进一个超级 service。总装配入口是 `src/acabot/runtime/bootstrap/__init__.py`。
- control plane 和 WebUI 在架构上是 runtime 之上的运维界面，不是另一套独立业务系统，对应目录是 `src/acabot/runtime/control/` 和 `webui/`。

## 分层

- 网关与事件标准化：
  `src/acabot/gateway/napcat.py`、`src/acabot/gateway/onebot_message.py`、`src/acabot/types/event.py`
- 运行时编排层：
  `src/acabot/main.py`、`src/acabot/runtime/app.py`、`src/acabot/runtime/bootstrap/__init__.py`
- Session 路由与决策契约层：
  `src/acabot/runtime/router.py`、`src/acabot/runtime/control/session_runtime.py`、`src/acabot/runtime/contracts/`
- 执行主线层：
  `src/acabot/runtime/pipeline.py`、`src/acabot/runtime/model/model_agent_runtime.py`、`src/acabot/runtime/outbox.py`
- 工具、插件与委派层：
  `src/acabot/runtime/tool_broker/`、`src/acabot/runtime/plugin_manager.py`、`src/acabot/runtime/builtin_tools/`、`src/acabot/runtime/subagents/`
- 记忆、存储与 reference 层：
  `src/acabot/runtime/memory/`、`src/acabot/runtime/storage/`、`src/acabot/runtime/references/`
- 运维与界面层：
  `src/acabot/runtime/control/`、`src/acabot/webui/`、`webui/`

## 数据流

- 消息入口从 `src/acabot/gateway/napcat.py` 开始，NapCat 通过反向 WebSocket 把 OneBot 事件送进来。
- 网关会把原始协议 payload 翻译成 `src/acabot/types/event.py` 中的 `StandardEvent`。
- `src/acabot/runtime/app.py` 里的 `RuntimeApp.handle_event()` 负责路由、线程 / run 打开、profile 与 model 解析，并构造 `RunContext`。
- `src/acabot/runtime/pipeline.py` 里的 `ThreadPipeline.execute()` 会依次完成消息准备、上下文压缩、retrieval planning、记忆注入、agent 执行、动作分发和 run 收尾。
- 外发动作最终通过 `src/acabot/runtime/outbox.py` 回到 gateway 动作面，同时状态会落到 `src/acabot/runtime/storage/`。
- 并行地，本地 HTTP API 会通过 `src/acabot/runtime/control/http_api.py` 把 `RuntimeControlPlane` 暴露给 WebUI，用于读取和修改运行时状态。

## 关键抽象

- `src/acabot/runtime/bootstrap/__init__.py` 里的 `RuntimeComponents` 和 `build_runtime_components()` 是总装配根。
- `src/acabot/runtime/app.py` 里的 `RuntimeApp` 管理事件接入、恢复流程和顶层生命周期。
- `src/acabot/runtime/contracts/` 中的 `RouteDecision`、`RunContext`、`ThreadState` 等契约，是整条 runtime 主线的稳定数据模型。
- `src/acabot/runtime/pipeline.py` 中的 `ThreadPipeline` 是单次 run 的核心执行器。
- `src/acabot/runtime/tool_broker/broker.py` 里的 `ToolBroker` 统一管理工具注册、可见性、策略与执行。
- `src/acabot/runtime/memory/memory_broker.py` 里的 `MemoryBroker` 和 `src/acabot/runtime/memory/retrieval_planner.py` 里的 `RetrievalPlanner` 共同负责记忆注入。
- `src/acabot/runtime/subagents/execution.py` 里的 `LocalSubagentExecutionService` 通过 child run 复用同一条 pipeline。
- `src/acabot/runtime/control/control_plane.py` 里的 `RuntimeControlPlane` 是状态、模型、session、skills、subagents、notes、references、workspace 的统一运维入口。

## 入口点

- CLI / 服务启动入口：`src/acabot/main.py`
- 运行时装配入口：`src/acabot/runtime/bootstrap/__init__.py`
- 网关入口：`src/acabot/gateway/napcat.py`
- 本地 HTTP API 与静态 UI 托管入口：`src/acabot/runtime/control/http_api.py`
- 前端启动入口：`webui/src/main.ts`
- 前端路由入口：`webui/src/router.ts`

## 错误处理

- 启动与停止阶段都显式做清理，例如 plugins、references、long-term-memory worker 的回收，见 `src/acabot/main.py` 和 `src/acabot/runtime/app.py`。
- pipeline 顶层会捕获执行异常并把 run 标记为 failed，而不是直接把异常漏到外层，见 `src/acabot/runtime/pipeline.py`。
- 可选依赖会做显式保护，例如缺少 `websockets` 或 `lancedb` 时会给出明确运行时错误，见 `src/acabot/gateway/napcat.py` 和 `src/acabot/runtime/bootstrap/builders.py`。
- HTTP API 会把 `KeyError`、`ValueError` 和兜底异常统一映射成 JSON 错误响应，逻辑在 `src/acabot/runtime/control/http_api.py`。

## 横切关注点

- 模型解析集中在 `src/acabot/runtime/model/` 的 model registry 与 target catalog。
- runtime plugin 和 builtin tools 都属于 agent 能力面，但它们通过不同接缝进入系统：分别是 `src/acabot/runtime/plugin_manager.py` 和 `src/acabot/runtime/builtin_tools/`。
- 前端和后端在部署上耦合得比较紧：`webui/` 里的 Vite 工程会构建到 `src/acabot/webui/`，再由后端 HTTP server 提供静态页面。
- session、skill、subagent、model binding 等能力都带有文件系统真源，因此仓库目录结构本身就是运行时契约的一部分。
