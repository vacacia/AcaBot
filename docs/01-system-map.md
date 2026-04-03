# AcaBot 系统地图

本文件是项目的总装配图，说明系统由哪些模块组成、主线怎么走、各子域的入口在哪里。

## 主线

```
Gateway → RuntimeApp → RuntimeRouter → SessionRuntime → ThreadPipeline → ModelAgentRuntime → Outbox → Gateway
```

**SessionRuntime** 负责"这条消息在当前会话里该怎么解释"，**RuntimeRouter** 把解释结果收成可执行路由，**ThreadPipeline** 负责真正把这次 run 跑完。

侧边线：
- `ToolBroker`：工具可见性、执行和副产物
- `builtin_tools/`：runtime 自带能力（read/write/edit/bash/skills/subagents）接成模型工具
- `PluginManager`：外部扩展 plugin
- `ComputerRuntime`：`/workspace`、`/skills`、`/self` 的文件和 shell 能力
- `MemoryBroker`：统一 /self、sticky notes、长期记忆的检索
- `RuntimeControlPlane + RuntimeHttpApiServer + WebUI`：本地控制面
- `storage/`：事实记录和 thread 状态

## 顶层目录

| 目录 / 文件 | 职责 |
|------------|------|
| `main.py` | 启动入口：读配置、创建 gateway/agent、调 `build_runtime_components()` |
| `config.py` | 配置容器：YAML 读写和路径解析 |
| `types/` | 跨层共享数据对象（`StandardEvent`、`Action`） |
| `gateway/` | 平台协议适配层（NapCat / OneBot v11） |
| `agent/` | 模型调用抽象层（`BaseAgent`、tool 契约、response 契约） |
| `runtime/` | 核心目录：主流程、路由、记忆、工具、控制面、模型解析 |
| `webui/src/` | WebUI 前端源码（开发时看这里） |
| `src/acabot/webui/` | WebUI 构建产物（`RuntimeHttpApiServer` 托管这里） |

## 依赖方向

```
types → gateway / agent → runtime → webui（通过 HTTP API）
```

`types` 只放共享对象不依赖 runtime；`gateway` 依赖 `types`；`runtime` 依赖 `config/types/gateway/agent`；`webui` 只通过 HTTP API 和后端交互，不直接碰 Python 内部状态。

## 启动和装配

**`main.py`** 只创建最外层对象（读配置、创建 gateway/agent、调 bootstrap），不是业务主线。

**`runtime/bootstrap/`** 是真正的装配中心。`build_runtime_components()` 接线所有核心组件：RuntimeRouter、SessionRuntime、ThreadManager、RunManager、ToolBroker、ComputerRuntime、MemoryBroker、ThreadPipeline、RuntimeControlPlane、RuntimeHttpApiServer、PluginManager、Outbox。bootstrap 还负责把 builtin tool 直接注册到 ToolBroker（`builtin:computer`、`builtin:message`、`builtin:skills`、`builtin:subagents`），这条线是主线不是补丁。

**`RuntimeApp`** 是 runtime 总入口：启动 gateway 和 plugin、接住 gateway 上来的 event、做最小入口分流、调 router、创建/获取 thread 和 run、把 `RunContext` 交给 pipeline。

## 消息主线六步

### 1. Gateway 翻译平台消息

`gateway/napcat.py` → `types/event.py`

只做协议层的事：平台事件翻译、segment 归一化、attachment 提取、reply/mention/targets_self 归一化。

### 2. SessionRuntime 解释消息

`runtime/control/session_runtime.py` → `contracts/session_config.py`

整条主线最关键的一层。先把消息收成 `EventFacts`，然后做 session 定位、surface 解析，按六个决策域产出决策：routing、admission、persistence、extraction、context、computer。决定"这条消息怎么跑"的是 **SessionConfig + SessionRuntime**。

### 3. RuntimeRouter 收口路由

`runtime/router.py`

生成稳定 ID（actor_id、conversation_id、thread_id）并把 session runtime 的决策收成 `RouteDecision`。它是把"解释结果"装配成"运行时结果"的薄层。

### 4. ThreadPipeline 执行 run

`runtime/pipeline.py`

完整主线：plugin hook → computer 上下文和附件准备 → 消息输入材料 → 写入 thread working memory → context compaction → retrieval planning → 记忆注入 → 调模型 → 发送动作 → 收尾 run → 触发 memory extraction。

### 5. ModelAgentRuntime 调模型

`runtime/model/model_agent_runtime.py`

读取 prompt、解析当前 run 可见的 tools、通过 ContextAssembler 组装最终上下文、调 `BaseAgent.run()`、把结果转成 runtime 结构。

### 6. Outbox 发消息

`runtime/outbox.py`

决定哪些动作发到平台、哪些属于送达事实、哪些写 `MessageStore`。

## Runtime 子域

### 路由和会话决策

| 文件 | 职责 |
|------|------|
| `runtime/router.py` | 收口路由结果 |
| `runtime/control/session_runtime.py` | 解释消息 |
| `runtime/control/session_loader.py` | 加载 session config |
| `runtime/control/session_bundle_loader.py` | 读取 session.yaml + agent.yaml |
| `runtime/control/session_agent_loader.py` | 加载 session-owned agent |
| `runtime/control/prompt_loader.py` | 读取 prompt |
| `runtime/contracts/session_config.py` | 会话配置契约 |

### 工具和能力表面

**ToolBroker**（`runtime/tool_broker/`）：统一工具入口，负责注册、按 profile/run 过滤可见工具、执行、审批和副产物记录。

**builtin_tools/**：runtime 自带的前台基础工具表面。当前有 `computer.py`（read/write/edit/bash）、`skills.py`（Skill 调用）、`subagents.py`（delegate_subagent），由 bootstrap 直接注册，不经过 plugin。

**PluginManager**（`runtime/plugin_manager.py`）：外部可选扩展，提供 hook 和外部 tool。不要把前台基础工具和 plugin 混在一起。

### Computer

| 文件 | 职责 |
|------|------|
| `runtime/computer/runtime.py` | `ComputerRuntime` 主入口（read/write/edit/bash_world） |
| `runtime/computer/contracts.py` | 契约定义 |
| `runtime/computer/backends.py` | 后端实现（host/docker） |
| `runtime/computer/world.py` | Work World 路径（/workspace、/skills、/self） |
| `runtime/computer/workspace.py` | workspace 和 attachments 管理 |
| `runtime/builtin_tools/computer.py` | 给模型看的工具表面（模型不直接看到 `computer` 这个名字） |

### Skills

runtime 按 `runtime.filesystem.skill_catalog_dirs` 递归扫描 `SKILL.md`，`SkillCatalog` 保留全部 metadata，profile 决定可见性，当前 run 按 `/skills` 可见性过滤，prompt 注入 skill 摘要，模型通过 `Skill(skill=...)` 调用。详见 `docs/18-tool-skill-subagent.md`。

关键文件：`runtime/skills/catalog.py`、`runtime/skills/package.py`、`runtime/skills/loader.py`、`runtime/builtin_tools/skills.py`。

### Subagents

subagent 定义真源是文件系统 `SUBAGENT.md` catalog，session 只负责 `visible_subagents`。关键文件：`runtime/subagents/contracts.py`、`runtime/subagents/broker.py`、`runtime/subagents/execution.py`、`runtime/builtin_tools/subagents.py`。

## 记忆和存储

**Working Memory**：`ThreadState.working_messages / working_summary`，当前 thread 短期上下文。

**长期记忆**：`MemoryBroker` 统一读取三个来源——`SelfFileRetriever`（/self）、`StickyNoteRetriever`（便签）、`LtmMemorySource`（长期记忆）。`RetrievalPlanner` 准备检索现场，`ContextCompactor` 做短期上下文压缩。详见 `05-memory-and-context.md`。

关键文件：`runtime/memory/memory_broker.py`、`runtime/memory/retrieval_planner.py`、`runtime/memory/context_compactor.py`、`runtime/memory/long_term_memory/`、`runtime/memory/long_term_ingestor.py`、`runtime/memory/file_backed/`。

**事实与状态存储**：`ChannelEventRecord`（外部事件事实）、`MessageRecord`（送达消息事实）、`RunRecord`（执行生命周期）、`ThreadState`（thread 短期状态）。

## 控制面和 WebUI

**RuntimeHttpApiServer**（`runtime/control/http_api.py`）：暴露 `/api/*`，可选托管 WebUI 构建产物。

**RuntimeControlPlane**（`runtime/control/control_plane.py`）：运行时状态、workspace/sandbox、tools/skills/subagent 快照、run/thread/memory 查询。

**RuntimeConfigControlPlane**（`runtime/control/config_control_plane.py`）：配置真源读写（profiles、prompts、gateway、runtime plugins、session-config reload）。

前端开发看 `webui/src/`，浏览器里看到的是构建后的 `src/acabot/webui/`。

## 容易看错的边界

1. **SessionConfig ≠ profile**：SessionConfig 决定消息在当前会话里怎么跑，profile 决定被选中的 agent 是谁和默认带什么能力。
2. **builtin tool ≠ plugin**：builtin tool 是 runtime 自带前台能力，plugin 是外部可选扩展。read/write/edit/bash 不是 plugin。
3. **`computer` ≠ `builtin_tools/computer.py`**：前者是真正干活的子域，后者是给模型看的工具表面。
4. **改 skill 先看规则**：先读 `docs/18-tool-skill-subagent.md`，再看代码。
5. **WebUI 不是独立前端项目**：真入口是 RuntimeHttpApiServer + RuntimeControlPlane + RuntimeConfigControlPlane，改页面要同时看后端。

## 典型改动入口

| 想改什么 | 先看 |
|---------|------|
| 消息主线 | `runtime/app.py`、`runtime/control/session_runtime.py`、`runtime/router.py`、`runtime/pipeline.py` |
| 前台工具 | `runtime/builtin_tools/`、`runtime/tool_broker/`、`runtime/computer/` |
| Skill | `docs/18-tool-skill-subagent.md`、`runtime/skills/`、`runtime/builtin_tools/skills.py` |
| WebUI / 控制面 | `runtime/control/http_api.py`、`runtime/control/control_plane.py`、`webui/src/` |
| 长期记忆 | `runtime/memory/memory_broker.py`、`runtime/memory/retrieval_planner.py`、`runtime/memory/long_term_memory/`、`runtime/memory/file_backed/` |
