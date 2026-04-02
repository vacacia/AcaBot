# 项目路径结构统一

## Context

AcaBot 当前的配置和数据目录存在严重的平行结构混乱：

- 两套 config.example.yaml（根目录 inline 模式 vs runtime-env/ filesystem 模式）
- 两套 .env.example
- `runtime-env/` 自成一体（config + .env + runtime-config/ + runtime-data/），和根目录形成平行世界
- `.acabot-runtime/` 隐藏目录存运行时数据，操作者看不到
- 命名风格混乱：`runtime-config`(kebab) / `runtime_root`(snake) / `.acabot-runtime`(dot-prefix+kebab)
- `.agents/` 隐藏目录、`plugins/` 根目录散落，扩展能力没有统一入口
- compose 挂载 `../src` 是开发模式，不是生产部署
- inline 模式和 filesystem 模式并存，且 inline 的残留散布在 router.py、session_loader.py、config_control_plane.py、control_plane.py 等多个文件
- `default_frontstage_agent` 被当成半正式对象用于 UI catalog / 新建 session 模板 / find_session_agent fallback，和 session-owned agent 主线矛盾

决策：

- **全 snake_case** 命名
- **compose 管全部（生产镜像）**，开发用 override
- **extensions/** 统一收纳 plugins/skills/subagents
- **三层真源分离**：`extensions/` 是能力包目录，`runtime_config/` 是操作者真源，`runtime_data/` 是运行时事实
- **不兼容旧结构**，新项目，直接改到最终形态
- **彻底删除 inline 模式**，filesystem-only，一路改到 router.py 和 session_loader.py
- **彻底移除 `default_frontstage_agent` 的正式身份**——它不参与路由、不代表真源、不在 UI 展示、不作为新建 session 模板
- **对齐 session-owned agent 主线**（docs/27-session-owned-agent.md）
- **清理死目录**：profiles/、bindings/、inbound_rules/、event_policies/ 在当前 runtime 代码中已无引用
- **runtime_config.example/ 是最小可启动，不是最小可响应**

## 当前主线契约

根据 docs/27-session-owned-agent.md(务必查看文件)：

- 前台正式真源是 `sessions/<scope>/session.yaml + agent.yaml`
- 不采用共享 profile 模型
- session-owned agent 是独立对象
- `SessionBundleLoader` → `SessionAgentLoader` → `ResolvedAgent.from_session_agent()` 是正式加载路径
- 无 session 匹配 → router 层 silent_drop（app.py line 218）

## 目标目录结构

```
project_root/
├── config.example.yaml          # 唯一配置模板
├── .env.example                 # 唯一环境变量模板（API key）
├── runtime_config.example/      # 最小可启动 seed（复制到 runtime_config/）
│   ├── sessions/                #   空目录，新实例默认不响应
│   ├── prompts/                 #   默认 prompt
│   ├── models/
│   │   ├── providers/
│   │   ├── presets/
│   │   └── bindings/
│   └── plugins/                 #   预留：未来 PluginSpec 真源
├── src/                         # 核心程序代码
├── webui/                       # 前端源码
├── tests/
├── runtime_config/              # 当前实例配置（git-ignored）
│   ├── sessions/                #   session + agent.yaml 真源
│   ├── prompts/                 #   prompt 文件
│   ├── models/
│   │   ├── providers/
│   │   ├── presets/
│   │   └── bindings/
│   └── plugins/                 #   预留：PluginSpec 真源（本轮不启用）
├── extensions/                  # 用户可安装扩展
│   ├── plugins/                 #   PluginPackage 根目录（当前先搬迁代码，后续可引入 plugin.yaml）
│   ├── skills/                  #   Skill 包（YAML/Markdown）
│   └── subagents/               #   Subagent 包（YAML/Markdown）
├── runtime_data/                # 所有运行时数据（git-ignored）
│   ├── db/                      #   SQLite
│   ├── soul/                    #   Self 文件
│   ├── sticky_notes/            #   Sticky notes
│   ├── backend/                 #   Backend session
│   ├── long_term_memory/        #   LanceDB（可选）
│   ├── plugins/                 #   预留：PluginStatus 真源（本轮按需生成）
│   ├── workspaces/              #   Computer 工作区 / 沙箱
│   └── debug/                   #   Model payload JSON
├── deploy/                      # 容器编排
│   ├── compose.yaml             #   生产 compose
│   ├── compose.dev.yaml         #   开发 override
│   ├── .env.example             #   compose 变量模板（端口等）
│   ├── napcat/
│   └── README.md
├── Dockerfile
└── pyproject.toml
```

## Phase 1 — 目录重命名 + 清理

### 1.1 重命名

```bash
git mv runtime-env/ deploy/
mkdir -p extensions
git mv plugins/ extensions/plugins/
mkdir -p extensions/skills extensions/subagents
```

### 1.2 删除

```bash
rm -rf .acabot-runtime/
rm -f deploy/config.example.yaml
```

### 1.3 runtime_config.example/ 种子

最小可启动 seed。复制后 `acabot` 能启动不崩溃，但不能响应消息（需要先配 session + model）。

**`runtime_config.example/prompts/default.md`**:

```
You are a helpful assistant.
```

**`runtime_config.example/sessions/`**: 空目录（.gitkeep）
**`runtime_config.example/models/providers/`**: 空（.gitkeep）
**`runtime_config.example/models/presets/`**: 空（.gitkeep）
**`runtime_config.example/models/bindings/`**: 空（.gitkeep）
**`runtime_config.example/plugins/`**: 空（.gitkeep，预留未来 PluginSpec 真源）

## Phase 2 — 后端：路径默认值 + inline 彻底清除

### 2.1 runtime_root 默认值

**文件**: `src/acabot/runtime/bootstrap/config.py`

`.acabot-runtime` → `runtime_data`

### 2.2 子路径 snake_case 化


| 文件                    | 位置                           | 旧默认                       | 新默认                       |
| ------------------------- | -------------------------------- | ------------------------------ | ------------------------------ |
| `bootstrap/__init__.py` | `sticky_notes_dir`             | `"sticky-notes"`             | `"sticky_notes"`             |
| `bootstrap/builders.py` | `payload_json_dir`             | `"debug/model-payloads"`     | `"debug/model_payloads"`     |
| `bootstrap/builders.py` | `long_term_memory.storage_dir` | `"long-term-memory/lancedb"` | `"long_term_memory/lancedb"` |

### 2.3 SQLite 默认路径

config 里写 `persistence.sqlite_path: "db/acabot.db"`（相对 runtime_data/）。

### 2.4 filesystem 默认值

config example 中 `filesystem.base_dir: "runtime_config"`。

`computer_root_dir` 从 `resolve_filesystem_path()` 改为 `resolve_runtime_path()`，默认 `"workspaces"` → `runtime_data/workspaces`。

### 2.5 extensions 路径（三类路径语义分离）

当前 `resolve_skill_catalog_dirs()` / `resolve_subagent_catalog_dirs()` 把相对路径基于 `filesystem.base_dir`（→ `runtime_config`）解析。extensions/ 不属于 runtime_config，必须基于项目根目录。

**路径语义分类**：

| 类别 | 基准 | 包含 |
|------|------|------|
| 正式配置真源 | `filesystem.base_dir`（→ `runtime_config`） | sessions/、prompts/、models/ |
| 运行时数据 | `runtime.runtime_root`（→ `runtime_data`） | db/、soul/、sticky_notes/、workspaces/ |
| 扩展目录 | 项目根目录（`config.base_dir()`） | extensions/plugins/、extensions/skills/、extensions/subagents/ |

**文件**: `src/acabot/runtime/bootstrap/config.py`

`resolve_skill_catalog_dirs()` 和 `resolve_subagent_catalog_dirs()` 中的 `_resolve_catalog_dir_path()` 改为基于 `config.base_dir()` 而非 `fs_conf["base_dir"]`：

```python
def resolve_skill_catalog_dirs(
    config: Config,
    fs_conf: dict[str, object],
    *,
    defaults: list[str],
) -> list[SkillDiscoveryRoot]:
    raw_values = fs_conf.get("skill_catalog_dirs")
    items = _normalize_catalog_dir_values(raw_values, defaults=defaults)
    project_root = config.base_dir()  # 改：不再用 fs_conf["base_dir"]

    resolved: list[SkillDiscoveryRoot] = []
    seen: set[tuple[str, str]] = set()
    for raw in items:
        scope = _scope_for_catalog_dir(raw)
        path = _resolve_catalog_dir_path(raw=raw, base_dir=project_root)
        root = SkillDiscoveryRoot(host_root_path=str(path), scope=scope)
        key = (str(root.path), root.scope)
        if key in seen:
            continue
        resolved.append(root)
        seen.add(key)
    return resolved
```

`resolve_subagent_catalog_dirs()` 同理。

这样 `defaults=["./extensions/skills"]` 就会正确解析到 `<project_root>/extensions/skills`。

**文件**: `src/acabot/runtime/control/config_control_plane.py`

line 1116 附近 `_rebuild_skill_catalog()` / `_rebuild_subagent_catalog()` 中调 `resolve_skill_catalog_dirs` / `resolve_subagent_catalog_dirs` 时传入的 `fs_conf` 不再影响 base_dir（因为函数内部已改为用 `config.base_dir()`），确认调用方无需改动。

**文件**: `src/acabot/runtime/bootstrap/builders.py`

默认值不变：

```python
defaults=["./extensions/skills"]    # 原 ["./.agents/skills", "~/.agents/skills"]
defaults=["./extensions/subagents"] # 原 ["./.agents/subagents", "~/.agents/subagents"]
```

### 2.6 彻底删除 inline 模式（三文件同一清理面）

这三个文件必须作为同一个清理面处理：

#### `src/acabot/runtime/bootstrap/loaders.py`

- `build_prompt_map()`: **删除整个函数**
- `build_prompt_loader()`: 删除 `StaticPromptLoader` 和 `runtime.prompts`。改为 `ChainedPromptLoader([FileSystemPromptLoader, SubagentPromptLoader])`
- `_build_subagent_prompt_map()`: 保留，产出注入新的 `SubagentPromptLoader`
- `build_prompt_refs()`: 删除 `runtime.prompts` 扫描和 `if not fs_enabled` 分支
- `build_session_runtime()`: 删除 inline 分支，始终 `SessionConfigLoader(sessions_dir)`
- `build_session_bundle_loader()`: 删除 `_filesystem_session_storage_enabled()` 检查，始终构造
- `_filesystem_session_storage_enabled()`: 删除

#### `src/acabot/runtime/router.py`

- line 45-47: 删除 `StaticSessionConfigLoader(_default_session_config(...))` fallback
- `RuntimeRouter.__init__` 的 `session_runtime` 参数改为必传（不再有默认值构造 inline session）
- 导入 `StaticSessionConfigLoader` 和 `_default_session_config` 删除

#### `src/acabot/runtime/control/session_loader.py`

- `ConfigBackedSessionConfigLoader`: **删除整个类**。它是 inline session 的正式 loader，留着会让人以为 runtime 还支持这条路径。

#### `src/acabot/runtime/control/prompt_loader.py`

新增 `SubagentPromptLoader(PromptLoader)`：只处理 `subagent/*` refs，从 `_build_subagent_prompt_map()` 的产出初始化。

### 2.7 彻底移除 `default_frontstage_agent` 的正式身份

这个对象当前被当成半正式对象用在多处。必须全部清理。

#### 移除触点清单


| 位置                                                          | 当前行为                                                                                              | 改为                                                                              |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `config_control_plane.py` line 333-344 `find_session_agent()` | 找不到 session agent 时 fallback 到`default_frontstage_agent`                                         | 返回`None`                                                                        |
| `config_control_plane.py` line 369-371 `create_session()`     | 新建 session 时从`default_frontstage_agent` 拷贝 agent.yaml                                           | 硬编码最小 agent payload（见下）                                                  |
| `config_control_plane.py` line 286-292                        | 热重载时用`default_frontstage_agent` 更新 router/tool_broker/subagent_delegator 的 `default_agent_id` | 删除这些赋值                                                                      |
| `control_plane.py` line 820-864 `get_ui_catalog()`            | 把`default_frontstage_agent` 作为 bot/agent 暴露给 UI                                                 | 不再返回；bot 信息从 session 列表导出                                             |
| `bootstrap/__init__.py` line 131                              | 调用`build_default_frontstage_agent()`                                                                | 替换为 `build_bootstrap_defaults()` → `BootstrapDefaults`                         |
| `bootstrap/__init__.py` line 307                              | `runtime_frontstage_agents = [default_frontstage_agent]`                                              | 初始为空列表，只从 session 收集                                                   |
| `bootstrap/__init__.py` line 276                              | `ToolBroker(default_agent_id=default_agent_id)`                                                       | `default_agent_id` 参数删除或传空                                                 |
| `bootstrap/__init__.py` line 172                              | `SubagentDelegationBroker(default_agent_id=...)`                                                      | 同上                                                                              |
| `tool_broker/broker.py` line 452-454                          | `visible_to_default_agent_only` 按 `default_agent_id` 硬过滤                                          | 改为按 session agent 的能力可见性过滤，或删除`visible_to_default_agent_only` 机制 |
| `plugins/backend_bridge_tool.py` line 58                      | `ask_backend` 工具标记 `visible_to_default_agent_only=True`                                           | 改为常规可见性控制（通过 session agent 的`visible_tools` 配置）                   |
| `bootstrap/__init__.py` line 322-332 `runtime_agent_loader`   | fallback 到`default_frontstage_agent`                                                                 | 删除 fallback；`session_bundle_loader` 为 None 时抛异常（不应发生，silent_drop 在 router 层）|

#### 新建 session 的 agent.yaml 初始内容

`create_session()` 不再从 `default_frontstage_agent` 拷贝。改为从 `bootstrap_defaults` 取 seed 值 + config 全局 computer policy：

```python
agent_payload = {
    "agent_id": agent_id,
    "prompt_ref": self.bootstrap_defaults.prompt_ref,
    "visible_tools": [],
    "visible_skills": [],
    "visible_subagents": [],
    "computer_policy": {
        "backend": self.bootstrap_defaults.computer_policy.backend,
        "allow_exec": self.bootstrap_defaults.computer_policy.allow_exec,
        "allow_sessions": self.bootstrap_defaults.computer_policy.allow_sessions,
        "auto_stage_attachments": self.bootstrap_defaults.computer_policy.auto_stage_attachments,
        "network_mode": self.bootstrap_defaults.computer_policy.network_mode,
    },
}
```

#### `build_default_frontstage_agent()` → `BootstrapDefaults`

`ResolvedAgent` 是 runtime 正式路由契约。用它装一个不参与路由、不参与 UI、不参与 target 的 bootstrap 杂项是语义污染。

改为独立的 bootstrap defaults 数据类：

**文件**: `src/acabot/runtime/bootstrap/loaders.py`

```python
@dataclass(frozen=True, slots=True)
class BootstrapDefaults:
    """Bootstrap 期间的种子默认值。不是 agent，不参与路由/UI/model target。"""
    prompt_ref: str = "prompt/default"
    computer_policy: ComputerPolicy | None = None
```

```python
def build_bootstrap_defaults(config: Config, *, default_computer_policy: ComputerPolicy) -> BootstrapDefaults:
    """从 config 构造 bootstrap 种子默认值。"""
    return BootstrapDefaults(
        prompt_ref="prompt/default",
        computer_policy=default_computer_policy,
    )
```

**文件**: `src/acabot/runtime/bootstrap/__init__.py`

bootstrap 中所有原来用 `default_frontstage_agent` 的地方改用 `BootstrapDefaults`：

```python
bootstrap_defaults = build_bootstrap_defaults(config, default_computer_policy=default_computer_policy)

# prompt_loader 初始化只需要 seed prompt_ref
prompt_loader = ReloadablePromptLoader(
    build_prompt_loader(
        config,
        prompt_refs={bootstrap_defaults.prompt_ref},
        subagent_catalog=runtime_subagent_catalog,
    )
)

# model target catalog 初始为空，等 session 加载后填充
runtime_model_target_catalog = MutableModelTargetCatalog()

# router 不再接收 default_agent_id
runtime_router = router or RuntimeRouter(session_runtime=session_runtime)

# tool_broker / subagent_delegator 不再接收 default_agent_id
# （见 Phase 2.7 触点清单）

# runtime_frontstage_agents 初始为空列表，只从 session 收集
runtime_frontstage_agents: list[ResolvedAgent] = []
if runtime_session_bundle_loader is not None:
    for bundle in runtime_session_bundle_loader.list_bundles():
        resolved = ResolvedAgent.from_session_agent(bundle.frontstage_agent)
        runtime_frontstage_agents.append(resolved)

# agent_loader fallback 不再返回 ResolvedAgent
# silent_drop 已在 router 层处理，agent_loader 只在有 session 时被调用
```

**文件**: `src/acabot/runtime/control/config_control_plane.py`

构造函数中 `default_frontstage_agent: ResolvedAgent` 参数改为 `bootstrap_defaults: BootstrapDefaults`，仅用于 `create_session()` 中取 `prompt_ref` 和 `computer_policy` 填充新 agent.yaml。

不再读取的 config.yaml 字段：`runtime.default_agent_id`、`runtime.default_prompt_ref`、`runtime.default_agent_name`、`runtime.enabled_tools`、`runtime.skills`、`runtime.visible_subagents`。

### 2.8 清理死配置键

从 config.example.yaml 的 `filesystem:` 块中删除无 runtime 代码引用的键：`profiles_dir`、`bindings_dir`、`inbound_rules_dir`、`event_policies_dir`。

### 2.9 extensions/plugins/ — 废弃旧体系 + 物理搬迁

当前 `plugins/` 下的 napcat_tools 和 notepad 两个插件基于已不存在的 `acabot.plugin.base.Plugin` 类（该模块在 src/ 中已被删除）。它们是死代码，无法被 runtime 加载。

**废弃旧插件体系**：

- `plugins/napcat_tools/` 和 `plugins/notepad/` 移到 `extensions/plugins/` 后标记废弃
- 它们导入的 `acabot.plugin.base`、`acabot.hook.base`、`acabot.types.HookPoint` 等已不存在
- 后续如需复活这些能力，须迁移到 `RuntimePlugin` 体系

**正式插件加载（runtime.plugins）**：

- 内置插件继续用 `module:Symbol`（如 `acabot.runtime.plugins.ops_control:OpsControlPlugin`）
- 这是当前 `plugin_manager.py` line 895 的正式路径，不改

**本轮不展开 extensions/ 插件的管理架构**。

当前插件真源是裂开的：

- "加载哪些插件" → `runtime.plugins` 列表（plugin_manager.py line 778）
- "插件自己的配置" → 顶层 `plugins.<plugin_name>`（config.py line 44）
- `extensions/plugins/` 只是代码目录，还不是正式管理对象

给一个真源裂开的系统加 `source` / `readonly` 标签只是表面缝合。正确的做法是插件管理体系整体升级，这需要独立 initiative（见下方设计方向），不应塞进目录重构。

**本轮只做**：

1. 物理搬迁：`git mv plugins/ extensions/plugins/`
2. `extensions/skills/`、`extensions/subagents/` 创建空目录
3. import 路径：`Dockerfile` 的 `PYTHONPATH` 包含 `/app/extensions`，`tests/conftest.py` 的 `sys.path` 改指 `extensions/`
4. 现有 `runtime.plugins` + `config_control_plane.py` 的加载/管理逻辑不改

**后续独立 initiative：Plugin = Package + Spec + Status + Reconciler**

方向：把插件收成正式管理对象，分三层各自一个职责：

```
extensions/plugins/<id>/plugin.yaml    # Package：安装包真源（是什么、入口、默认配置）
runtime_config/plugins/<id>/plugin.yaml # Spec：操作者意图（启用/禁用、配置覆盖）
runtime_data/plugins/<id>/status.json   # Status：运行时事实（加载结果、注册工具、错误）
```

核心对象：
- **PluginPackage**: 是什么插件、入口在哪、默认配置是什么
- **PluginSpec**: 操作者是否启用、配置是什么
- **PluginStatus**: 加载成功/失败、注册了哪些 tool、最后错误
- **PluginReconciler**: 做 join → diff → load/reload/unload → 写 status

API 升级为资源接口：
- `GET /api/system/plugins` — package + spec + status 合并视图
- `PUT /api/system/plugins/<id>/spec` — 改启用/配置
- `POST /api/system/plugins/<id>/reconcile` — 单插件重收敛
- `POST /api/system/plugins/reconcile` — 全量重收敛

import_path 从 UI 消失，操作者只认稳定的 `plugin_id`。WebUI 不再直接调 load/unload，而是改 Spec 让 Reconciler 收敛。

这套模型需要单独的设计文档和实施计划（docs/29-plugin-control-plane.md）。

## Phase 3 — compose 改造

### 3.1 .env 分层

- `deploy/.env`：Compose CLI 变量（端口映射等），从 `deploy/.env.example` 复制
- 根目录 `.env`：应用级变量（API key），挂载进容器由 python-dotenv 读

### 3.2 compose.yaml（生产）

**文件**: `deploy/compose.yaml`

```yaml
services:
  acabot:
    build:
      context: ..
      dockerfile: Dockerfile
    container_name: acabot
    restart: unless-stopped
    ports:
      - "${ACABOT_PORT:-8080}:8080"
      - "${ACABOT_WEBUI_PORT:-8765}:8765"
    volumes:
      - ../config.yaml:/app/config.yaml:ro
      - ../.env:/app/.env:ro
      - ../runtime_config:/app/runtime_config
      - ../runtime_data:/app/runtime_data
      - ../extensions:/app/extensions
    environment:
      - TZ=Asia/Shanghai
      - ACABOT_CONFIG=/app/config.yaml
    networks:
      - acabot_network

  napcat:
    image: mlikiowa/napcat-docker:latest
    container_name: acabot-napcat
    restart: unless-stopped
    ports:
      - "${NAPCAT_WEBUI_PORT:-6099}:6099"
    environment:
      - NAPCAT_UID=${NAPCAT_UID:-1000}
      - NAPCAT_GID=${NAPCAT_GID:-1000}
    volumes:
      - ./napcat/config:/app/napcat/config
      - ./napcat/QQ:/app/.config/QQ
    networks:
      - acabot_network

networks:
  acabot_network:
    driver: bridge
```

### 3.3 compose.dev.yaml（开发 override）

```yaml
services:
  acabot:
    volumes:
      - ../src:/app/src
      - ../webui:/app/webui
```

### 3.4 Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app

RUN pip install uv --no-cache-dir

COPY pyproject.toml ./
COPY src/ src/
RUN uv pip install --system .

COPY extensions/ extensions/

EXPOSE 8080
ENV PYTHONPATH=/app/src:/app/extensions
CMD ["python", "-m", "acabot.main"]
```

### 3.5 deploy/README.md

生产 / 开发 / 本地三种启动方式说明。

## Phase 4 — config.example.yaml

Filesystem-only，无 inline，无 `filesystem.enabled`。只列实际被 runtime 使用的配置键：

```yaml
runtime:
  persistence:
    sqlite_path: "db/acabot.db"
  # ... prompt_assembly, context_compaction, computer, plugins, webui ...
  filesystem:
    base_dir: "runtime_config"
    sessions_dir: "sessions"
    prompts_dir: "prompts"
    model_providers_dir: "models/providers"
    model_presets_dir: "models/presets"
    model_bindings_dir: "models/bindings"
```

## Phase 5 — .env.example + .gitignore 清理

### 5.1 根目录 .env.example

只保留 API key。

### 5.2 deploy/.env.example

Compose CLI 变量（端口等）。

### 5.3 .gitignore

```diff
- runtime-data/
- runtime-config/
- runtime-env/.env
- runtime-env/config.yaml
- runtime-env/runtime-config/
- runtime-env/runtime-data/
- runtime-env/napcat
- .acabot-runtime/
+ runtime_data/
+ runtime_config/
+ deploy/napcat/
+ deploy/.env
```

## Phase 6 — control plane + WebUI 适配

### 6.1 config_control_plane.py

- `DEFAULT_SKILL_CATALOG_DIRS` / `DEFAULT_SUBAGENT_CATALOG_DIRS` → `["./extensions/skills"]` / `["./extensions/subagents"]`
- `_session_bundle_storage_enabled()`: 删除
- `storage_mode()`: 删除
- 所有 `if self.storage_mode() == "filesystem":` 分支 → 直走 filesystem
- `_build_session_runtime()`: 删 inline 分支
- `_computer_root_dir()`: 改 `resolve_runtime_path`，默认 `"workspaces"`
- `_sticky_notes_dir()`: `"sticky-notes"` → `"sticky_notes"`
- `_long_term_memory_storage_dir()`: `"long-term-memory/lancedb"` → `"long_term_memory/lancedb"`
- `get_filesystem_scan_config()`: 删 `"enabled"` 字段
- `find_session_agent()`: 删 `default_frontstage_agent` fallback
- `create_session()`: agent.yaml 改为 `bootstrap_defaults` seed + 全局 `computer_policy`（不从 `default_frontstage_agent` 拷贝）

### 6.2 control_plane.py

- `get_ui_catalog()`: 删除 `default_frontstage_agent` 作为 bot/agent 的暴露
- `"bot"` 字段删除或改为从 session 列表导出

### 6.3 http_api.py

**文件**: `src/acabot/runtime/control/http_api.py`

- 系统概览 `"storage_mode"` 字段删除（line 266）
- 系统 snapshot 中涉及 `storage_mode`、旧路径默认值的字段同步清理

### 6.4 control_plane.py 系统 snapshot

**文件**: `src/acabot/runtime/control/control_plane.py`

- line 325: `"storage_mode"` 从 path_overview 透传 → 删除
- 所有引用 `default_frontstage_agent` 的地方（见 Phase 2.7 触点清单）

### 6.5 SystemView.vue

**文件**: `webui/src/views/SystemView.vue`

- 删 `storage_mode` 显示（line ~157, 668）
- 删 `filesystem.enabled` warning（line ~519）
- 删 `profiles_dir` / `profile_count` 及相关提示文案（line ~50, ~399）— 已废弃旧概念
- 删 `default_agent_id` 显示（line ~87）— 不再是正式配置项
- 更新 `PathOverview` 类型定义（line ~86），去掉 `storage_mode`、`profiles_dir`、`default_agent_id` 等
- reload result 中涉及 `storage_mode` / `default_agent_id` 的字段同步清理
- catalog dirs 跟随后端新默认值

### 6.6 公共导出面

**文件**: `src/acabot/runtime/__init__.py`

检查是否 re-export 了 `ConfigBackedSessionConfigLoader`、`StaticPromptLoader`（作为公共 API）等被删除的类型。如有则移除。

## Phase 7 — 测试修复

- 旧路径默认值适配（`.acabot-runtime` → `runtime_data`、`sticky-notes` → `sticky_notes` 等）
- `build_prompt_map()` 已删，测试写临时文件到 prompts_dir
- `StaticPromptLoader` 不再被 loaders.py 使用，subagent prompt 走 `SubagentPromptLoader`
- `ConfigBackedSessionConfigLoader` 已删，测试用 `SessionConfigLoader` + 临时 sessions 目录
- `tests/conftest.py` sys.path 改为 `extensions/`
- `tests/runtime/test_webui_api.py`（line ~1415 等）：涉及 `storage_mode`、旧 inline 契约、旧默认路径的断言全部适配
- `storage_mode` 相关断言删除或改为验证 filesystem-only 行为
- `default_frontstage_agent` 相关测试适配（不再作为正式对象出现在 UI catalog 等返回中）

## 文件清单


| 文件                                                 | 操作     | 说明                                                                   |
| ------------------------------------------------------ | ---------- | ------------------------------------------------------------------------ |
| `runtime-env/` → `deploy/`                          | 重命名   | git mv                                                                 |
| `plugins/` → `extensions/plugins/`                  | 移动     | git mv                                                                 |
| `.acabot-runtime/`                                   | 删除     | rm -rf                                                                 |
| `deploy/config.example.yaml`                         | 删除     |                                                                        |
| `runtime_config.example/`                            | **新建** | 最小可启动 seed                                                        |
| `src/acabot/runtime/bootstrap/config.py`             | 修改     | runtime_root 默认`runtime_data`；catalog 解析改为基于 `config.base_dir()` |
| `src/acabot/runtime/bootstrap/__init__.py`           | 修改     | snake_case；`BootstrapDefaults` 替代 `default_frontstage_agent`        |
| `src/acabot/runtime/bootstrap/builders.py`           | 修改     | extensions 路径、snake_case、workspaces 走 runtime_path                |
| `src/acabot/runtime/bootstrap/loaders.py`            | 修改     | 删 inline；`BootstrapDefaults` 替代 `build_default_frontstage_agent`   |
| `src/acabot/runtime/router.py`                       | 修改     | 删 StaticSessionConfigLoader fallback                                  |
| `src/acabot/runtime/control/session_loader.py`       | 修改     | 删 ConfigBackedSessionConfigLoader                                     |
| `src/acabot/runtime/control/prompt_loader.py`        | 修改     | 新增 SubagentPromptLoader                                              |
| `src/acabot/runtime/tool_broker/broker.py`           | 修改     | 删`default_agent_id` + `visible_to_default_agent_only` 机制            |
| `src/acabot/runtime/plugins/backend_bridge_tool.py`  | 修改     | 删`visible_to_default_agent_only=True`                                 |
| `src/acabot/runtime/subagents/broker.py`             | 修改     | 删`default_agent_id`                                                   |
| `src/acabot/runtime/control/config_control_plane.py` | 修改     | 删 storage_mode/inline/default_agent 触点                              |
| `src/acabot/runtime/control/control_plane.py`        | 修改     | get_ui_catalog 不再暴露 default agent；删 storage_mode 透传            |
| `src/acabot/runtime/control/http_api.py`             | 修改     | 删 storage_mode                                                        |
| `src/acabot/runtime/plugin_manager.py`               | 不改     | 本轮不展开 extensions 插件管理架构                                     |
| `src/acabot/runtime/__init__.py`                     | 修改     | 清理 re-export 的已删类型                                              |
| `webui/src/views/SystemView.vue`                     | 修改     | 删 storage_mode / filesystem.enabled / profiles_dir / default_agent_id |
| `webui/src/views/PluginsView.vue`                    | 不改     | 本轮不展开插件 UI 变更                                                 |
| `config.example.yaml`                                | 重写     | filesystem-only                                                        |
| `.env.example`                                       | 重写     | 只保留 API key                                                         |
| `deploy/.env.example`                                | 新建     | Compose 变量                                                           |
| `deploy/compose.yaml`                                | 重写     | 生产模式                                                               |
| `deploy/compose.dev.yaml`                            | 新建     | 开发 override                                                          |
| `deploy/README.md`                                   | 新建     | 部署说明                                                               |
| `Dockerfile`                                         | 重写     | 先 COPY src 再 install，非 editable                                    |
| `.gitignore`                                         | 修改     | 清理旧条目                                                             |
| `tests/conftest.py`                                  | 修改     | sys.path → extensions/                                                |
| `tests/runtime/test_webui_api.py`                    | 修改     | storage_mode / inline 契约 / 旧路径断言适配                            |
| `tests/`                                             | 修改     | 适配新默认值和接口变化                                                 |

## 执行顺序

1. Phase 1 — 目录重命名 + 种子目录
2. Phase 2 — 后端路径默认值 + inline 彻底清除 + default_agent 移除正式身份
3. Phase 3 — compose + Dockerfile
4. Phase 4 — config.example.yaml
5. Phase 5 — .env + .gitignore
6. Phase 6 — control plane + WebUI 适配
7. Phase 7 — 测试修复

## 验证

1. `cp config.example.yaml config.yaml && cp -r runtime_config.example/ runtime_config/` → 启动不崩溃
2. runtime_data/ 下出现 db/、soul/、sticky_notes/
3. 无 session 时入站消息被 silent_drop（不崩溃、不回复）
4. 配好 model provider/preset → WebUI 创建 session → 在 Session Agent 页保存模型选择（由 SessionsView 写 `agent:<agent_id>` binding）→ 消息正常响应
5. WebUI filesystem 编辑 → 文件保存到 `runtime_config/models/...`
6. 新建 session 的 agent.yaml 含硬编码最小 payload + 全局 computer_policy（不从 default_frontstage_agent 拷贝）
7. extensions/ 下的 skills/subagents 被发现
8. subagent prompt 正常加载（SubagentPromptLoader 链路）
9. 内置插件 `module:Symbol` 路径正常（extensions/ 插件管理架构留待 docs/29）
10. `cd deploy && docker compose up -d --build` 正常
11. `pytest` 通过
12. `npm run build` (webui) 通过
