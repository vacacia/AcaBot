# AcaBot 给 AI 的入口文档

这份文档是写给新对话里的 Codex 用的。

目标很简单: 先把项目的真结构讲清楚，让 AI 在开始改代码之前，知道自己应该去看哪里，哪些地方不能乱动，哪些地方改一处会连着动很多处。

如果你只打算读一篇，就先读这一篇。读完再按这里给的顺序去看别的文档。

## 先讲结论

AcaBot 真实入口是:

- `src/acabot/main.py`
- `src/acabot/runtime/bootstrap/`
- `src/acabot/runtime/app.py`
- `src/acabot/runtime/pipeline.py`

如果你要改主流程，不要先去翻 `agent-first/`。那个目录更像较早的设计草稿和 TODO 记录，不是现状真相。

## 读文档顺序

建议每次新对话按这个顺序读:

1. `00-ai-entry.md`
2. `01-system-map.md`
3. `02-runtime-mainline.md`
4. 按任务类型再看:
   - 路由 / agent 绑定 / prompt: `04-routing-and-profiles.md`
   - 记忆 / retrieval / compaction: `05-memory-and-context.md`
   - 工具 / plugin / subagent: `06-tools-plugins-and-subagents.md`
   - 平台接入 / NapCat / 事件翻译: `07-gateway-and-channel-layer.md`
   - WebUI / 控制面: `08-webui-and-control-plane.md`
   - workspace / computer / 附件 / shell session: `12-computer.md`
   - 模型 provider / preset / binding / 生效模型解析: `13-model-registry.md`
   - reference / notebook 检索后端: `14-reference-backend.md`
   - 已知问题 / 设计缺口 / 修复后该同步哪些文档: `15-known-issues-and-design-gaps.md`
   - 前后台双 agent / 自我进化方向: `16-front-back-agents-and-self-evolution.md`
   - 配置和部署: `09-config-and-runtime-files.md`、`11-deployment-reference.md`
5. 真要动手前，再看 `10-change-playbooks.md`

## 这套代码里哪些文件最像“总装配图”

- `src/acabot/main.py`
  现在只负责启动和组装，不负责业务主线。
- `src/acabot/runtime/bootstrap/`
  默认 runtime 组件都在这里接起来。
- `src/acabot/runtime/contracts/`
  核心运行时数据对象现在拆在这里。
- `src/acabot/runtime/control/config_control_plane.py`
  WebUI 能改的配置真源和热刷新逻辑大多在这里。

## 一张够用的脑图

外部世界进来时，大致是这条线:

`NapCat -> Gateway -> RuntimeApp -> RuntimeRouter -> ThreadManager / RunManager -> ThreadPipeline -> ModelAgentRuntime -> Outbox -> Gateway`

同时还有几条侧边线:

- `ChannelEventStore` 记录外部事件事实
- `MessageStore` 记录真正送达的消息事实
- `MemoryStore` 存长期记忆
- `ToolBroker` 负责工具可见性、审批、前台到后台 bridge tool 和执行
- `PluginManager` 给主线插 hook / tool / executor
- `ControlPlane + HTTP API + WebUI` 负责本地运维和配置改写

## 这项目最容易看错的地方

### 1. 把 working memory 和长期记忆混在一起

不是一回事:

- `ThreadState.working_messages / working_summary` 是当前线程上下文(就是QQ群的对话流)
- `MemoryStore / MemoryBroker / structured_memory` 是长期记忆
- `MessageStore` 是送达事实，不是上下文草稿
- `ChannelEventStore` 是外部事件事实，不是 assistant 回复事实

### 2. 把 Gateway 当业务层

`gateway/napcat.py` 只该做协议翻译和 API 调用。不要把“该不该回复”“该走哪个 agent”“要不要提取记忆”这种逻辑塞进去。

### 3. 把 WebUI 当成“独立系统”

不是。WebUI 只是 `RuntimeHttpApiServer` 和 `RuntimeControlPlane` 的前端壳。前后端改动通常要一起看。

### 4. 只改前端，不改配置真源

很多页面不是读内存状态，而是读 / 写 runtime config 真源。你只改 `webui/app.js`，往往只改到表面。

### 5. 只改单点，不看调用链

这个项目里很多功能跨层:

- 图片转述会同时碰 `event attachments`、`computer staging`、`model capability`、`tool/plugin`、`prompt assembly`
- 长期记忆会同时碰 `event policy`、`memory broker`、`store`、`retrieval planner`
- WebUI 控制面板会同时碰 `app.js`、`http_api.py`、`control_plane.py`、`config_control_plane.py`

## 改代码前的固定流程

每次都建议按这个顺序来:

1. 先判断改动属于哪一层
   - 协议层
   - runtime 主线
   - 配置与控制面
   - 记忆系统
   - 工具 / plugin / subagent
   - WebUI
2. 找主入口文件，不要上来全文搜索到哪改哪
3. 确认输入和输出契约
   - 这层吃什么对象
   - 往下游吐什么对象
4. 列影响面
   - 配置项
   - 持久化
   - WebUI
   - 模型能力约束
   - 事件 / 消息事实记录
5. 先给变更方案，再开始改

## 改完代码后，不要把文档留在旧状态

以后只要改了代码，而且改动会影响下面任意一类信息，就应该顺手同步 `docs/`：

- 主线流程
- 模块职责
- 数据契约
- 配置项和生效路径
- WebUI / control plane 行为
- tool / plugin / skill / subagent 的接入方式
- 典型改动入口

最少要做两件事:

1. 判断现有文档有没有被改旧
2. 把受影响的文档一起更新

不要把文档当成“最后有空再补”的东西。

这套文档的目标就是让下一次新对话不用再从头读完整代码。如果代码变了、文档不跟，文档很快就会失去价值。

这套文档的定位是:

- 尽量替代“每次都做一遍全仓扫读”
- 让 AI 能快速定位到该看的模块
- 让 AI 不必再盲目通读一堆无关文件

但它不是“永远不用再看源码”的许可证。

如果任务刚好碰到:

- 最近改过但文档还没同步的模块
- 这次文档没有覆盖到的细节实现
- 大文件里的具体边界条件

那还是应该回到对应源码做定点复读。

如果拿不准该改哪篇，先检查:

- `00-ai-entry.md`
- `01-system-map.md`
- `02-runtime-mainline.md`
- 对应专题文档
- `10-change-playbooks.md`

## 改动和文档的对照表

如果你改的是下面这些地方，通常至少要同步这些文档。

### runtime 主线

代码范围:

- `runtime/app.py`
- `runtime/pipeline.py`
- `runtime/bootstrap/`
- `runtime/router.py`

通常要同步:

- `02-runtime-mainline.md`
- `01-system-map.md`
- 需要时 `10-change-playbooks.md`

### 数据契约

代码范围:

- `types/`
- `runtime/contracts/`

通常要同步:

- `03-data-contracts.md`
- 如果影响主线，再看 `02-runtime-mainline.md`

### 记忆系统

代码范围:

- `runtime/memory/memory_broker.py`
- `runtime/memory/structured_memory.py`
- `runtime/memory/context_compactor.py`
- `runtime/memory/retrieval_planner.py`
- `runtime/control/event_policy.py`

通常要同步:

- `05-memory-and-context.md`
- `10-change-playbooks.md`

### tool / plugin / skill / subagent

代码范围:

- `runtime/tool_broker/`
- `runtime/plugin_manager.py`
- `runtime/plugins/`
- `runtime/skills/catalog.py`
- `runtime/subagent_*`

通常要同步:

- `06-tools-plugins-and-subagents.md`
- 如果影响主线，再看 `02-runtime-mainline.md`
- 如果改变典型接入方式，再看 `10-change-playbooks.md`

### gateway / 渠道层

代码范围:

- `gateway/`
- `types/event.py`
- `types/action.py`

通常要同步:

- `07-gateway-and-channel-layer.md`
- `03-data-contracts.md`

### WebUI / control plane

代码范围:

- `runtime/control/http_api.py`
- `runtime/control/control_plane.py`
- `runtime/control/config_control_plane.py`
- `webui/`

通常要同步:

- `08-webui-and-control-plane.md`
- `09-config-and-runtime-files.md`
- 需要时 `10-change-playbooks.md`

### computer

代码范围:

- `runtime/computer/`
- `runtime/plugins/computer_tool_adapter.py`

通常要同步:

- `12-computer.md`
- 如果影响 skill mirror，再看 `06-tools-plugins-and-subagents.md`

### model registry

代码范围:

- `runtime/model/model_registry.py`
- `runtime/model/model_resolution.py`

通常要同步:

- `13-model-registry.md`
- `08-webui-and-control-plane.md`

### reference backend

代码范围:

- `runtime/references/`
- `runtime/plugins/reference_tools.py`

通常要同步:

- `14-reference-backend.md`
- `06-tools-plugins-and-subagents.md`

## 文档不会自动暴露 bug

这套文档默认更偏“结构图”和“入口图”，不是 bug 列表。

所以有两类信息要主动补:

### 1. 已知风险 / 已知缺口

如果你在读代码时发现某个地方:

- 有真实 bug
- 有明显设计缺口
- 当前实现和文档预期不一致

那应该把它写进对应专题文档的“已知风险”或“实现现状”部分。

### 2. 修复后的行为变化

如果某个 bug 修掉之后会改变行为边界，也要改文档，不然下一次 AI 还会按旧行为理解系统。

## 建议你输出给用户的方案格式

在真正改代码前，先给一版很短的方案:

1. 改动目标
2. 主要落点文件
3. 影响面
4. 不改的部分
5. 风险点

这项目不怕改得慢一点，怕的是找错入口之后越改越散。

## 权威来源和非权威来源

优先级从高到低:

1. `src/acabot/**`
2. `runtime-env/**`
3. `docs/**`
4. `agent-first/**`

`agent-first/` 可以拿来找最近的构想和 TODO，但不要把里面的话直接当成当前实现。

## 最后一句

如果你不确定某个能力应该放在哪一层，先回到两个文件:

- `src/acabot/runtime/bootstrap/`
- `src/acabot/runtime/pipeline.py`

大多数“应该接在哪”的问题，看完这两个文件就不会跑偏。
