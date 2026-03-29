# 外部集成

## API 与外部服务

- NapCat / OneBot v11 是当前最核心的外部消息集成。反向 WebSocket 服务实现在 `src/acabot/gateway/napcat.py`，容器接线在 `runtime-env/compose.yaml`。
- LLM 提供方通过 `src/acabot/runtime/model/model_registry.py` 中的模型注册表抽象接入，代码已经支持 OpenAI-compatible、Anthropic、Gemini 风格的 provider 配置。
- 本地浏览器里的 WebUI 通过 `src/acabot/runtime/control/http_api.py` 暴露的 HTTP 接口访问运行时。
- reference 检索支持两类后端：`src/acabot/runtime/references/local.py` 中的本地 SQLite 实现，以及 `src/acabot/runtime/references/openviking.py` 中的 OpenViking 兼容实现。
- 后台操作流还接了 `src/acabot/runtime/backend/bridge.py` 和 `src/acabot/runtime/backend/pi_adapter.py` 这条 backend bridge 线。

## 数据存储

- 核心运行时持久化依赖 `src/acabot/runtime/storage/sqlite_stores.py` 中的 SQLite stores，对应配置键是 `config.example.yaml` 里的 `runtime.persistence.sqlite_path`。
- 当 `runtime.reference.provider=local` 时，reference 数据也可以写入单独的本地 SQLite 库，解析逻辑位于 `src/acabot/runtime/bootstrap/builders.py`。
- 长期记忆打开后会使用 `src/acabot/runtime/memory/long_term_memory/storage.py` 中的 LanceDB 存储。
- sticky notes 和 soul 使用文件真源，目录在 `src/acabot/runtime/bootstrap/__init__.py` 中按 runtime 配置解析。
- workspace 和附件数据由 `src/acabot/runtime/computer/` 中的 computer runtime 负责管理。

## 认证与身份

- NapCat 网关认证是可选的 Bearer Token 模式。反向 WebSocket 会在 `src/acabot/gateway/napcat.py` 中检查 `Authorization` 头。
- 模型 provider 通过环境变量读取密钥，比如 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`；provider 配置里保存的是 env var 名称，不是明文密钥，逻辑见 `src/acabot/runtime/model/model_registry.py`。
- 管理员能力主要由 actor ID 控制，例如 `config.example.yaml` 中的 `plugins.ops_control.allowed_actor_ids`，以及 bootstrap 时解析的 backend admin actor IDs。
- session 和 actor 的身份会被标准化为显式字符串命名空间，例如 `qq:user:<id>`、`qq:group:<id>`，见 `src/acabot/runtime/router.py` 和 `src/acabot/runtime/control/session_runtime.py`。

## 监控与可观测性

- 运行时日志会进入 `src/acabot/runtime/control/log_buffer.py` 的内存缓冲区，并通过 `src/acabot/runtime/control/control_plane.py` 暴露给 WebUI。
- gateway 状态、active runs、plugins、skills、subagents 等运行信息都通过 `src/acabot/runtime/control/control_plane.py` 的 snapshot 接口暴露。
- `/status`、`/skills`、`/reload_plugin` 这类本地 ops 命令由 `src/acabot/runtime/plugins/ops_control.py` 提供。
- 仓库里没有看到外部 metrics、tracing 或 SaaS 监控接入。

## CI/CD 与部署

- 容器化部署路径由 `Dockerfile` 和 `runtime-env/compose.yaml` 定义。
- compose 栈中至少包含 `acabot` 和 `napcat` 两个服务，见 `runtime-env/compose.yaml`。
- 前端通过 `webui/vite.config.ts` 构建后直接进入后端服务的静态目录。
- 仓库当前没有看到 `.github/workflows/` 或其他显式 CI 配置文件。

## 环境配置

- `.env.example` 描述了环境变量入口，`src/acabot/main.py` 会在启动时尝试加载 `.env`。
- 运行时配置既可以走本地 `config.yaml`，也可以走容器环境里的 `runtime-env/config.yaml`。
- profiles、prompts、bindings、inbound rules、event policies、model providers/presets/bindings 等文件系统真源，都通过 `runtime-env/config.example.yaml` 里的 `runtime.filesystem` 配置出来。
- WebUI 的 CORS 白名单在 `config.example.yaml` 和 `runtime-env/config.example.yaml` 中定义。
- workspace 根目录以及附件相关限制通过 `src/acabot/runtime/bootstrap/builders.py` 中的 computer runtime 配置控制。

## Webhook 与回调

- 当前主要的回调形态是 NapCat 主动连入 AcaBot 的反向 WebSocket，而不是 AcaBot 对第三方发 webhook。
- 本地 HTTP API 在 `src/acabot/runtime/control/http_api.py` 下提供 `/api/*` 路由，但仓库里没有看到面向第三方服务的 webhook receiver 或签名回调逻辑。
- plugin reload 和 control 操作都属于本地 runtime 控制面，不是远端回调型集成。
