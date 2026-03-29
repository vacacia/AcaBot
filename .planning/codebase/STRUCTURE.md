# 代码结构

## 目录布局

```text
src/acabot/
  agent/                 核心 agent 抽象与 LiteLLM 相关运行时代码
  gateway/               NapCat / OneBot 入站与消息翻译
  runtime/               主执行引擎、control plane、memory、tools、subagents
  types/                 共享事件 / 动作契约
  webui/                 构建后的前端静态产物

webui/
  src/components/        可复用 Vue 组件
  src/views/             配置、会话、日志、系统等页面级视图
  src/lib/               前端 API 封装
  src/styles/            共享设计系统样式

tests/
  runtime/               runtime 各子系统测试
  runtime/backend/       backend 相关测试
  runtime/control/       control plane 相关测试
  fixtures/skills/       skill catalog / loader 用的 fixture 包
  types/                 低层类型测试

plugins/                 旧式 plugin 风格扩展与实验代码
runtime-env/             docker-compose 运行环境与示例配置
docs/                    架构说明、专题设计、计划与已知问题
```

## 目录用途

- `src/acabot/` 是正式后端包，系统绝大部分正式能力都在 `src/acabot/runtime/` 下面。
- `src/acabot/runtime/backend/` 负责 backend bridge 和 backstage session 相关逻辑。
- `src/acabot/runtime/builtin_tools/` 放第一方工具接线。
- `src/acabot/runtime/control/` 放本地运维 API 和 WebUI 后端接口。
- `src/acabot/runtime/memory/`、`src/acabot/runtime/storage/`、`src/acabot/runtime/model/` 分别承担记忆、持久化和模型接线。
- `webui/` 是可编辑的前端源码目录，做 UI 开发时应优先改这里。
- `src/acabot/webui/` 是前端构建产物，也是后端默认直接托管的静态目录。
- `plugins/` 里是旧式插件代码，例如 `plugins/notepad/`。
- `runtime-env/` 是 docker 化运行外壳，包住 AcaBot 和 NapCat。
- `docs/` 是活跃使用中的设计文档区，不只是归档说明。

## 关键文件位置

- 主启动入口：`src/acabot/main.py`
- 运行时总装配：`src/acabot/runtime/bootstrap/__init__.py`
- 事件路由：`src/acabot/runtime/router.py`
- session 决策运行时：`src/acabot/runtime/control/session_runtime.py`
- 执行主线：`src/acabot/runtime/pipeline.py`
- control plane API：`src/acabot/runtime/control/http_api.py`
- 模型注册表：`src/acabot/runtime/model/model_registry.py`
- 工具总入口：`src/acabot/runtime/tool_broker/broker.py`
- subagent 执行：`src/acabot/runtime/subagents/execution.py`
- 前端路由：`webui/src/router.ts`
- 前端 API 客户端：`webui/src/lib/api.ts`
- 前端设计系统样式：`webui/src/styles/design-system.css`
- 运行时示例配置：`config.example.yaml` 与 `runtime-env/config.example.yaml`

## 命名约定

- Python 模块统一使用 snake_case，例如 `session_runtime.py`、`model_registry.py`、`sqlite_stores.py`。
- runtime 内部按领域拆目录，而不是纯按技术层拆，比如 `memory/`、`model/`、`control/`、`subagents/`。
- Vue 页面文件使用 `*View.vue` 命名，例如 `webui/src/views/HomeView.vue`、`webui/src/views/SessionsView.vue`。
- 可复用 Vue 组件使用 PascalCase 文件名，例如 `webui/src/components/AppSidebar.vue`。
- 测试文件统一走 `test_*.py` 命名，并按子系统分布在 `tests/runtime/`、`tests/runtime/backend/`、`tests/runtime/control/` 等目录。

## 新代码应该加到哪里

- 新的 runtime 功能一般应该进入对应领域目录，而不是继续在包根部堆更多顶层模块。
- 新的运维 API 通常应该先接到 `src/acabot/runtime/control/control_plane.py`，再由 `src/acabot/runtime/control/http_api.py` 暴露出去。
- 新的 agent 能力如果是工具 schema，通常落在 `src/acabot/runtime/builtin_tools/`；如果是生命周期 hook，更可能落在 `src/acabot/runtime/plugins/`。
- 新的前端页面应该优先放进 `webui/src/views/`，公用 UI 抽到 `webui/src/components/`。
- 新的后端 / 前端联动测试，通常应该放在 `tests/runtime/test_webui_api.py` 或对应的子系统测试文件中。

## 特殊目录

- `src/acabot/webui/` 是由 `webui/vite.config.ts` 构建出来的产物目录，除非是有意补产物，否则不应该把它当源码改。
- `tests/fixtures/skills/` 用来模拟 skill package 的文件系统结构，是 catalog / loader 测试的重要 fixture。
- `runtime-env/napcat/` 是运行时状态目录，递归扫描时可能遇到权限受限文件。
- `.acabot-runtime/`、`runtime-data/`、`runtime-config/`、`.worktrees/` 这类目录更偏环境状态，不属于核心应用源码。
