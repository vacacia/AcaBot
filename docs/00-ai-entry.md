# AI 入口文档

本文件是 AI agent 开始工作前的第一份阅读材料。它覆盖项目约定、全局命名契约、核心组件定义和文档维护规则。

## 文档体系

核心文档编号 00-14 和 18-29，commit 前要同步更新受影响的文档。当前进展写在 `docs/HANDOFF.md` 里。

| 主题 | 文档 |
|------|------|
| 路由 / agent 绑定 / prompt | `04-routing-and-profiles.md` |
| 记忆 / retrieval / compaction | `05-memory-and-context.md` |
| 工具 / skill / subagent | `18-tool-skill-subagent.md` |
| run 机制 | `21-run-mechanism.md` |
| 私聊 foreground worker | `26-foreground-worker.md` |
| 平台接入 / NapCat / 事件翻译 | `07-gateway-and-channel-layer.md` |
| WebUI / 控制面 | `08-webui-and-control-plane.md` |
| workspace / computer / 附件 / shell | `12-computer.md` |
| 模型 provider / preset / binding | `13-model-registry.md` |
| reference 检索后端（待删除） | `14-reference-backend.md` |
| 前后台双 agent / 自我进化 | `16-front-back-agents-and-self-evolution.md` |
| 配置和部署 | `09-config-and-runtime-files.md`、`deploy/README.md` |
| session config / session-owned agent | `23-session-config-and-rule-refactor.md`、`27-session-owned-agent.md` |
| 子系统详细实现 | `docs/wiki/`（computer、sticky-notes、long-term-memory、skill、subagent） |
| LTM 实现设计 | `docs/LTM/` |

---

## 项目约定

- 现有审计层可以删除，不要为保留审计发明中间抽象或兼容层。
- 默认 yolo。
- 文档和注释只写"现在在做什么"，不写"不要怎么做"。设计文档直接写最终形态、物理目录约定、逻辑路径约定、工具面和关键组件职责。

---

## 全局命名契约

runtime、memory、tool、WebUI、control plane 统一使用以下命名。同一个东西只保留一个主名字。

### 正式词典

| 名称 | 语义 | 示例 |
|------|------|------|
| `actor_id` | 当前消息的发言人 | `qq:user:12345` |
| `conversation_id` | 消息发生的对话容器（收束旧 `channel_scope`） | `qq:group:67890` |
| `thread_id` | runtime 内部执行线程（运行时对象，不是平台对象） | `thread:front:qq:group:67890` |
| `session_id` | 命中的 session config（配置对象，不是聊天容器） | `session:qq:group:67890:default` |
| `entity_ref` | 被引用的实体对象（sticky note / retrieval target / WebUI / bot 工具统一用它） | `qq:user:12345`、`qq:group:67890` |

### 派生分类

`entity_kind` 只用于 UI 分组和人类阅读辅助，必须从 `entity_ref` 派生，不是并列传递的主字段：
- 指向"人"→ `user`
- 指向"群/频道/房间/私聊容器"→ `conversation`

无法稳定派生的 `entity_ref` 是无效对象，应在边界直接拒绝。`entity_ref` 的合法性校验和 `entity_kind` 的派生必须复用同一个共享解析 helper。

旧的 `scope`、`scope_key`、`channel_scope` 在修改代码时顺手收束到正式命名，不保留双轨表达。

### 合法字符

`entity_ref` 允许：字母、数字、`:`、`-`、`_`、`.`、`@`、`!`。路径分隔符和 `..` 一律拒绝。

### 固定案例

群聊里张三发消息：
```
actor_id          = qq:user:12345
conversation_id   = qq:group:67890
thread_id         = thread:front:qq:group:67890
session_id        = session:qq:group:67890:default
sticky note targets:
  发言人 note     → entity_ref = qq:user:12345
  对话容器 note   → entity_ref = qq:group:67890
```

Bot 想主动查看李四的便签：`actor_id` 仍然是当前发言人 A，李四只能用 `entity_ref = qq:user:22222`，不能把李四也叫 `actor_id`。

`session_id` 和 `conversation_id` 在某些场景下值相同，但语义永远不同。

---

## 核心组件定义

### run

一个 conversation 里每次调用 LLM 都是一次 run。每次取上下文 snapshot（system prompt + working memory snapshot + 新消息 + 记忆注入），run 的所有工具调用、子代理和 skill 内容都不进入 working memory，只附加 LLM 最终回复，保持上下文干净，实现并行处理而不污染。

### tool

给 LLM 调用的 JSON tools 中的工具。tool 只定义名字、描述、参数、返回值和执行入口，不决定可见性和准入——这些由 ToolBroker、agent 配置和 world policy 决定。core tool 属于 runtime 自带，plugin 也可以提供 tool，但两者不是一回事。

### plugin

runtime 暴露给外部的可选扩展包。典型应用：链接解析（hook 阻断 LLM 回复，直接解析视频并发送）、日报分析（定时查数据库）、天气查询（提供 tool）。plugin 可以提供 tool，但 tool ≠ plugin。plugin 不注册 subagent（subagent 真源是文件系统 `SUBAGENT.md` catalog）。判断标准：卸掉它后系统只少一项扩展能力，不该把 `read/write/edit/bash` 这类基础能力一起卸掉。

### computer

前台文件工具和 shell 工具的底层实现。模型不直接看到 `computer` 这个名字，系统启动时把它拆成四个 builtin tool 注册到 ToolBroker：`read`、`write`、`edit`、`bash`。computer 负责按 Work World 路径读写文件、在当前 world 里执行 bash、维护 thread 级 workspace 和附件。哪些路径可用、world 能不能看到 `/workspace`、`/skills`、`/self`、命令在宿主机还是 docker 里跑，都由上层定好再交给 computer 执行。不通过 plugin 实现，因为这是基础能力。

### skill

前台正式入口：prompt 里的 skill 摘要提醒 → builtin `Skill(skill=...)` → 后续沿 `/skills/...` 读 skill 包里的文件。详见 `docs/18-tool-skill-subagent.md`。

### 记忆

五个层次。前两个是消息事实（不是记忆），后三个才是真正的记忆系统。

**thread working memory**：当前 thread 的短期上下文（`ThreadState.working_messages / working_summary`），服务于当前轮上下文压缩和 retained history，不是长期记忆。

**event / message facts**：`ChannelEventStore` 记录平台上真实发生过什么，`MessageStore` 记录系统真正送达了什么。它们是客观事实记录，不是给模型拼 prompt 的草稿，但为长期记忆的写入线提供原始数据。

**`/self`**：Aca 的自我连续性空间。记录 Aca 这一天经历了什么、正在和谁互动、有哪些持续中的状态。Aca 虽然有 prompt 有 sticky note 有长期记忆，但没有一个地方让 Aca 记录自己在这一刻、这一天正在干什么——`/self` 就是用来保持行动连贯性的。它不是人格设定（人格在配置 prompt 里），不是人物/群聊资料（那些放 sticky note），不是杂项长期记忆。由 Aca 在自己的 computer 里通过工具维护，结构是 `today.md` + `daily/*.md`。存储在 `runtime_data/soul/`。

**sticky notes**：零碎但长期有用的实体级笔记——群主是谁、群风格是什么、群里有哪些黑话、某个用户的生日和重大经历。围绕 `entity_ref` 建模，只有 `user` 和 `conversation` 两种实体。每张便签分两区：`readonly`（人工编写，百分百真源，bot 不能改）和 `editable`（bot 可以追加观察）。两区都注入上下文，几乎每轮都会命中。存储在 `runtime_data/sticky_notes/`。

**长期记忆**：从完整对话事实中提炼的结构化经验库（Core SimpleMem + LanceDB）。写入线 fact-driven（事实落盘后 `mark_dirty`），检索线 run-driven（三路召回 + reranking）。存储在 `runtime_data/long_term_memory/`。

上下文组装链路：`RetrievalPlanner`（整理检索现场）→ `MemoryBroker`（统一读取 /self、sticky notes、长期记忆）→ `ContextAssembler`（组装最终 system_prompt + messages）。`ctx.system_prompt` / `ctx.messages` 只表示最终结果，不表示中间态。

详见 `05-memory-and-context.md`。

### WebUI

WebUI 中每个记忆层级有独立管理页面，允许编辑的记忆可以在 WebUI 编辑。WebUI 不是独立系统，只是 `RuntimeHttpApiServer` + `RuntimeControlPlane` 的前端壳。

---

## 项目结构

### 总装配图

```
src/acabot/main.py                     # 启动和组装
src/acabot/runtime/bootstrap/          # runtime 组件接线
src/acabot/runtime/contracts/          # 核心运行时数据对象
src/acabot/runtime/control/            # 控制面（HTTP API、config、session runtime）
```

### 主线

```
NapCat → Gateway → RuntimeApp → SessionRuntime → RuntimeRouter
    → ThreadManager / RunManager → ThreadPipeline → ModelAgentRuntime → Outbox → Gateway
```

侧边线：
- `ChannelEventStore`：记录外部事件事实
- `MessageStore`：记录送达的消息事实
- `MemoryBroker`：统一 /self、sticky notes、长期记忆的检索
- `ToolBroker`：工具可见性、审批和执行
- `PluginManager`：给主线插 hook / tool
- `ControlPlane + HTTP API + WebUI`：本地运维和配置

### 容易看错的地方

1. **working memory ≠ 长期记忆**：`ThreadState.working_messages` 是当前线程上下文，长期记忆走 `MemoryBroker`，`MessageStore` 是送达事实不是上下文草稿。
2. **Gateway 不是业务层**：`gateway/napcat.py` 只做协议翻译和 API 调用，不做"该不该回复"之类的决策。
3. **WebUI 不是独立系统**：前后端改动通常要一起看。
4. **只改前端不改配置真源**：很多页面读写的是 `runtime_config/` 下的文件，不是内存状态。
5. **跨层改动要看调用链**：图片转述碰 event attachments + computer staging + model capability + tool + prompt assembly；长期记忆碰 session config + memory broker + store + retrieval planner。

---

## 改完代码后同步文档

只要改动影响主线流程、模块职责、数据契约、配置项、WebUI 行为或 tool/plugin/skill/subagent 接入方式，就必须同步 docs/。

### 代码 → 文档对照表

| 代码范围 | 要同步的文档 |
|---------|-------------|
| `runtime/app.py`、`runtime/pipeline.py`、`runtime/bootstrap/`、`runtime/router.py` | `02-runtime-mainline.md`、`01-system-map.md` |
| `types/`、`runtime/contracts/` | `03-data-contracts.md` |
| `runtime/memory/` | `05-memory-and-context.md` |
| `runtime/tool_broker/`、`runtime/plugin_manager.py`、`runtime/skills/`、`runtime/subagents/` | `18-tool-skill-subagent.md` |
| `gateway/`、`types/event.py`、`types/action.py` | `07-gateway-and-channel-layer.md`、`03-data-contracts.md` |
| `runtime/control/`、`webui/` | `08-webui-and-control-plane.md`、`09-config-and-runtime-files.md` |
| `runtime/computer/`、`runtime/builtin_tools/` | `12-computer.md` |
| `runtime/model/` | `13-model-registry.md` |
| `runtime/references/` | `14-reference-backend.md` |

### 改代码前的固定流程

1. 判断改动属于哪一层（协议 / runtime 主线 / 配置控制面 / 记忆 / 工具 / WebUI）
2. 找主入口文件，不要全文搜索到哪改哪
3. 确认输入输出契约（这层吃什么对象、吐什么对象）
4. 列影响面（配置项、持久化、WebUI、模型能力、事件/消息记录）
5. 先给变更方案，再开始改
