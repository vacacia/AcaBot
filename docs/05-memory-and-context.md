# working memory、长期记忆和上下文组装

这一块最容易被误解，所以先讲一句最重要的话:

现在系统里至少有四种“看起来都像记忆”的东西，但它们不是一回事。

## 四种东西分别是什么

### 1. `ThreadState.working_messages / working_summary`

这是当前 thread 的工作上下文。

用途:

- 当前轮和最近几轮对话上下文
- compaction 后的有效摘要

不等于长期记忆。

### 2. `MessageStore`

这是“真正发出去并送达”的消息事实。

它像聊天记录事实表，不是拿来直接当 prompt 的工作内存。

### 3. `ChannelEventStore`

这是“外部平台上发生过什么”的事件事实。

用户消息、notice 事件等会走这里。

### 4. `MemoryStore`

这是长期记忆项仓库。

通过 `MemoryBroker` 的 retrieve / extract 跟主线接起来。

## 当前主线里怎么处理上下文

相关文件:

- `runtime/pipeline.py`
- `runtime/memory/context_compactor.py`
- `runtime/memory/retrieval_planner.py`
- `runtime/memory/memory_broker.py`
- `runtime/memory/structured_memory.py`

流程是:

1. 消息整理层先生成 history 版本、model 版本和 memory 候选材料
2. history 版本 append 到 `thread.working_messages`
3. context compactor 对 working memory 做压缩
4. retrieval planner 准备 prompt 组装
5. `MemoryBroker.retrieve()` 拉长期记忆
6. retrieval planner 把 working memory、summary、memory blocks 组到 `ctx.messages`
7. run 结束后 `MemoryBroker.extract_after_run()` 再写长期记忆

## `MemoryBroker` 的真实定位

它只是统一入口，不是高级记忆引擎。

它做的事比较克制:

- 把 `RunContext` 变成 retrieval request
- 把 `RunContext` 变成 write request
- 把消息整理层给出的 memory 候选材料格式化成 write-back 要用的文本
- 调 retriever / extractor

所以长期记忆要重构，第一站通常不是 pipeline，而是 `MemoryBroker` 周边的协议和后端。

## `structured_memory.py` 现在实际提供了什么

现在实现是“最小闭环”，不是完整记忆系统。

有两部分:

- `StoreBackedMemoryRetriever`
  从 `MemoryStore` 按 scope 查记忆，转成 `MemoryBlock`
- `StructuredMemoryExtractor`
  在 run 收尾后，按 event policy hint 写一条最小 episodic memory

这版刻意没做很多高级功能，比如:

- 自动 sticky note 提取
- reference 切片
- 向量检索
- 复杂记忆融合

## 现在代码里到底有哪些“记忆层级”

这里最好分两层看，不然很容易把几个概念混掉。

### 第一层: scope

这是“这条记忆归谁”的层级。

当前代码里正式跑通的主要是这四个:

- `relationship`
- `user`
- `channel`
- `global`

它们大致对应:

- `relationship`
  某个用户在某个会话里的关系记忆。现在默认最常用，也最像“这个人和这个群里的上下文关系”。
- `user`
  跨会话的用户级记忆。
- `channel`
  群级 / 会话级记忆。
- `global`
  整个 bot 共享的全局记忆。

`structured_memory.py` 里已经把这些 scope 的 `scope_key` 规则写死了:

- `relationship -> {actor_id}|{channel_scope}`
- `user -> {actor_id}`
- `channel -> {channel_scope}`
- `global -> global`

### 第二层: memory_type

这是“这条记忆是什么类型”的层级。

当前代码和配置里能看到的主要类型有:

- `episodic`
- `semantic`
- `relationship`
- `sticky_note`
- `reference`
- `task`

这里要特别注意:

`episodic` 在当前实现里主要是 `memory_type`，不是 `scope`。

也就是说，当前系统表达的是:

- 一条记忆属于哪个范围: `scope`
- 这条记忆是什么性质: `memory_type`

而不是“episodic / semantic / user / channel”全都放在一个平级枚举里。

## 你脑子里的那套层级，代码现在落了多少

如果按更直觉的产品语言去说，你预想里的记忆层一般会像这样:

- 本轮 / 工作记忆
- 情节记忆
- 用户记忆
- 会话记忆
- 全局记忆
- 也许还有 sticky note、reference、task 这种特殊层

现在代码里对应关系大概是:

- 本轮 / 工作记忆
  已实现。就是 `ThreadState.working_messages / working_summary`
- 情节记忆
  部分实现。现在主要表现为 `memory_type = episodic`
- 用户记忆
  已有 scope，但默认策略还比较薄
- 会话 / 群记忆
  已有 `channel` scope
- 全局记忆
  已有 `global` scope
- sticky note
  有独立插件和服务，已经不是纯设想
- semantic / reference / task
  代码里已有类型名和部分挂点，但整体还没形成一套很完整的上层体验

换句话说:

不是没有实现，而是“底层桶和标签已经有了，上层那套你想要的清晰记忆分层产品感还没完全做出来”。

## scope 和 scope_key 很重要

长期记忆不是一股脑存进一个桶。

scope_key 的选法直接决定:

- 这条记忆跟谁绑定
- retrieval 时会不会被命中

所以你要做长期记忆重构，别只改 `content` 长什么样，还要先设计 scope 体系。

## retrieval 和 extraction 分别在哪发生

### retrieval

发生在 agent 调用前。

入口:

- `ThreadPipeline._inject_memories()`
- `MemoryBroker.retrieve()`

### extraction

发生在 run 收尾后。

入口:

- `ThreadPipeline._extract_memory_safely()`
- `MemoryBroker.extract_after_run()`

这两段逻辑是分开的。很多改动只盯其中一段，会导致系统行为很怪。

## event policy 里那组 memory_scopes 是干什么的

WebUI 和 event policy 里会看到 `memory_scopes` 这组配置。

它的意思不是“立刻创建这些记忆”，而更像是:

- 这条事件允许往哪些 scope 写
- retrieval 时优先查哪些 scope

也就是说，它更像 hint，不是最终事实表。

当前默认值里常见的是:

- `relationship`
- `user`
- `channel`
- `global`

这也说明当前系统默认更偏“同一事件可以同时参考多个范围的记忆”，而不是严格只选一个层。

## 如果你要做“长期记忆”

建议先决定四件事:

1. 要记什么
2. 写到哪个 scope
3. 什么时候写
4. 什么时候取

然后再决定落点:

- 协议层事件补充: `StandardEvent`
- 是否允许参与提取: `event_policy`
- retrieval / write 协议: `memory_broker`
- 持久化格式: `MemoryItem`
- 具体策略: `structured_memory` 或新实现

### 如果你要把“预想的记忆层级”做得更完整

建议别直接从 UI 或 prompt 文案入手，先把这三件事定清楚:

1. 你想暴露给用户 / AI 的“层级名”是什么
2. 这些层级在底层究竟映射到 `scope`、`memory_type`，还是两者组合
3. 哪些层级只是读法不同，哪些层级真的要不同的写入 / 检索策略

不先定这个，最后很容易出现:

- UI 上写“情节记忆 / 用户记忆 / 群记忆”
- 代码里却是另一套 `scope + memory_type`
- AI 看文档时也会误判哪个层级该改哪里

## 如果你要做“图片转述”

这类需求表面看像多模态，其实也会碰上下文系统。

当前实现已经不是“只在当轮临时注入”。

当前行为是:

1. 当前消息图片会先 staging 到本地
2. 如果配置允许处理 reply，reply 会在当前轮重新取回，reply 图片也会重新落到本地
3. 图片会生成 caption
4. caption 会以“系统补充”的形式追加到 history 版本里，再写入 `ThreadState.working_messages`
5. 如果这条消息最终要进入 `respond` 主线，而且模型支持 vision，当前轮还会额外把图片本体直接发给主模型
6. `MemoryBroker` 不是直接吃“消息整理层给它写死的一段长期记忆文本”，而是自己消费候选材料，决定最终 write-back 的文本长什么样

这意味着:

- 图片描述会进入后续几轮上下文，不再是“一次性用完就没”
- 当前轮既可能看到 caption，也可能同时看到图片本体
- 长期记忆是否真的落盘，仍然由 `event policy + memory extraction` 决定

所以这块现在真正要注意的是:

1. 图片 caption 已经和 working memory 绑定，不再只是 prompt 装饰
2. `record_only` 带图消息也会生成 caption，用来描述群聊里发生了什么
3. 当前轮 vision 直发和长期上下文 caption 是两条并行链
4. 会话历史里写的是“原始消息 + 系统补充”, 不是把 caption 伪装成原始事实

## 现在这块代码的几个现实限制

### 1. 还偏最小实现

很多东西已经接上线了，但抽象层次还不算很厚。改大功能时要准备好补接口，而不是只 patch 业务分支。

### 2. working memory 和 compaction 有并发设计

`pipeline.py` 里有注释说明:

- 同一 thread 的 run 之间允许并行
- compaction 是 snapshot + apply 的模式

所以你如果改 compaction 或 thread 写入方式，要留意并发语义，不然很容易出现线程上下文回写冲突。

### 3. event policy 会影响 memory

不是所有事件都会进长期记忆。很多行为是 event policy 决定的。

## 这块改动时最常见的坏味道

### 1. 把长期记忆直接塞进 `ThreadState`

短期看省事，长期一定乱。

### 2. 在 extractor 里偷偷决定业务策略

提取器更适合做写回，不适合兼做“哪些消息值得记住”的总决策。这个决策更适合前移到 event policy 或明确策略层。

### 3. retrieval 不看模型上下文预算

最终是要进入 prompt 的。别只顾着多拿记忆，不看 compaction 和上下文窗口。

## 读源码顺序建议

1. `src/acabot/runtime/pipeline.py`
2. `src/acabot/runtime/memory/memory_broker.py`
3. `src/acabot/runtime/memory/structured_memory.py`
4. `src/acabot/runtime/memory/retrieval_planner.py`
5. `src/acabot/runtime/memory/context_compactor.py`
6. `src/acabot/runtime/control/event_policy.py`
