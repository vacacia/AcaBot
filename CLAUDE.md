<!-- GSD:project-start source:PROJECT.md -->
## Project

**AcaBot**

AcaBot 是一个面向 QQ / NapCat 场景的本地优先 agent runtime 和后台控制台。它的目标不是只把模型接起来跑，而是让操作者能够通过统一的 WebUI 看懂、配置和维护 bot 的真实行为，而不是继续依赖分散配置文件、硬编码路径和源码猜系统怎么运行。

当前这轮工作主要先服务你自己把系统收稳、收可用，但产品方向不是“只给作者自己调试的私人工具”。在核心控制面稳定后，它还需要能让其他操作者通过 quickstart 上手。

**Core Value:** 操作者必须能通过一个真实可用的 WebUI 稳定地理解并控制 AcaBot 的行为。

### Constraints

- **Brownfield**: 必须沿着现有 runtime 主线、session contract 和 control plane 演进，而不是另起炉灶重写一套系统 — 因为当前代码和文档已经形成正式边界
- **Product Scope**: 现有 WebUI 页面信息架构和页面定位优先保持稳定 — 因为这些页面内容已经是你明确打磨过的需求，而不是随手占位
- **Source of Truth**: WebUI 的每一个正式管理项都必须接到真实配置 / 目录 / registry / runtime 契约，而不是停留在占位 UI 状态 — 因为“页面存在但不生效”会直接毁掉控制面的可信度
- **Operability**: 路径、数据目录、filesystem catalog、运行时存储位置必须可统一解析和可说明 — 因为当前连操作者自己都不总能判断运行时数据实际落点
- **Audience**: 当前优先级是操作者可用性，后续要支持其他人上手 — 因为 Quickstart 和可维护性是明确后续目标
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## 语言
- 后端代码主要是 Python 3.11，位于 `src/acabot/**/*.py`。
- 前端代码是 TypeScript 和 Vue 单文件组件，位于 `webui/src/**/*.ts` 与 `webui/src/**/*.vue`。
- 运行时与部署配置主要使用 YAML，见 `config.example.yaml`、`runtime-env/config.example.yaml` 和本地 `config.yaml`。
- 文档与规划以 Markdown 为主，集中在 `docs/`、`webui-pages-draft.md` 和 `.planning/`。
## 运行时
- 后端运行入口由 `pyproject.toml` 中的 `acabot = "acabot.main:main"` 和 `src/acabot/main.py` 定义。
- 主要消息入口是 `src/acabot/gateway/napcat.py` 里的反向 WebSocket 服务。
- 运行时装配中心在 `src/acabot/runtime/bootstrap/__init__.py` 与 `src/acabot/runtime/app.py`。
- 本地 control plane / WebUI API 没有使用 FastAPI 或 Flask，而是使用 `src/acabot/runtime/control/http_api.py` 中的 `ThreadingHTTPServer`。
- 前端源码位于 `webui/`，生产构建产物由 `webui/vite.config.ts` 输出到 `src/acabot/webui/`。
## 框架
- 后端传输层使用 `websockets`，用于 NapCat / OneBot 反向 WebSocket 网关，声明在 `pyproject.toml`，实际使用见 `src/acabot/gateway/napcat.py`。
- 模型运行时通过 `litellm` 接入多家模型提供方，相关代码集中在 `src/acabot/runtime/model/`。
- 持久化主要通过 `src/acabot/runtime/storage/sqlite_stores.py` 中的 `aiosqlite` 路径完成。
- 配置加载依赖 `pyyaml` 和 `python-dotenv`，入口见 `src/acabot/config.py` 与 `src/acabot/main.py`。
- 长期记忆是可选能力，依赖 `lancedb` 与 `pyarrow`，实现位于 `src/acabot/runtime/memory/long_term_memory/storage.py`。
- 前端框架是 Vue 3 + Vue Router，入口见 `webui/package.json`、`webui/src/App.vue` 和 `webui/src/router.ts`。
- 前端工具链是 Vite + TypeScript，配置见 `webui/package.json`、`webui/tsconfig.json` 和 `webui/vite.config.ts`。
- 测试框架是 `pytest` + `pytest-asyncio`，配置见 `pyproject.toml` 和 `tests/`。
## 关键依赖
- `websockets>=12.0`：网关传输，主要用于 `src/acabot/gateway/napcat.py`。
- `litellm>=1.40.0`：模型提供方访问与抽象层，主要用于 `src/acabot/runtime/model/`。
- `aiosqlite>=0.20.0`：SQLite 持久化，主要用于 `src/acabot/runtime/storage/sqlite_stores.py`。
- `pyyaml>=6.0`：配置读写，主要用于 `src/acabot/config.py`。
- `python-dotenv>=1.0.0`：`.env` 加载，主要用于 `src/acabot/main.py`。
- `lancedb>=0.25.0` 和 `pyarrow>=18.0.0`：长期记忆存储，可选，位于 `src/acabot/runtime/memory/long_term_memory/`。
- `vue`、`vue-router`、`vite`、`@vitejs/plugin-vue`、`typescript`：`webui/` 前端栈的核心依赖。
## 配置
- 基础运行时配置通过 `src/acabot/config.py` 中的 `Config.from_file()` 加载。
- 示例配置文件主要是 `config.example.yaml` 和 `runtime-env/config.example.yaml`。
- 活动配置路径可以通过环境变量 `ACABOT_CONFIG` 覆盖，相关逻辑见 `src/acabot/config.py` 和 `runtime-env/compose.yaml`。
- 当 `runtime.filesystem.enabled=true` 时，profiles、prompts、bindings 等文件系统真源通常位于 `runtime-config/` 或 `runtime-env/runtime-config/`。
- 模型 provider、preset、binding 的目录解析逻辑位于 `src/acabot/runtime/bootstrap/builders.py`。
- WebUI 的静态构建输出由 `webui/vite.config.ts` 决定，并由后端从 `src/acabot/webui/` 对外提供。
## 平台要求
- Python 3.11 是正式要求，见 `pyproject.toml` 和 `Dockerfile`。
- 如果要开发或重建前端，需要本地具备 Node.js 与 npm，因为前端使用 Vite，并且构建结果会写入仓库中的静态目录。
- Docker 不是必须，但仓库已经提供 `Dockerfile` 和 `runtime-env/compose.yaml` 作为标准运行方式。
- QQ / OneBot 场景下，NapCat 是正式运行依赖，compose 中的 `napcat` 服务已经体现了这一点。
- 运行时需要可写本地存储，用于 SQLite、workspace、sticky notes 和可选的长期记忆目录。
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## 命名模式
- Python 模块使用 snake_case，并且通常直接按职责命名，例如 `control_plane.py`、`memory_broker.py`、`session_runtime.py`。
- 类和 dataclass 使用 PascalCase，例如 `RuntimeApp`、`ThreadPipeline`、`RuntimeControlPlane`、`RouteDecision`。
- 运行时内部很多标识都使用显式命名空间字符串，例如 `qq:user:<id>`、`qq:group:<id>`、`binding:agent:aca`、`subagent:<name>`。
- Vue 页面使用 `*View.vue`，公用组件使用 PascalCase 文件名，例如 `LogStreamPanel.vue`、`StatusCard.vue`。
## 代码风格
- Python 文件几乎都会先写 `from __future__ import annotations`。
- 生产代码广泛使用类型标注，尤其是 `src/acabot/runtime/contracts/`、`src/acabot/runtime/model/`、`src/acabot/runtime/control/`。
- 模块风格偏向“小 helper + 显式 builder”，而不是一个类里藏很多隐式初始化逻辑。
- Docstring 很常见，而且大量使用中文来解释模块边界和设计意图。
- 代码整体更偏显式组合、纯数据对象和边界清晰的 service，而不是依赖框架魔法。
## 导入组织
- 导入顺序通常是标准库、第三方库、项目内模块。
- 需要隔离循环依赖或仅用于类型提示时，会使用 `TYPE_CHECKING`，例如 `src/acabot/runtime/bootstrap/builders.py`。
- 包内部多用相对导入，顶层入口则常用绝对包导入，例如 `from acabot.config import Config`。
- 前端模块使用标准 ES import，路径通常保持比较浅，例如 `./views/HomeView.vue`、`./lib/api`。
## 错误处理
- 可选依赖通常会被显式保护，并给出有针对性的 `RuntimeError`，例如 `src/acabot/gateway/napcat.py` 和 `src/acabot/runtime/bootstrap/builders.py`。
- pipeline 和 app 生命周期代码会在失败时主动做清理，而不是默认让进程退出，见 `src/acabot/runtime/app.py` 和 `src/acabot/runtime/pipeline.py`。
- HTTP API 会把预期错误统一包装成 JSON 错误返回，逻辑在 `src/acabot/runtime/control/http_api.py`。
- 配置读取大量使用 `dict.get(...)` 和默认值，而不是假定字段一定存在。
## 日志
- 后端模块统一使用 `logging.getLogger("acabot....")` 风格的命名 logger，例如 `acabot.runtime.app`、`acabot.gateway`。
- 日志里经常带上 `event_id`、`run_id`、`thread_id`、`agent_id` 这类运行时标识，方便排查。
- 系统会通过 `src/acabot/runtime/control/log_buffer.py` 维护一段内存日志窗口，供 WebUI 查看。
- routing、model resolution、compaction、delivery 等关键链路都有较多 debug 级日志。
## 注释
- 注释主要用于解释架构意图、迁移痕迹和一些容易踩坑的行为，而不是逐行翻译代码。
- 仓库里会保留“踩坑记录”类注释，例如 `src/acabot/runtime/control/http_api.py` 对静态目录路径问题的说明。
- 对并发、生命周期这类不直观逻辑，允许使用较长的解释性注释，例如 `src/acabot/runtime/pipeline.py` 中关于 compaction 的说明块。
## 函数设计
- 公共函数和方法通常会写带 Args/Returns 的 docstring。
- builder 风格命名非常常见，例如 `build_runtime_components`、`build_memory_broker`、`build_long_term_memory_source`。
- 决策型函数也很多，例如 `resolve_surface`、`resolve_routing`、`resolve_admission`、`resolve_context`。
- IO 重、跨服务边界的逻辑通常是 `async`；纯解析或配置 helper 通常保持同步。
## 模块设计
- runtime 内部主要按领域拆分目录，而不是只按 MVC / service / util 这种通用层次拆。
- `src/acabot/runtime/__init__.py` 承担了一个大的 facade export 角色，把 runtime 对外稳定面集中导出。
- skills、subagents、profiles、sessions、model bindings 等能力都走文件系统 catalog / loader，这是一条很明确的设计主线。
- 测试目录和正式代码的领域边界比较一致，尤其是 `tests/runtime/` 这层。
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## 模式概览
- 这个仓库的整体结构是一套分层的 runtime engine，启动时显式装配，主要领域模块集中在 `src/acabot/runtime/`。
- 每条入站事件都会先走配置驱动的路由决策，再进入正式执行主线。这个决策接缝主要由 `src/acabot/runtime/router.py` 和 `src/acabot/runtime/control/session_runtime.py` 负责。
- 运行时更偏向“组合 + 依赖注入”，而不是把所有行为塞进一个超级 service。总装配入口是 `src/acabot/runtime/bootstrap/__init__.py`。
- control plane 和 WebUI 在架构上是 runtime 之上的运维界面，不是另一套独立业务系统，对应目录是 `src/acabot/runtime/control/` 和 `webui/`。
## 分层
- 网关与事件标准化：
- 运行时编排层：
- Session 路由与决策契约层：
- 执行主线层：
- 工具、插件与委派层：
- 记忆、存储与 reference 层：
- 运维与界面层：
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
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
