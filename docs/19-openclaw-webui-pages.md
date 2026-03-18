结论先写在前面：OpenClaw 的 WebUI 没有一个“把群聊 / 私聊 / 多平台工作方式全塞进去”的 Bot 页面。它把职责拆得很开：连接入口在 `Overview`，平台接入和平台配置在 `Channels`，会话级覆盖在 `Sessions`，agent 工作区在 `Agents`，运维类页面单独放在 `Usage / Cron / Debug / Logs / Nodes`。

# Chat

- 定位：直接和网关建立一个聊天会话，用来人工介入、试消息、开新会话，不是系统级配置页。
- 可查看：消息流、工具消息、流式输出、compaction / fallback 状态、当前 session 的聊天记录。
- 可操作/可配置：切换 session key、发送消息、终止生成、新建 session、粘贴图片附件、打开 Markdown 侧栏、切 focus mode。
- 证据：`ref/openclaw/ui/src/ui/views/chat.ts`，`ref/openclaw/ui/src/ui/navigation.ts`

# Overview

- 定位：Control UI 的接入页和总览页，主要解决“这个 dashboard 连到哪个 gateway、怎么鉴权、现在健康不健康”。
- 可查看：连接状态、uptime、tick interval、最近 channel 刷新时间、实例数量、session 数量、cron 状态、配对 / 鉴权 / insecure HTTP 提示。
- 可操作/可配置：填写 WebSocket URL、gateway token、password、默认 session key、UI language，然后 `Connect` / `Refresh`。
- 边界：这里不是配置群聊/私聊回复策略的地方，它更像控制台入口。
- 证据：`ref/openclaw/ui/src/ui/views/overview.ts`，`ref/openclaw/ui/src/i18n/locales/en.ts`

# Channels

- 定位：平台接入和平台配置页，按 channel 维度管理 WhatsApp、Telegram、Discord、Slack、Signal、iMessage、Nostr 等。
- 可查看：每个平台的 configured / running / connected 状态、账号数量、错误信息、channel health JSON snapshot。
- 可操作/可配置：对每个 channel 打开表单化配置，直接改 `channels.<channelId>` 对应配置并 `Save` / `Reload`；某些平台还有专属操作 UI。
- 边界：这里管的是“平台/接入层”配置，不是某个 session 的个性化 AI 覆盖。
- 证据：`ref/openclaw/ui/src/ui/views/channels.ts`，`ref/openclaw/ui/src/ui/views/channels.config.ts`，`ref/openclaw/ui/src/i18n/locales/en.ts`

# Instances

- 定位：实例在线态监控页。
- 可查看：已连接实例的 host、mode、roles、scopes、platform、deviceFamily、modelIdentifier、version、最后输入时间和 presence age。
- 可操作/可配置：只有刷新，没有配置表单，本质上是只读监控页。
- 证据：`ref/openclaw/ui/src/ui/views/instances.ts`，`ref/openclaw/ui/src/i18n/locales/en.ts`

# Sessions

- 定位：会话目录和会话级 AI 覆盖页。
- 可查看：session key、label、kind、更新时间、tokens、thinking / verbose / reasoning 状态。
- 可操作/可配置：按过滤条件查看 session，修改 label，修改 thinking / verbose / reasoning 覆盖，删除 session，点进对应 chat session。
- 边界：这里是 per-session override，不是平台模板管理页。
- 证据：`ref/openclaw/ui/src/ui/views/sessions.ts`，`ref/openclaw/ui/src/i18n/locales/en.ts`

# Usage

- 定位：用量和成本分析页。
- 可查看：token/cost 总览、sessions 聚合、daily 聚合、timeseries、session logs、query insight。
- 可操作/可配置：按日期范围、时区、query、session/day/hour 过滤；切图表模式和 breakdown；点选 session 下钻；导出 `Sessions CSV` 和 `Daily CSV`。
- 边界：这是分析页，不承担运行时配置职责。
- 证据：`ref/openclaw/ui/src/ui/app-render-usage-tab.ts`，`ref/openclaw/ui/src/ui/views/usage.ts`，`ref/openclaw/ui/src/i18n/locales/en.ts`

# Cron Jobs

- 定位：调度器页面，用来创建和管理周期任务。
- 可查看：cron 全局状态、job 列表、下次运行时间、最近运行状态、run history、delivery 状态。
- 可操作/可配置：新建 job、编辑、克隆、启停、立即运行、删除、筛选 jobs / runs、加载更多、设置 agent、schedule、timezone、payload、delivery 目标等。
- 证据：`ref/openclaw/ui/src/ui/views/cron.ts`，`ref/openclaw/ui/src/i18n/locales/en.ts`

# Agents

- 定位：agent workspace 管理页，不是单页表单，而是一个多面板工作区。
- 可查看：agent 列表、默认 agent、identity 信息、workspace 路径、model、skills filter、关联文件、工具权限、技能状态、agent 相关 channel 概览、agent 相关 cron job。
- 可操作/可配置：切换 agent；在 `Overview` 面板改 agent model/fallback；在 `Files` 面板编辑 agent 文件；在 `Tools` 面板改 tool profile 和 allow/deny override；在 `Skills` 面板按 agent 开关技能；在 `Channels` / `Cron` 面板看与该 agent 相关的状态。
- 边界：这里是“agent 工作区管理”，不是 gateway 全局配置页。
- 证据：`ref/openclaw/ui/src/ui/views/agents.ts`，`ref/openclaw/ui/src/ui/views/agents-panels-status-files.ts`，`ref/openclaw/ui/src/ui/views/agents-panels-tools-skills.ts`，`ref/openclaw/ui/src/i18n/locales/en.ts`

# Skills

- 定位：技能目录和全局技能管理页。
- 可查看：技能名称、描述、来源、缺失依赖、禁用状态、原因、分组。
- 可操作/可配置：筛选技能、启用/禁用、安装缺失技能、保存技能 API key。
- 边界：这是“技能资源管理”，不是某个 agent 的专属页面；agent 级技能开关在 `Agents` 页里还有一层。
- 证据：`ref/openclaw/ui/src/ui/views/skills.ts`，`ref/openclaw/ui/src/i18n/locales/en.ts`

# Nodes

- 定位：设备配对、节点能力暴露、执行审批页。
- 可查看：pending pairing requests、paired devices、device roles/scopes/tokens、nodes 列表、binding 状态、exec approvals。
- 可操作/可配置：批准/拒绝配对、rotate/revoke device token、设置默认 node 绑定和 agent 绑定、编辑并保存 exec approvals。
- 证据：`ref/openclaw/ui/src/ui/views/nodes.ts`，`ref/openclaw/ui/src/i18n/locales/en.ts`

# Config

- 定位：网关配置编辑器，明确就是编辑 `~/.openclaw/openclaw.json`。
- 可查看：schema、ui hints、配置问题、section/subsection 结构、form/raw 两种视图。
- 可操作/可配置：在 form 模式下按 schema 改字段，或在 raw 模式直接改 JSON；支持 search、section 切换、`Reload`、`Save`、`Apply`、`Update`。
- 证据：`ref/openclaw/ui/src/ui/views/config.ts`，`ref/openclaw/ui/src/i18n/locales/en.ts`

# Debug

- 定位：运维 / 诊断页。
- 可查看：status、health、heartbeat、models catalog、event log、安全审计摘要。
- 可操作/可配置：手动发 RPC method + JSON params，刷新快照。
- 边界：这是 debug/inspection 工具，不是面向普通配置的产品页。
- 证据：`ref/openclaw/ui/src/ui/views/debug.ts`，`ref/openclaw/ui/src/i18n/locales/en.ts`

# Logs

- 定位：日志尾流页。
- 可查看：gateway file logs、日志文件路径、截断提示、按 level 分类后的日志流。
- 可操作/可配置：按文本过滤、按 level 过滤、开关 auto-follow、刷新、导出当前可见日志。
- 证据：`ref/openclaw/ui/src/ui/views/logs.ts`，`ref/openclaw/ui/src/i18n/locales/en.ts`
