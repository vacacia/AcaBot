# 管理员 Author Session

## 结论

- 群聊 / 普通前台会话保持保守，不拥有系统维护权。
- 管理员私聊引入一种单独的 `admin_author` 会话。
- `admin_author` 不是群聊 bot 的高权限版本，也不是可任意改仓库的 root maintainer。
- 它的正式语义是：**可自主创作扩展与可允许配置，但不能改 core。**

## 三层能力面

### 1. Public Frontstage

面向群聊和普通会话。

- 默认不允许改代码
- 默认不允许改系统配置
- 最多允许少量无害能力切换
- 仍然遵守 `session-owned agent` 的能力可见性模型

### 2. Admin Author Session

只允许管理员私聊进入。

- 可以直接使用 coding tools
- 可以直接修改允许范围内的文件
- 可以给自己增删 `tool / skill / subagent / prompt`
- 可以创建新 `skill / subagent / prompt`
- 可以从外部下载并安装 `skill`
- 可以修改扩展代码
- 可以触发受控 reload，让改动重新装配到 runtime

### 3. Protected Core

core 永远不属于 bot 的可写面。

- `src/acabot/**`
- `deploy/**`
- `Dockerfile`
- `pyproject.toml`
- 全局系统级主配置

这些路径对 `admin_author` 只读，不可写，不可 patch，不可通过 shell 间接改写。

## 可写范围

`admin_author` 的正式可写根目录：

- `extensions/plugins/**`
- `extensions/skills/**`
- `extensions/subagents/**`
- `runtime_config/prompts/**`
- `runtime_config/models/**`
- `runtime_config/plugins/**`
- `runtime_config/sessions/**/agent.yaml`

其中：

- `extensions/` 是 bot 的能力创作层
- `runtime_config/` 中只有被明确放开的配置目录可写
- `session-owned agent` 的 `agent.yaml` 是 bot 调整自己能力表面的正式真源

## 允许的动作

`admin_author` 应允许：

- 修改自己的 `prompt_ref`
- 修改自己的 `visible_tools`
- 修改自己的 `visible_skills`
- 修改自己的 `visible_subagents`
- 新建或编辑 prompt
- 新建或编辑 skill
- 下载并安装 skill 到 `extensions/skills/`
- 新建或编辑 subagent
- 新建或编辑扩展 plugin
- 修改扩展相关配置
- 触发 prompt / skill / subagent / plugin 的 reload 或 reconcile

## 不允许的动作

`admin_author` 不应允许：

- 修改 `src/acabot/**` core 代码
- 修改 router / pipeline / control plane / tool broker 主线
- 修改 deploy / packaging / dependency 主线
- 修改未开放的全局配置真源
- 用“先写临时脚本再执行”的方式绕过 core 写保护

## 工具面

这类会话不该继续只靠 `ask_backend(query|change)` 摘要桥。

它应该直接拥有两类工具：

- 原生 coding tools：`read / write / edit / bash`
- 结构化 authoring tools：如 `create_prompt`、`install_skill`、`create_subagent`、`reload_domains`

其中原生 coding tools 必须带路径白名单约束；结构化 tools 负责把高频动作收成正式控制面。

## 运行时语义

- `admin_author` 是单独的会话类型，不和群聊前台混用
- 它工作在完整仓库视图上，但写权限只落在允许根目录
- 它改的是扩展层和允许配置层，不是 core 层
- 它的 reload 只针对扩展域和允许配置域，不对 core 做热修改

## 一句话定义

`admin_author` = **有创作权的管理员会话**。

它可以长出新能力，可以改自己的能力表面，可以重载自己做出的扩展；  
但它不能改 AcaBot core。
