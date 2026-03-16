# 常见改动的落点手册

这一篇是给 AI 实战用的。

不是讲原理，是讲“你要改这种功能时，先从哪几处下手比较不容易走偏”。

## 先说通用流程

无论改哪类功能，建议先做这四步:

1. 写一句目标
2. 列主落点文件
3. 列会连带影响的层
4. 确认哪些地方暂时不碰

很多失控的改动，都是因为上来就开始 patch，而不是先做这四步。

## 场景一: WebUI 控制面板

这是当前优先级最高的场景。

### 先看哪些文件

- `src/acabot/webui/app.js`
- `src/acabot/runtime/control/http_api.py`
- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/snapshots.py`
- `src/acabot/runtime/control/ui_catalog.py`
- `src/acabot/runtime/control/model_ops.py`
- `src/acabot/runtime/control/workspace_ops.py`
- `src/acabot/runtime/control/reference_ops.py`
- `src/acabot/runtime/control/config_control_plane.py`

### 先判断这块面板在改什么

#### 只读运行时状态

比如:

- 当前连接状态
- active runs
- pending approvals
- thread / memory 查询

这种一般落在 `RuntimeControlPlane`。

#### 持久配置

比如:

- profile
- prompt
- rule
- model preset

这种一般要落在 `RuntimeConfigControlPlane`。

#### 二者混合

很多真正的控制面板都属于这种，需要前后都看。

### 推荐改法

1. 先补后端接口和数据模型
2. 再补前端页面状态管理
3. 最后补导航、提示文案、保存反馈

### 常见坑

- 只改前端，不落盘
- 只落盘，不热刷新
- 接口混了“当前状态”和“配置真源”
- 没写清哪些操作要重启

## 场景二: 图片转述 / VLM 接入

这个需求会跨很多层，别当成“只是加个模型调用”。

### 先看哪些文件

- `src/acabot/types/event.py`
- `src/acabot/gateway/napcat.py`
- `src/acabot/runtime/inbound/message_resolution.py`
- `src/acabot/runtime/inbound/message_projection.py`
- `src/acabot/runtime/inbound/message_preparation.py`
- `src/acabot/runtime/inbound/image_context.py`
- `src/acabot/runtime/pipeline.py`
- `src/acabot/runtime/computer/`
- `src/acabot/runtime/model/model_agent_runtime.py`
- `src/acabot/runtime/model/model_resolution.py`
- `src/acabot/runtime/memory/memory_broker.py`
- `src/acabot/webui/app.js`

### 先回答四个设计问题

1. 图片是自动处理，还是模型按需调用
2. 图片是远程引用直接喂模型，还是先转本地文件
3. 结果是只用于当前轮，还是也要写入记忆
4. 需要新增配置项吗

### 当前项目里的实际落法

现在这块已经不是“待设计”状态，而是走这条混合链:

- `computer` 先把当前消息附件 staging 到本地
- `MessageResolutionService` 负责把当前消息和 reply 里的可用输入拿全
- `MessageProjectionService` 负责把这条消息变成 history 版本、model 版本和 memory 候选材料
- `ImageContextService` 只处理图片说明和 image parts，不再自己决定 reply 拉取或 thread 投影
- 如果当前 run 会回复，而且主模型支持 vision，再把图片本体应用到最后一条 user message
- `reply` 图片当前轮重新取消息、重新拿图，不复用历史 caption
- 会话历史里写的是“原始消息 + 系统补充”，不是把图片说明伪装成原始事实
- 长期记忆模块自己决定怎样消费 memory 候选材料，不是消息整理层直接写死长期记忆文本
- WebUI 的 Profiles / Sessions 都能配置 `image_caption.*`

如果你改的是 bot 事件响应面板, 还要记住一件事:

- WebUI 里的 `message` 默认行为已经不是单行
- 现在会拆成 `消息 @bot`、`消息 引用bot`、`消息 普通群聊`、`消息 其他`
- 这些 UI 行背后对应的就是不同的 inbound rule match 条件

所以如果以后继续改这块，优先看“现有混合链哪里要变”，不要再从零发明另一条路径。

### 常见落法

#### 自动预处理

这就是当前 AcaBot 已经采用的落法。

重点落点:

- event attachments
- `computer` staging
- `ImageContextService`
- pipeline 里的 working memory 投影和当前轮多模态注入

#### 工具化

适合“让模型自己决定要不要看图”。

通常会碰:

- ToolBroker
- plugin tool 注册
- model capability

### 必看的影响面

- `StandardEvent.attachments`
- 当前模型是否支持 vision
- prompt / messages 里怎样表达图片输入
- MessageStore 是否要记录转述文本
- MemoryStore 是否要记录图片摘要
- WebUI / 配置是否要暴露开关

### 最容易出错的地方

- 只改 Gateway，让图片进来了，但主线根本不用
- 只改 prompt，不处理本地附件 / URI 可达性
- 让消息整理层直接决定长期记忆正文，结果只是把 memory policy 挪了个地方
- 把图片说明直接当原始消息写进上下文，后面分不清什么是事实、什么是系统补充
- 忘了不同模型对 vision 输入格式的限制
- 忘了 `record_only` 消息也会影响 working memory，结果群聊图片上下文前后不一致

## 场景三: 长期记忆重构

这类改动不是“换个文案”级别，通常会动结构。

### 先看哪些文件

- `src/acabot/runtime/memory/memory_broker.py`
- `src/acabot/runtime/memory/structured_memory.py`
- `src/acabot/runtime/storage/stores.py`
- `src/acabot/runtime/storage/memory_store.py`
- `src/acabot/runtime/storage/sqlite_stores.py`
- `src/acabot/runtime/control/event_policy.py`
- `src/acabot/runtime/pipeline.py`

### 先确认重构目标

长期记忆重构可能是几种完全不同的事:

- 改写入策略
- 改 retrieval 策略
- 改 scope 设计
- 改存储结构
- 加向量检索
- 加记忆编辑 / 合并 / 置信度策略

不先定清楚，后面很容易“看起来全都要改”。

### 推荐切入顺序

1. 先定 `MemoryItem` 和 retrieval / write request 的契约
2. 再定 scope 和 scope_key 规则
3. 再定 extractor / retriever 策略
4. 最后才改 pipeline 接线

### 最容易出错的地方

- 把 working memory 和长期记忆混起来
- 只管写，不管取
- 只改 extractor，不改 event policy
- 只改内存实现，不改 SQLite / 控制面

## 快速判断“该动哪里”

### 需求像“平台事件长什么样”

先看 `gateway + types`

### 需求像“消息进来系统怎么决定”

先看 `router + profiles + event policy`

### 需求像“这轮 prompt 里该塞什么”

先看 `pipeline + retrieval + memory`

### 需求像“模型可以用什么能力”

先看 `tool broker + plugins + subagents`

### 需求像“用户怎么改配置和查看状态”

先看 `http api + control plane + webui`
