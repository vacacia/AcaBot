# 配置、运行时文件和生效路径

AcaBot 的配置分三层：主配置文件（`config.yaml`）、文件系统配置目录（`runtime_config/`）和运行时数据目录（`runtime_data/`）。理解这三层的区别是修改任何配置逻辑的前提。

## Config 对象

`src/acabot/config.py` 中的 `Config` 是最底层配置入口，提供 `from_file()`、`get()`、`save()`、`reload_from_file()`、`base_dir()` 和 `resolve_path()`。

`Config.from_file()` 按以下优先级查找配置文件：显式传入路径 > 环境变量 `ACABOT_CONFIG` > 默认 `config.yaml`。实际部署中，配置文件通常在 `deploy/` 目录下，通过 `ACABOT_CONFIG` 指向，而不是仓库根目录。

`Config.resolve_path()` 将相对路径解析到配置文件所在目录（而不是仓库根目录），所以同一个相对路径在不同位置的 config 下会指向不同的实际目录。

## 三层配置来源

### 主配置文件（`config.yaml`）

由 `Config` 读取，包含四个顶层块：

| 块 | 影响范围 |
|-----|---------|
| `gateway` | 网关创建、监听地址、WebUI 网关状态页 |
| `agent` | 默认 agent、默认模型、默认系统 prompt |
| `runtime` | filesystem 模式、computer、session 读取路径、长期记忆开关、skill 目录等（影响最广） |
| `plugins` | 插件加载和私有配置 |

`runtime` 块中三个值得注意的子配置：

- **`runtime.render.width` / `runtime.render.device_scale_factor`**：render 默认截图参数。`width` 控制基础 viewport 宽度，`device_scale_factor` 控制像素密度；两者都属于全局默认值，由 bootstrap 注入 Playwright render backend，也可通过 WebUI 系统页和 `/api/render/config` 读写。它们影响 `message.send.render` 的 runtime 内部渲染流程，不会把 render artifact 移进 `/workspace`。
- **`runtime.filesystem.skill_catalog_dirs`**：指定 skill 扫描根目录。相对路径视为 `project` 来源，`~` 或绝对路径视为 `user` 来源。默认扫描 `./.agents/skills` 和 `~/.agents/skills`，递归查找 `**/SKILL.md`。注入和执行时按 `project > user` 优先级选取。
- **`runtime.long_term_memory.enabled`**：装配开关（不是模型配置开关）。打开后自动构造 `LanceDbLongTermMemoryStore`、`LtmWritePort`、`LtmMemorySource` 和 `LongTermMemoryIngestor`。实际可用还需要在 `models/bindings/` 中配好 `system:ltm_extract`、`system:ltm_query_plan`、`system:ltm_embed` 三个 target。该配置块还支持 `storage_dir`、`window_size`、`overlap_size`、`max_entries`、`extractor_version`。

### 文件系统配置目录（`runtime_config/`）

当前是唯一模式（inline 配置已移除）。runtime 从这里加载 prompts、sessions、models 和 plugins 配置：

```
runtime_config/
  models/
    providers/          # 模型提供方
    presets/             # 模型预设
    bindings/            # 模型绑定（含 target 映射）
  prompts/               # prompt 模板
  sessions/              # session config + session-owned agent
    qq/group/<id>/session.yaml + agent.yaml
    qq/private/<id>/session.yaml + agent.yaml
  plugins/               # 插件私有配置
```

### 运行时数据目录（`runtime_data/`）

不是配置真源，而是运行时状态和持久化数据：

```
runtime_data/
  soul/                  # /self 连续性文件（today.md、daily/）
  sticky_notes/          # 实体便签（user/、conversation/）
  workspaces/            # thread workspace
  render_artifacts/      # runtime 内部 render 图片 / html artifact
  debug/                 # 调试产物（payload json 等）
  acabot.db              # SQLite 主库
  long_term_memory/      # LanceDB 数据
```

很多 WebUI 页面操作的是 `runtime_config/` 或 `runtime_data/` 下的文件，而不是主 YAML。只改 `Config` 对象往往只改对一半。

## 其他仓库目录

| 目录 | 用途 |
|------|------|
| `deploy/` | 部署实例目录，含 `compose.yaml`、`compose.dev.yaml`、`README.md` |
| `extensions/` | 能力包目录，含 `plugins/`、`skills/`、`subagents/` |

## Session、Agent 和 Prompt 的加载

相关加载器在 `src/acabot/runtime/control/` 下：

**Frontstage agent**（`session_agent_loader.py`）描述 `prompt_ref`、`enabled_tools`、`skills`、`computer_policy`。模型配置不在这里，而是统一放在 `models/` 目录下由 target 解析。

**Prompt**（`prompt_loader.py`）从 `runtime_config/prompts/` 加载，支持 chained fallback。

**Session config**（`session_loader.py`）控制六个决策域：routing、admission、persistence、extraction、context、computer。从 `runtime_config/sessions/` 加载。

## RuntimeConfigControlPlane

`src/acabot/runtime/control/config_control_plane.py` 提供配置真源的读写能力，当前覆盖：profiles、prompts、gateway、render 默认值、runtime plugins，以及 session-config 驱动的 reload。

## 热刷新与重启

并非所有配置都支持热刷新。

| 支持热刷新 | 需要重启 |
|-----------|---------|
| profiles、prompts、session config、`runtime.render.width`、`runtime.render.device_scale_factor`、部分 plugin 配置 | gateway 监听地址/token、进程级环境变量、Docker/NapCat 接线、基础设施初始化参数 |

## 源码阅读顺序

1. `src/acabot/config.py`
2. `src/acabot/runtime/control/config_control_plane.py`
3. `src/acabot/runtime/control/session_bundle_loader.py`
4. `src/acabot/runtime/control/session_loader.py`
5. `src/acabot/runtime/control/session_runtime.py`
6. `src/acabot/runtime/bootstrap/`
