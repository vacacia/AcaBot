# 技术栈

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
