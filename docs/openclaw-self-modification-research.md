# OpenClaw 能力边界与自修改机制

本文基于 `ref/openclaw/` 源码与文档的系统性阅读，整理 OpenClaw 的能力架构、自修改机制及其边界。

---

## 目录

1. [为什么 OpenClaw 能"修改自己"](#1-为什么-openclaw-能修改自己)
2. [五类能力扩展机制](#2-五类能力扩展机制)
3. [Workspace：agent 的可变外置状态](#3-workspaceagent-的可变外置状态)
4. [Skills：渐进披露的能力单元](#4-skills渐进披露的能力单元)
5. [Plugins / Extensions：进程内能力注册](#5-plugins--extensions进程内能力注册)
6. [Session / Subagent：跨 session 自迭代](#6-session--subagent跨-session-自迭代)
7. [Chat-native 配置命令](#7-chat-native-配置命令)
8. [五层纵深防御：自修改的边界在哪](#8-五层纵深防御自修改的边界在哪)
9. [能否真正"自我迭代"](#9-能否真正自我迭代)
10. [能力全景总表](#10-能力全景总表)

---

## 1. 为什么 OpenClaw 能"修改自己"

"修改自己"不是指 agent 在一轮对话里改变措辞，而是指它改动了**会在后续运行中被 OpenClaw runtime 重新读取、解析或装配的外置真源**。

这件事之所以可能，源于一个核心设计决策：

> **Agent 的身份、记忆、技能、行为指令全部存储在 workspace 文件系统中，而 agent 默认持有对 workspace 的读写工具。**

换言之，OpenClaw 把"agent 是什么"和"agent 能操作什么"放在了同一个可变文件系统里。这不是 bug，而是刻意选择——它让 agent 成为一个可以自我演化的实体，而不是只能执行预定义指令的工具。

修改入口有三类：
- **文件工具**（`write`、`edit`、`apply_patch`）：直接修改 workspace 文件
- **CLI / 聊天命令**（`/config`、`/plugins`、`openclaw skills install`）：修改运行时配置
- **Session 工具**（`sessions_spawn`）：创建新的执行上下文

被修改的对象在后续运行中的生效时机各不相同：有的下一轮对话即生效（workspace 文件），有的需要热重载（skills），有的需要重启 gateway（plugins）。

---

## 2. 五类能力扩展机制

OpenClaw 的能力通过五个正交的机制组织，每个机制有不同的注册方式、生效时机和持久性：

```
┌─────────────────────────────────────────────────────────────┐
│  1. Workspace 文件  → 身份 / 记忆 / 行为指令               │
│     生效：每次 session 启动时读取                            │
│     修改：write / edit / apply_patch                        │
├─────────────────────────────────────────────────────────────┤
│  2. Skills          → 按需加载的操作指南                     │
│     生效：系统提示注入 name+description，正文按需 read       │
│     修改：文件写入 + chokidar 热重载（250ms）                │
├─────────────────────────────────────────────────────────────┤
│  3. Plugins         → 进程内能力注册（工具/provider/channel）│
│     生效：gateway 启动时加载                                 │
│     修改：/plugins install → 需要 restart gateway           │
├─────────────────────────────────────────────────────────────┤
│  4. Session/Subagent → 跨 session 委派与定时任务             │
│     生效：立即（spawn 是非阻塞的）                           │
│     修改：sessions_spawn / cron                              │
├─────────────────────────────────────────────────────────────┤
│  5. Config 命令     → 运行时配置写回                         │
│     生效：写入后由各消费方自行 reload                        │
│     修改：/config set / /plugins enable / /allowlist add     │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Workspace：agent 的可变外置状态

Workspace 是 agent 的 home 目录，也是文件工具的默认工作目录。与 `~/.openclaw/` 下的 config、credentials、sessions 分开存放。

### 3.1 Workspace 文件及其运行时角色

| 文件 | 角色 | 加载时机 |
|------|------|---------|
| `AGENTS.md` | 操作指令、行为说明 | 每个 session 启动 |
| `SOUL.md` | 人格、语调、行为边界 | 每个 session 启动 |
| `USER.md` | 用户画像与称呼方式 | 每个 session 启动 |
| `IDENTITY.md` | agent 名字、vibe、emoji | 每个 session 启动 |
| `TOOLS.md` | 工具使用说明 | 每个 session 启动 |
| `HEARTBEAT.md` | 心跳 / 健康状态 | 每个 session 启动 |
| `MEMORY.md` | 长期记忆 | normal session 启动 |
| `memory/*.md` | 每日记忆文件 | prompt 组装时 |
| `skills/` | workspace 级 skill 目录 | 热重载（chokidar） |
| `BOOTSTRAP.md` | 首次运行引导 | 仅 brand-new workspace |

### 3.2 Bootstrap 初始化

首次运行时，`workspace.ts` 会向 workspace 写入 `AGENTS.md`、`SOUL.md`、`TOOLS.md`、`IDENTITY.md`、`USER.md`、`HEARTBEAT.md` 的模板，并记录 `bootstrapSeededAt`。Agent 随后可以修改这些文件来定义自己。

### 3.3 Memory 文件

Memory 是 workspace 内的 Markdown 文件集合，不是隐藏状态：
- `MEMORY.md`：长期记忆摘要
- `memory/YYYY-MM-DD.md`：每日记忆

Memory flush 发生在 compaction 前，写入当天的 memory 文件。Prompt 组装时会读取 memory section 注入上下文。

### 3.4 自修改含义

Agent 通过 `write`/`edit`/`apply_patch` 修改上述文件后，改动会在下一个 session（或下一轮 prompt 构建）中被 runtime 自动读取。这构成了最基础的"自修改"闭环：

```
agent 修改 AGENTS.md → 下次 session 启动读取 → agent 行为改变
agent 写入 memory/*.md → 下次 prompt 构建注入 → agent 记忆更新
agent 创建 skills/ → chokidar 250ms 热重载 → 新 skill 可用
```

---

## 4. Skills：渐进披露的能力单元

### 4.1 Skill 是什么

每个 Skill 是一个目录，唯一必需的文件是 `SKILL.md`：

```
<skill-name>/
├── SKILL.md          ← 必需（frontmatter + 正文）
├── scripts/          ← 可选
├── references/       ← 可选
└── assets/           ← 可选
```

`SKILL.md` 的 frontmatter 定义 metadata，正文是完整操作指南：

```markdown
---
name: github
description: "GitHub operations via `gh` CLI — PRs, issues, reviews, releases"
metadata:
  openclaw:
    emoji: "🐙"
    requires:
      bins: ["gh"]
---

# GitHub Skill
（正文：仅在触发后才加载）
```

### 4.2 三级渐进式披露

| 阶段 | 内容 | 时机 | Token 成本 |
|------|------|------|-----------|
| Level 1 | `name` + `description` | 始终在系统提示中 | 低 |
| Level 2 | `SKILL.md` 正文 | 模型选定后用 `read` 加载 | 中 |
| Level 3 | `scripts/`、`references/`、`assets/` | 执行时按需访问 | 按需 |

系统提示中注入格式：
```xml
<available_skills>
<skill name="github" location="~/skills/github/SKILL.md">
GitHub operations via `gh` CLI — PRs, issues, reviews, releases
</skill>
</available_skills>
```

Token 预算：默认最多 150 个 skill、30,000 字符；超出时降级为 compact 格式。

### 4.3 六层来源与优先级

| 优先级 | 层级 | 目录 | 来源 |
|--------|------|------|------|
| 1（最低） | `extra` | config 声明 + 插件声明 | operator / plugin |
| 2 | `bundled` | `<package_root>/skills/` | 随 OpenClaw 分发 |
| 3 | `managed` | `~/.openclaw/skills/` | CLI 管理安装 |
| 4 | `agents-skills-personal` | `~/.agents/skills/` | 个人 agent skills |
| 5 | `agents-skills-project` | `<workspace>/.agents/skills/` | 项目级 agent skills |
| 6（最高） | `workspace` | `<workspace>/skills/` | ClawHub 安装 / agent 自创 |

同名 skill 按优先级覆盖，workspace 层永远胜出。

### 4.4 安装与发现

```bash
openclaw skills search <query>    # 从 ClawHub 搜索
openclaw skills install <slug>    # 安装到 workspace/skills/
openclaw skills update [slug]     # 更新已安装 skill
openclaw skills list              # 列出所有可用 skill
openclaw skills check             # 检查依赖就绪状态
```

安装流程：ClawHub API → 下载 `.skill`（zip 归档）→ 解压验证 → 复制到 `workspace/skills/<slug>/` → 写入 `.clawhub/lock.json`。

### 4.5 资格过滤

Skill 可声明运行时依赖，不满足则自动排除：
- `requires.bins`：必须存在的可执行文件
- `requires.anyBins`：至少一个存在
- `requires.env`：必须存在的环境变量
- `requires.config`：必须存在的配置路径
- `metadata.os`：限定平台

`metadata.always: true` 可跳过所有检查，始终注入。

### 4.6 热重载

`refresh.ts` 使用 chokidar 监听所有 skill 目录下的 `*/SKILL.md`：
- 监听事件：add / change / unlink
- 防抖延迟：250ms
- 触发后：`bumpSkillsSnapshotVersion()` 递增版本号，通知所有消费者重建 prompt

### 4.7 Agent 自创 Skill

内置的 `skill-creator` 元技能（bundled skill）定义了 6 步创作流程：

1. **Understand** — 明确用途边界
2. **Plan** — 确定 frontmatter description（触发关键）
3. **Initialize** — 运行 `init_skill.py` 脚手架
4. **Edit** — 编写 SKILL.md 正文
5. **Package** — 运行 `package_skill.py` 打包为 `.skill`
6. **Iterate** — 测试触发，迭代修订

自创 skill 写入 workspace 层后，chokidar 250ms 内热重载，**无需重启 runtime，当前对话内即可生效**。

---

## 5. Plugins / Extensions：进程内能力注册

### 5.1 Plugin 是什么

Plugin 是 OpenClaw 的**所有权边界**——一个 plugin 拥有某个"厂商"或"功能"的全部 surface。例如 `openai` plugin 拥有 OpenAI 的 text inference + speech + image generation。

**Extension = Plugin 的代码实现单元。** `extensions/` 目录下的是 bundled plugins（第一方），第三方 plugin 发布到 ClawHub / npm 后安装进来。二者走同一套 `register(api)` 契约。

### 5.2 四层装配模型

```
1. Discovery     读 openclaw.plugin.json manifest，不执行代码
2. Enablement    决定 enabled / disabled / blocked，处理独占槽位
3. Loading       jiti 进程内加载，调用 register(api)，写入 Plugin Registry
4. Consumption   core / channels 从 Registry 读取 tools / providers / hooks
```

**Manifest-First 原则**：发现、校验、UI hints、onboarding metadata 全部来自 manifest，不依赖 plugin 代码执行。

### 5.3 Plugin 能注册的能力完整清单

**Capability 注册：**

| 方法 | 能力 |
|------|------|
| `registerProvider(...)` | LLM 推理 provider |
| `registerCliBackend(...)` | 本地 CLI 推理后端 |
| `registerChannel(...)` | 消息 channel |
| `registerSpeechProvider(...)` | TTS / STT |
| `registerMediaUnderstandingProvider(...)` | 图片/音频/视频理解 |
| `registerImageGenerationProvider(...)` | 图像生成 |
| `registerWebSearchProvider(...)` | 网络搜索 |

**Agent 工具与命令：**

| 方法 | 说明 |
|------|------|
| `registerTool(tool, opts?)` | 注册 agent tool（必选或 `optional: true`） |
| `registerCommand(def)` | 注册自定义 slash command |

**基础设施：**

| 方法 | 说明 |
|------|------|
| `registerHook(events, handler)` | 事件 hook |
| `registerHttpRoute(params)` | 网关 HTTP 端点 |
| `registerGatewayMethod(name, handler)` | 网关 RPC 方法 |
| `registerCli(registrar)` | CLI 子命令 |
| `registerService(service)` | 后台 service |

**独占槽位：**

| 方法 | 说明 |
|------|------|
| `registerContextEngine(id, factory)` | Context engine（全局唯一） |
| `registerMemoryPromptSection(builder)` | Memory prompt section |
| `registerMemoryFlushPlan(resolver)` | Memory flush plan |
| `registerMemoryRuntime(runtime)` | Memory runtime adapter |

### 5.4 Plugin 的行为修改能力

Plugin 通过 Hooks 可以拦截运行时关键路径：

| Hook | 拦截点 | 能力 |
|------|--------|------|
| `before_tool_call` | tool 调用前 | 阻止调用 或 触发审批 |
| `message_sending` | 消息发出前 | 取消发送 |
| `before_model_resolve` | 模型解析前 | 覆盖 model/provider 选择 |
| `before_prompt_build` | prompt 构建前 | 修改 prompt 内容 |

Provider plugin 还有 24 个专属 hook（`resolveDynamicModel`、`wrapStreamFn`、`sanitizeReplayHistory` 等），可以全程干预推理管道。

### 5.5 Plugin 生命周期

```
install  → openclaw plugins install <spec>
           npm install --omit=dev --ignore-scripts（安全：禁止 lifecycle scripts）
           写入 plugins.installs.<id>

enable   → plugins.allow 或 enabledByDefault: true

load     → gateway 启动时 jiti 加载 → register(api) → Plugin Registry

runtime  → 通过 registry 暴露 tools / channels / providers / hooks

disable  → plugins.deny 或移除 plugins.allow（配置保留）

uninstall → openclaw plugins uninstall（可 --keep-files / --keep-config）
```

### 5.6 Extensions 分类

```
extensions/
├── Channel 类:  discord, telegram, slack, qqbot, whatsapp, line, signal...
├── Provider 类: anthropic, openai, google, ollama, deepseek, groq...
├── Feature 类:  memory-core, memory-lancedb, browser, voice-call...
├── 媒体能力类:  deepgram, elevenlabs, fal...
└── 搜索类:      brave, duckduckgo, exa, perplexity, tavily...
```

### 5.7 关键边界

- **Plugin 运行 in-process，没有沙箱隔离** — native plugin 与 core 拥有完全相同的进程级信任
- 安全保障来自安装侧（`--ignore-scripts`、路径逸出检测、allowlist）而不是运行时沙箱
- 工具名不能与 core tools 冲突
- 独占槽位（memory / contextEngine）同时只能有一个激活
- Plugin 不能替代另一个 plugin 的 HTTP route

---

## 6. Session / Subagent：跨 session 自迭代

### 6.1 Session 工具套件

| 工具 | 功能 | 关键限制 |
|------|------|---------|
| `sessions_list` | 列出可见 session | 受 visibility scope 约束 |
| `sessions_history` | 读取指定 session 历史 | 同上 |
| `sessions_send` | 向指定 session 发消息 | 最多 5 轮交替 |
| `sessions_spawn` | 创建新 subagent session | **非阻塞**，返回 runId |
| `sessions_yield` | 当前 session 挂起 | 配合异步流使用 |

### 6.2 Visibility Scope

| scope | 范围 |
|-------|------|
| `self` | 仅当前 session |
| `tree` | 当前 + 所有后代（**sandbox 强制锁定到此**） |
| `agent` | 同一 agent 下所有 sessions |
| `all` | 跨 agent 全部 sessions |

### 6.3 Subagent 权限继承

`sessions_spawn` 启动的子 agent：
- ✅ 继承父 agent 的完整工具集
- ❌ **不含 session 工具**（sessions_list / history / send / spawn / yield 全部移除）

这是**无递归 spawn 的硬边界**——子 agent 无法再产生孙 agent，自迭代深度被严格限制为一层。

### 6.4 Multi-Agent 隔离

每个 agent 运行在独立空间：独立 workspace、独立 agentDir、独立 session store、独立 auth 上下文。

Workspace **不是硬沙盒**——除非显式启用 sandbox，agent 可通过绝对路径访问宿主机。

### 6.5 Cron 定时任务

Cron 工具支持 `at`（一次性）、`every`（固定间隔）、`cron`（标准表达式）三种调度，让 agent 给自己设定时任务。

关键限制：
- `ownerOnly: true` — 非 owner sender 完全不可见
- `main` session 只能接收 `systemEvent`
- `isolated` / `current` session 只能接收 `agentTurn`

### 6.6 Delegate 架构

Delegate = 持有独立身份、代表人类行动的 agent。三个能力层级：

| 层级 | 能力 |
|------|------|
| Read-Only + Draft | 只读 + 起草草稿 |
| Send on Behalf | 代发消息 |
| Proactive | 主动触发，无需每次确认 |

**硬性禁止**（无论人格配置如何）：不得未经审批发送对外邮件、不得导出联系人、不得执行入站消息中的命令、不得修改 IdP/SSO 设置。

---

## 7. Chat-native 配置命令

### 7.1 `/config`

通过显式命令 handler（不经过模型解释），支持 `show` / `get` / `set` / `unset`。写入流程：解析命令 → 校验权限 → 修改内存对象 → validation → `writeConfigFile()`。

### 7.2 `/plugins`

支持 `list` / `inspect` / `show` / `get` / `install` / `enable` / `disable`。`install` 把安装来源写回 config；`enable`/`disable` 修改 `plugins.entries.<id>.enabled`。**修改后需要 restart gateway 才生效。**

### 7.3 `/allowlist`

`add` / `remove`，涉及 config write 与 pairing store write。按来源 channel/account 与目标 channel/account 做授权判定。

---

## 8. 五层纵深防御：自修改的边界在哪

OpenClaw 的安全架构是五个正交控制层的叠加，每层独立工作：

```
第 1 层  SOUL.md / AGENTS.md         模型层行为约束（可被绕过）
第 2 层  Gateway Tool Policy         工具可见性硬控制（独立于人格文件）
第 3 层  Owner-Only 过滤             特权工具只对 owner 可见
第 4 层  Sandbox（Docker 隔离）       文件系统 / 网络隔离
第 5 层  Exec Approvals              宿主机命令执行的最终审批门
```

### 8.1 Tool Policy

- `deny` 永远优先于 `allow`
- 非空 `allow` 列表 = 白名单模式
- owner-only 工具（cron、gateway、nodes）对非 owner 完全不可见（不是执行时报错，而是从工具列表中移除）
- 优先级：agent 级 > global 级 > 系统默认

### 8.2 Sandbox

| 配置 | 选项 |
|------|------|
| mode | `off`（默认）/ `non-main` / `all` |
| scope | `shared` / `agent`（默认）/ `session` |

Docker 容器安全默认值：
- `network: none`（完全禁止网络）
- `capDrop: [ALL]`
- `readOnlyRoot: true`
- `workspaceAccess: none`

**绝对禁止（无配置可绕过）：** `network: host`、`seccompProfile: unconfined`、`apparmorProfile: unconfined`。

宿主机路径封锁：`/etc`、`/proc`、`/sys`、`/dev`、`/root`、`/boot`、`/var/run/docker.sock` 等不可 bind mount。

### 8.3 Exec Approvals

| 参数 | 选项 | 默认值 |
|------|------|--------|
| `ExecSecurity` | `deny` / `allowlist` / `full` | `deny` |
| `ExecAsk` | `off` / `on-miss` / `always` | `on-miss` |

持久审批存储在 `~/.openclaw/exec-approvals.json`（权限 `0o600`），基于命令 SHA256 哈希匹配。

### 8.4 Trust Model

> OpenClaw 是单用户个人助理模型，非多租户系统。

- 经过 Gateway 认证的调用者 = 受信任的 operator
- Agent / Model 本身不是受信任的主体
- Session identifier 是 routing control，不是 per-user authorization boundary
- Exec approvals 是 operator guardrails，不是 multi-tenant authorization boundary

**关键原则：工具限制在 Gateway 层强制执行，独立于 SOUL.md / AGENTS.md 等人格文件。** 人格文件被模型"看到"不等于其中的限制条款能阻止工具调用——只有 Gateway 的 tool policy 才是真正的执行边界。

---

## 9. 能否真正"自我迭代"

### 9.1 Agent 可以做到的

| 自迭代行为 | 机制 | 生效时机 |
|-----------|------|---------|
| 修改自己的行为指令 | 写 `AGENTS.md` / `SOUL.md` | 下次 session |
| 积累长期记忆 | 写 `MEMORY.md` / `memory/*.md` | 下次 prompt 构建 |
| 创建新 skill | 写 `workspace/skills/` | 250ms 热重载 |
| 修改已有 skill | 编辑 `SKILL.md` | 250ms 热重载 |
| 给自己设定时任务 | cron 工具 | 立即 |
| 委派子任务 | sessions_spawn | 立即（非阻塞） |
| 修改工具可见性配置 | /config set | 写入后 |

### 9.2 Agent 不能做到的

| 硬边界 | 原因 |
|--------|------|
| 修改 OpenClaw 核心代码 | 二进制分发，不在 workspace 内 |
| 修改模型权重 | 模型由外部 provider 提供 |
| 绕过 tool policy | Gateway 层硬控制，独立于人格文件 |
| 绕过 sandbox 网络隔离 | Docker level 强制 |
| 递归 spawn subagent | 子 agent 不持有 session 工具 |
| 修改 exec approvals 配置 | 在 `~/.openclaw/` 下，非 workspace 内 |
| 提升自己的 visibility scope | sandbox 场景强制锁定到 `tree` |
| 安装 plugin 并立即生效 | 需要 restart gateway |
| 跨 agent 修改其他 agent 的 workspace | Multi-agent 隔离 |

### 9.3 本质判断

OpenClaw 的"自我迭代"准确地说是：

> **用户授权范围内的、受 runtime 契约约束的、对自身外置状态的修改。**

它不是无限制的自我重写——agent 能改的是 workspace 里的 Markdown 文件和 skill 目录，不能改 runtime 本身。但在这个范围内，闭环是完整的：agent 可以修改自己的行为指令、记忆、技能，并在下一轮运行中看到这些修改的效果。

与传统软件的"配置热更新"相比，OpenClaw 的特殊之处在于：被修改的不只是参数，而是 agent 的身份（SOUL.md）、操作指令（AGENTS.md）和能力集合（skills/）。这使得"自修改"的语义远超简单的配置变更。

---

## 10. 能力全景总表

| 能力类型 | 注册方式 | 持久性 | 生效时机 | Agent 可自行操作 |
|---------|---------|--------|---------|-----------------|
| **身份/行为指令** | workspace 文件 | 持久 | 下次 session | ✅ write/edit |
| **记忆** | workspace 文件 | 持久 | 下次 prompt | ✅ write/edit + auto flush |
| **Skill** | SKILL.md 文件 | 持久 | 250ms 热重载 | ✅ 文件写入 / skills install |
| **Plugin 工具** | register(api) | 持久 | gateway 重启 | ⚠️ /plugins install（需重启） |
| **Plugin provider** | register(api) | 持久 | gateway 重启 | ⚠️ 同上 |
| **Plugin channel** | register(api) | 持久 | gateway 重启 | ⚠️ 同上 |
| **Plugin hook** | register(api) | 持久 | gateway 重启 | ⚠️ 同上 |
| **Subagent session** | sessions_spawn | 会话级 | 立即 | ✅ |
| **定时任务** | cron 工具 | 持久 | 立即 | ✅（owner-only） |
| **运行时配置** | /config set | 持久 | 各消费方自行 | ✅ slash command |
| **Tool policy** | config | 持久 | config reload | ⚠️ /config set（受权限约束） |
| **Exec approval** | 持久文件 | 持久 | 即时 | ❌ 不在 workspace 内 |
| **Sandbox 配置** | config | 持久 | gateway 重启 | ⚠️ /config set |

---

## 附录 A：本次调研阅读的主要源文件

<details>
<summary>展开完整文件列表</summary>

**文档：**
- `ref/openclaw/SECURITY.md`
- `ref/openclaw/docs/concepts/agent.md`
- `ref/openclaw/docs/concepts/agent-workspace.md`
- `ref/openclaw/docs/concepts/memory.md`
- `ref/openclaw/docs/concepts/session.md`
- `ref/openclaw/docs/concepts/session-tool.md`
- `ref/openclaw/docs/concepts/multi-agent.md`
- `ref/openclaw/docs/concepts/delegate-architecture.md`
- `ref/openclaw/docs/start/bootstrapping.md`
- `ref/openclaw/docs/tools/apply-patch.md`
- `ref/openclaw/docs/tools/exec.md`
- `ref/openclaw/docs/gateway/sandbox-vs-tool-policy-vs-elevated.md`
- `ref/openclaw/docs/plugins/architecture.md`
- `ref/openclaw/docs/plugins/building-plugins.md`
- `ref/openclaw/docs/plugins/manifest.md`
- `ref/openclaw/docs/plugins/sdk-overview.md`
- `ref/openclaw/docs/plugins/agent-tools.md`

**实现：**
- `ref/openclaw/src/agents/apply-patch.ts`
- `ref/openclaw/src/agents/pi-tools.ts`
- `ref/openclaw/src/agents/pi-tools.read.ts`
- `ref/openclaw/src/agents/tool-catalog.ts`
- `ref/openclaw/src/agents/tool-fs-policy.ts`
- `ref/openclaw/src/agents/tool-policy.ts`
- `ref/openclaw/src/agents/workspace.ts`
- `ref/openclaw/src/agents/system-prompt.ts`
- `ref/openclaw/src/agents/skills/workspace.ts`
- `ref/openclaw/src/agents/skills/refresh.ts`
- `ref/openclaw/src/agents/sandbox/constants.ts`
- `ref/openclaw/src/agents/sandbox/tool-policy.ts`
- `ref/openclaw/src/agents/tools/cron-tool.ts`
- `ref/openclaw/src/infra/exec-approvals.ts`
- `ref/openclaw/src/auto-reply/reply/commands-core.ts`
- `ref/openclaw/src/auto-reply/reply/config-commands.ts`
- `ref/openclaw/src/auto-reply/reply/plugins-commands.ts`
- `ref/openclaw/src/auto-reply/reply/commands-allowlist.ts`
- `ref/openclaw/src/cli/plugins-cli.ts`
- `ref/openclaw/src/cli/plugins-install-persist.ts`
- `ref/openclaw/src/config/config-paths.ts`
- `ref/openclaw/src/config/io.ts`
- `ref/openclaw/packages/plugin-package-contract/`
- `ref/openclaw/extensions/memory-core/`
- `ref/openclaw/extensions/browser/`
- `ref/openclaw/skills/skill-creator/`

</details>
