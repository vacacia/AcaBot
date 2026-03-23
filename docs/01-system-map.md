# AcaBot 系统地图

这一篇不讲很细的实现，而是讲现在这套系统到底由哪些块组成、主线怎么走、哪些边界最容易看错。

如果你第一次接手这个项目，建议把它当成“总装配图”来看。

## 先讲结论

AcaBot 现在真正的主线，已经不是“很多规则 + 一些旁路”那种形状了。

现在更接近下面这条线：

`Gateway -> RuntimeApp -> SessionRuntime -> RuntimeRouter -> ThreadPipeline -> ModelAgentRuntime -> Outbox -> Gateway`

同时还有几条稳定侧边线：

- `ToolBroker` 负责工具可见性、工具执行和工具副产物
- `builtin_tools/` 负责把 runtime 自带能力接成给模型看的基础工具
- `PluginManager` 负责外部扩展 plugin
- `ComputerRuntime` 负责 `/workspace /skills /self` 这一套前台文件和 shell 能力
- `RuntimeControlPlane + RuntimeHttpApiServer + WebUI` 负责本地控制面
- `storage/` 和 `memory/` 负责事实记录、working memory 和长期记忆

如果你只记一句话，可以记这个：

> **SessionRuntime 负责“这条消息在当前会话里该怎么解释”，RuntimeRouter 负责把结果收成可执行路由，ThreadPipeline 负责真的把这次 run 跑完。**

---

## 顶层目录现在各自是什么

`src/acabot` 下面现在最重要的几块是：

- `main.py`
  - 启动入口
  - 读配置
  - 创建 gateway、agent 和 runtime
- `config.py`
  - 配置容器
  - 负责 YAML 读写和路径解析
- `types/`
  - 跨层共享的数据对象
  - 重点是 `StandardEvent` 和 `Action`
- `gateway/`
  - 平台协议适配层
  - 当前正式实现是 NapCat / OneBot v11
- `agent/`
  - 面向模型调用的抽象层
  - 定义 `BaseAgent`、tool 契约、response 契约
- `runtime/`
  - 当前最重要的目录
  - 主流程、路由、记忆、工具、控制面、模型解析都在这里
- `webui/`
  - WebUI 前端源码
  - 真正开发时看的是 `webui/src/`
- `src/acabot/webui/`
  - WebUI 构建产物
  - `RuntimeHttpApiServer` 托管的是这里，不是 `webui/src/`

---

## 真实依赖方向

脑子里最好一直保留这条方向：

`types -> gateway / agent -> runtime -> webui`

具体一点：

- `types` 只放共享对象，不该依赖 runtime 细节
- `gateway` 依赖 `types`
- `agent` 依赖自己的契约和少量通用对象
- `runtime` 依赖 `config / types / gateway / agent`
- `webui` 不直接碰 Python 内部状态，只通过 HTTP API

这条方向不是为了好看，而是为了避免越界。

如果你发现：

- `gateway` 开始决定 agent 绑定
- `types` 开始带业务判断
- `webui` 试图绕过 HTTP API 直接假设 Python 内部结构

那基本就是边界被写坏了。

---

## 启动和装配层

关键文件：

- `src/acabot/main.py`
- `src/acabot/runtime/bootstrap/`
- `src/acabot/runtime/app.py`

### `main.py`

只负责把最外层东西创建出来：

- 读配置
- 创建 gateway
- 创建 agent
- 调 `build_runtime_components()`

它不是业务主线，不要把 runtime 逻辑塞回去。

### `runtime/bootstrap/`

这是现在真正的默认装配中心。

`build_runtime_components()` 会把这些东西接起来：

- `RuntimeRouter`
- `SessionRuntime`
- `ThreadManager`
- `RunManager`
- `ToolBroker`
- `ComputerRuntime`
- `MemoryBroker`
- `ThreadPipeline`
- `RuntimeControlPlane`
- `RuntimeHttpApiServer`
- `PluginManager`
- `Outbox`

另外很重要的一点是：

- 前台基础工具现在不是 plugin 注册进去的
- `bootstrap` 启动时会调用 `runtime/builtin_tools/__init__.py`
- 直接把 builtin tool 注册到 `ToolBroker`

也就是：

- `builtin:computer`
- `builtin:skills`
- `builtin:subagents`

这条线现在是主线，不是补丁。

### `RuntimeApp`

`RuntimeApp` 是 runtime 的总入口。

它主要负责：

- 启动 gateway、plugin 和恢复逻辑
- 接住 gateway 上来的 event
- 做最小入口分流
- 调 router
- 创建 / 获取 thread 和 run
- 把 `RunContext` 交给 pipeline

---

## 消息主线现在怎么走

### 第 1 步：Gateway 先把平台消息翻译成 `StandardEvent`

关键文件：

- `src/acabot/gateway/napcat.py`
- `src/acabot/types/event.py`

到这一步为止，只应该发生协议层事情：

- 平台事件翻译
- segment 归一化
- attachment 提取
- reply / mention / targets_self 归一化

### 第 2 步：`SessionRuntime` 先解释这条消息

关键文件：

- `src/acabot/runtime/control/session_runtime.py`
- `src/acabot/runtime/control/session_loader.py`
- `src/acabot/runtime/contracts/session_config.py`

这是现在整条主线里最关键的一层。

它会先把消息收成：

- `EventFacts`

然后继续做：

- session 定位
- surface 解析
- 不同决策域的决策

当前会算的决策至少包括：

- `routing`
- `admission`
- `persistence`
- `extraction`
- `context`
- `computer`

也就是说，今天真正决定“这条消息怎么跑”的，不是旧的 rule 文件，而是：

> **SessionConfig + SessionRuntime**

### 第 3 步：`RuntimeRouter` 把这些结果收成 `RouteDecision`

关键文件：

- `src/acabot/runtime/router.py`

它负责两件事：

1. 生成稳定 ID
   - `actor_id`
   - `channel_scope`
   - `thread_id`
2. 把 session runtime 算好的决策收成 `RouteDecision`

所以 `router.py` 现在不是新的规则中心，它更像一个把“解释结果”装配成“运行时结果”的薄层。

### 第 4 步：`ThreadPipeline` 真正执行这次 run

关键文件：

- `src/acabot/runtime/pipeline.py`

它会把一条消息带过完整主线：

- 运行 plugin hook
- 准备 computer 上下文和附件
- 准备消息输入材料
- 写入 thread working memory
- 做 context compaction
- 做 retrieval planning
- 注入长期记忆
- 调模型
- 发送动作
- 收尾 run
- 必要时触发 memory extraction

### 第 5 步：`ModelAgentRuntime` 调模型

关键文件：

- `src/acabot/runtime/model/model_agent_runtime.py`

它负责：

- 读取 prompt
- 解析当前 run 真正可见的 tools
- 组装 system prompt
- 调底层 `BaseAgent.run()`
- 把结果转成 runtime 认识的结构

### 第 6 步：`Outbox` 发消息并记录消息事实

关键文件：

- `src/acabot/runtime/outbox.py`

这里处理的是：

- 哪些动作真的要发到平台
- 哪些动作属于“送达事实”
- 哪些动作需要写 `MessageStore`

---

## runtime 里最重要的几个子域

## 1. 路由和会话决策

关键文件：

- `runtime/router.py`
- `runtime/control/session_runtime.py`
- `runtime/control/session_loader.py`
- `runtime/contracts/session_config.py`
- `runtime/control/profile_loader.py`

这是“消息为什么这样跑”的入口。

现在的分工要记住：

- `SessionRuntime`: 解释消息
- `RuntimeRouter`: 收口路由结果
- `ProfileLoader`: 读取 profile 和 prompt

## 2. 工具和能力表面

关键文件：

- `runtime/tool_broker/`
- `runtime/builtin_tools/`
- `runtime/plugin_manager.py`
- `runtime/plugins/`

### `ToolBroker`

它是统一工具入口，负责：

- 注册工具
- 按 profile / run 过滤可见工具
- 执行工具
- 做审批和审计
- 记录 tool 副产物

### `builtin_tools/`

这层非常重要。

它表达的是：

> runtime 自带的前台基础工具表面。

当前主要有：

- `runtime/builtin_tools/computer.py`
- `runtime/builtin_tools/skills.py`
- `runtime/builtin_tools/subagents.py`

它们负责把 runtime 里的真实能力接成给模型看的工具。

### `plugin_manager.py`

plugin 现在主要表示：

- 外部可选扩展
- hook
- 外部 tool
- 外部 subagent executor

现在不要再把前台基础工具和 plugin 混在一起理解。

## 3. `computer` 子域

关键文件：

- `runtime/computer/runtime.py`
- `runtime/computer/contracts.py`
- `runtime/computer/backends.py`
- `runtime/computer/world.py`
- `runtime/computer/workspace.py`
- `runtime/builtin_tools/computer.py`

这块现在已经很清楚了：

- 前台真正暴露给模型看的 builtin tool 只有：
  - `read`
  - `write`
  - `edit`
  - `bash`
- 模型不会直接看到 `computer` 这个名字
- 真正干活的是 `ComputerRuntime`

`ComputerRuntime` 现在最重要的前台入口是：

- `read_world_path(...)`
- `write_world_path(...)`
- `edit_world_path(...)`
- `bash_world(...)`

它负责的是：

- `/workspace /skills /self` 这套 world 路径
- workspace
- attachments
- 文件读写
- shell
- backend 状态

## 4. `skills` 子域

关键文件：

- `runtime/skills/catalog.py`
- `runtime/skills/package.py`
- `runtime/skills/loader.py`
- `runtime/builtin_tools/skills.py`

请直接以：

- `docs/18-skill.md`

作为目前这块的正式设计基准。

### skill 现在的真实状态

现在真正存在的是这几条线：

1. runtime 会按 `runtime.filesystem.skill_catalog_dirs` 递归扫描每个 skill 根目录里的 `SKILL.md`
2. 相对路径根目录算 `project`, `~` 和绝对路径根目录算 `user`
3. `SkillCatalog` 会先保留全部扫描到的 skill metadata
4. profile 决定这个 agent 理论上能看到哪些 skill
5. 当前 run 里，world 还会再按 `/skills` 可见性过滤一次
6. prompt 注入和 `Skill` 真正读取时，才按可见性和 `project > user` 选出最后那一份 skill
7. 模型会在 system prompt 的 `<system-reminder>` 里看到 skill 摘要
8. 模型可以调用 builtin `Skill(skill=...)` 读取某个 `SKILL.md`
9. 前台 `computer` 也支持沿 `/skills/...` 继续读 skill 包里的文件

如果你要继续改 skill，先看 `docs/18-skill.md`，不要只看眼前代码猜路径规则和工具契约。

## 5. `subagents` 子域

关键文件：

- `runtime/subagents/contracts.py`
- `runtime/subagents/broker.py`
- `runtime/subagents/execution.py`
- `runtime/builtin_tools/subagents.py`

这里负责的是：

- subagent executor 注册
- 委派请求编排
- child run 执行
- frontstage `delegate_subagent` 工具

---

## 记忆和存储

关键文件：

- `runtime/memory/`
- `runtime/storage/`

## working memory

当前 thread 里的短期上下文主要在：

- `ThreadState.working_messages`
- `ThreadState.working_summary`

它是短期上下文，不是长期记忆仓库。

## 长期记忆

关键文件：

- `runtime/memory/memory_broker.py`
- `runtime/memory/structured_memory.py`
- `runtime/memory/retrieval_planner.py`
- `runtime/memory/context_compactor.py`

这条线主要负责：

- retrieval
- extraction
- context compaction
- prompt slots

## 事实存储

现在最重要的几类事实是：

- `ChannelEventRecord`
  - 外部事件事实
- `MessageRecord`
  - 系统真正送达的消息事实
- `MemoryItem`
  - 长期记忆项
- `RunRecord`
  - 一次执行生命周期
- `ThreadState`
  - 当前 thread 的短期状态

---

## 控制面和 WebUI

关键文件：

- `runtime/control/http_api.py`
- `runtime/control/control_plane.py`
- `runtime/control/config_control_plane.py`
- `webui/src/`
- `src/acabot/webui/`

### 后端控制面

#### `RuntimeHttpApiServer`

负责：

- 暴露 `/api/*`
- 可选托管静态 WebUI 构建产物

#### `RuntimeControlPlane`

负责：

- 当前运行时状态
- workspace / sandbox 状态
- tools / skills / subagent executors 快照
- run / thread / memory 等控制面查询

#### `RuntimeConfigControlPlane`

负责：

- 配置真源读写
- profiles
- prompts
- gateway
- runtime plugins
- session-config 驱动的 reload

### 前端源码和构建产物

#### 开发时看哪里

- `webui/src/main.ts`
- `webui/src/router.ts`
- `webui/src/views/`
- `webui/src/components/`
- `webui/src/lib/api.ts`

#### 运行时真正托管哪里

- `src/acabot/webui/`

也就是说：

- 改页面时看 `webui/src/`
- 浏览器里最终看到的是 build 后的 `src/acabot/webui/`

---

## 现在系统里最容易看错的边界

## 1. `SessionConfig` 和 profile 不是一回事

- `SessionConfig` 决定这条消息在当前会话里怎么跑
- profile 决定被选中的 agent 是谁、默认带什么能力

不要再把 profile 当成“消息决策中心”。

## 2. builtin tool 和 plugin 不是一回事

- builtin tool 是 runtime 自带前台能力
- plugin 是外部可选扩展

不要再把 `read / write / edit / bash` 当成 plugin。

## 3. `computer` 和 `builtin_tools/computer.py` 不是同一个层

- `builtin_tools/computer.py` 是给模型看的工具表面
- `runtime/computer/` 才是真正干活的子域

## 4. 想改 skill 先看正式规则

skill 这块现在已经有一条明确主线：

- runtime 扫 skill
- prompt 先给 skill 摘要
- 模型调 `Skill(skill=...)`
- 后续沿 `/skills/...` 继续读

先看：

- `docs/18-skill.md`

再看代码。

## 5. WebUI 不是一个独立前端项目

它的真入口一直是：

- `RuntimeHttpApiServer`
- `RuntimeControlPlane`
- `RuntimeConfigControlPlane`

不要只改前端页面，不看后端控制面和配置真源。

---

## 典型改动应该先看哪里

### 想改消息主线

先看：

- `runtime/app.py`
- `runtime/control/session_runtime.py`
- `runtime/router.py`
- `runtime/pipeline.py`

### 想改前台工具

先看：

- `runtime/builtin_tools/`
- `runtime/tool_broker/`
- `runtime/computer/`

### 想改 skill

先看：

- `docs/18-skill.md`
- `runtime/skills/`
- `runtime/builtin_tools/skills.py`
- `runtime/computer/`

### 想改 WebUI / 控制面

先看：

- `runtime/control/http_api.py`
- `runtime/control/control_plane.py`
- `runtime/control/config_control_plane.py`
- `webui/src/`

### 想改长期记忆

先看：

- `runtime/control/session_runtime.py`
- `runtime/memory/memory_broker.py`
- `runtime/memory/structured_memory.py`
- `runtime/memory/retrieval_planner.py`
- `runtime/pipeline.py`

---

## 什么时候该看 `agent-first/`

只有两种情况：

1. 你发现代码里还没实现某块，而 `agent-first/` 里正好有近期 TODO
2. 你要判断作者最近想把架构往哪推

别把它当实现说明书。

---

## 一句话版本

这项目现在最重要的，不是死记某个文件很大，而是先认清三件事：

1. `SessionRuntime` 先解释消息
2. runtime 自带基础工具现在走 `builtin_tools/`
3. `computer`、skill、subagent、WebUI 都已经各有明确入口，不要再按旧壳理解它们
