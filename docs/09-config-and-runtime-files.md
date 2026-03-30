# 配置、运行时文件和生效路径

这一篇主要解决两个问题:

1. 配置到底从哪里来
2. 改完之后什么时候生效

## `Config` 还是最底层入口

关键文件:

- `src/acabot/config.py`

它主要负责:

- `from_file()`
- `get()`
- `save()`
- `reload_from_file()`
- `base_dir()`
- `resolve_path()`

### 配置文件查找顺序

`Config.from_file()` 的优先级还是:

1. 显式传入 path
2. 环境变量 `ACABOT_CONFIG`
3. 默认 `config.yaml`

### 一个现实情况

仓库根目录不一定真的有正在使用的 `config.yaml`。
实际部署更常见的是:

- `runtime-env/config.yaml`
- 再通过 `ACABOT_CONFIG` 指过去

所以你改配置逻辑时, 不要默认“项目根目录就是唯一真源”。

## 现在的配置来源有哪几类

当前系统可以把配置分成三层看:

### 1. 主配置文件

主要由 `Config` 读取。

通常包含:

- `gateway`
- `agent`
- `runtime`
- `plugins`

### 2. 文件系统配置目录

如果开了 `runtime.filesystem.enabled`, 运行时还会继续从文件系统目录加载:

- `profiles/`
- `prompts/`
- `sessions/`
- `models/`
- 其他 control plane 需要的运行时目录

当前真正和主线强相关的几类是:

- profiles
- prompts
- sessions

### 3. 运行时数据目录

这一层不是“配置真源”, 而是运行时状态和持久化数据。

常见内容包括:

- SQLite 数据
- workspace
- attachments
- self 数据
- long_term_memory 的 LanceDB 数据
- 运行过程里的临时状态

## 为什么这点重要

因为很多 WebUI 页面改的不是主 YAML 某一段, 而是运行时目录下的一组文件。

你如果只改 `Config`, 往往只改对一半。

## 哪些配置会影响哪些模块

### `gateway`

影响:

- `main.py` 创建 gateway
- WebUI 的 gateway 状态页
- 部署接线

### `agent`

影响:

- 默认 agent 创建
- 默认模型
- 默认系统 prompt

### `runtime`

影响最大, 现在通常包括:

- default agent/profile
- profiles
- filesystem 模式
- webui
- computer
- runtime plugins
- session config 的读取路径

这里有一条和 skill 直接相关的新规则:

- `runtime.filesystem.skill_catalog_dirs`

它表示“runtime 要扫描哪些 skill 根目录”。

当前规则是:

- 相对路径, 例如 `./skills`、`./agent/skills`, 算 `project`
- `~` 路径和根目录绝对路径, 算 `user`
- runtime 会递归扫描这些目录下的 `**/SKILL.md`
- 扫描阶段先保留全部 skill metadata
- 真正注入 prompt 或执行 `Skill(skill=...)` 时, 再按可见性和 `project > user` 选出最后那一份 skill

如果配置没写这个字段, runtime 默认会扫描:

- `./.agents/skills`
- `~/.agents/skills`

这里还有一条和长期记忆直接相关的新配置:

- `runtime.long_term_memory.enabled`

它表示 runtime 是否自动装配 `long_term_memory` 这一整条链路。
打开后, runtime 会自己构造:

- `LanceDbLongTermMemoryStore`
- `CoreSimpleMemWritePort`
- `CoreSimpleMemMemorySource`
- `LongTermMemoryIngestor`

这只是装配开关, 不是模型配置开关。
真正让这条链路可用, 还要先在模型绑定里配好:

- `system:ltm_extract`
- `system:ltm_query_plan`
- `system:ltm_embed`

当前这个配置块还支持这些字段:

- `storage_dir`
- `window_size`
- `overlap_size`
- `max_entries`
- `extractor_version`

### `plugins`

影响 plugin 的加载和插件私有配置。

## session bundle / prompt / session 现在分别从哪里来

关键文件:

- `src/acabot/runtime/control/session_bundle_loader.py`
- `src/acabot/runtime/control/session_agent_loader.py`
- `src/acabot/runtime/control/prompt_loader.py`
- `src/acabot/runtime/control/session_loader.py`
- `src/acabot/runtime/control/session_runtime.py`
- `src/acabot/runtime/control/config_control_plane.py`

### frontstage agent

frontstage agent 现在主要描述:

- prompt_ref
- enabled_tools
- skills
- computer policy

模型配置不在这里；模型真源统一放在 `models/providers`、`models/presets`、`models/bindings`，再由内建和插件 target 解析。

它可以来自:

- `runtime.profiles`
- 文件系统 `profiles/`

### prompt

prompt 现在可以来自:

- inline `runtime.prompts`
- 文件系统 `prompts/`
- chained fallback

### session config

session config 现在决定的是:

- routing
- admission
- persistence
- extraction
- context
- computer

它可以来自:

- config 里直接提供的 session 相关配置
- 文件系统 `sessions/`

## `RuntimeConfigControlPlane` 现在真正管什么

关键文件:

- `src/acabot/runtime/control/config_control_plane.py`

它现在保留的配置真源读写能力主要是:

- profiles
- prompts
- gateway
- runtime plugins
- session-config 驱动的 reload

如果你在找旧的:

- binding rules
- inbound rules
- event policies

那已经不是当前控制面的真源结构了。

## 热刷新和重启怎么分

不要假设所有配置都能热刷新。

### 更可能热刷新的

- profiles
- prompts
- session config
- 部分 plugin 配置

### 更可能需要重启的

- gateway 监听地址 / token
- 进程级环境变量
- Docker / NapCat 接线
- 某些基础设施初始化参数

如果你做 WebUI 配置页, 最好在页面文案里说清楚这一点。

## `runtime-env/` 现在怎么理解

这个目录更像“实际运行实例目录”, 不是源代码目录。

里面常见的东西包括:

- `compose.yaml`
- `config.yaml`
- `.env`
- `runtime-config/`
- `runtime-data/`
- `napcat/`

## 运行时目录的实际意义

### `runtime-config/`

更像给 WebUI 和 runtime 热刷新用的配置真源目录。

### `runtime-data/`

更像运行时状态和持久化数据目录, 比如:

- SQLite
- workspace
- attachments
- self 数据
- `long-term-memory/lancedb`

### `napcat/`

NapCat 自己的配置和登录态, 不属于 AcaBot 的业务配置。

## 路径解析规则

`Config.resolve_path()` 会把相对路径解析到当前配置文件所在目录。

这点很重要, 因为:

- 同样写一个相对路径
- 在项目根 config 和在 `runtime-env/config.yaml` 下面
- 实际指向的目录可能完全不同

所以你如果改 filesystem 目录、workspace、模型目录等路径, 不要只盯字符串, 要看配置文件本身在哪里。

## 设计新配置项时的建议

### 1. 先决定它属于哪一层

通常放在:

- `gateway`
- `agent`
- `runtime`
- `plugins.<plugin_name>`

不要随手塞。

### 2. 先想清楚它是不是“运行时可改”

如果以后要给 WebUI 改, 最好一开始就想好:

- 是否能热刷新
- 改完是不是要触发 reload

### 3. 先想清楚它是不是“部署态配置”

像 token、端口、挂载路径这种更偏部署态。不要和业务配置混着讲。

## AI 在改配置相关代码前要先确认的事

1. 当前实例到底读的是哪份 config
2. 是否开启了 filesystem 模式
3. 目标改动是配置真源还是运行时数据
4. 改完要不要热刷新
5. WebUI 是否也要同步暴露

## 读源码顺序建议

1. `src/acabot/config.py`
2. `src/acabot/runtime/control/config_control_plane.py`
3. `src/acabot/runtime/control/session_bundle_loader.py`
4. `src/acabot/runtime/control/session_loader.py`
5. `src/acabot/runtime/control/session_runtime.py`
6. `src/acabot/runtime/bootstrap/`
