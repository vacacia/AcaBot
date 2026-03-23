
## Relationship Memory

### 设计理念 / 构想

这层如果按最终目标去理解，负责的应该是：

- Aca 和某个用户之间长期形成的关系
- 和这个人互动时应该记住的长期事实
- 只属于“我和这个对象”的连续性材料

它不是 thread 里的短期上下文，也不是某个群共享的背景。

### 当前代码现状

这层在当前代码里已经**有 scope**，但还没有成为一个独立、完整的产品模块。

#### 1. `relationship` 已经是正式 scope

相关代码在：

- `src/acabot/runtime/memory/structured_memory.py`
- `src/acabot/runtime/memory/memory_broker.py`
- `src/acabot/runtime/memory/retrieval_planner.py`

当前 structured memory 已经正式支持 `relationship` scope，scope key 规则是：

- `actor_id|channel_scope`

这说明当前代码已经把 relationship 当成“某个人在某个会话环境下的长期归属空间”。

#### 2. 当前它主要存在于通用长期记忆基础设施里

现在和 relationship memory 直接相关的基础设施有：

- `MemoryStore`
- `MemoryBroker`
- `StoreBackedMemoryRetriever`
- `StructuredMemoryExtractor`

但这些层目前提供的主要是：

- scope 路由
- memory item 存取
- 最小 retrieval
- 最小 extraction

它们还没有长出 relationship memory 自己的专用结构，比如：

- 独立的数据模型
- 独立的提取规则
- 独立的展示页
- 独立的合并策略

#### 3. 当前会写进去的内容还是最小 episodic memory

`StructuredMemoryExtractor` 现在会在 run 收尾后写入一条最小 `episodic` 记忆。

代码在：

- `src/acabot/runtime/memory/structured_memory.py`

它会根据 hint 选一个 scope，默认很容易落到 `relationship`。但写进去的内容仍然只是最小事件摘要，不是“关系记忆专用格式”。

#### 4. sticky note 的默认 scope 也偏向 relationship

`StickyNotesService` 和 `StickyNotesPlugin` 当前默认 scope 都是 `relationship`。

这说明当前代码倾向于把“和某个人有关的稳定笔记”优先放到 relationship 语义里，但这套语义还没有和产品层彻底对齐。

所以这层的真实现状可以概括成一句话：

> relationship memory 在代码里已经是正式 scope，也是很多默认长期写入的第一落点，但它现在更像通用 `MemoryStore` 上的一种归属方式，还不是独立成型的关系记忆模块。

## Channel Memory

### 设计理念 / 构想

按 `docs/00-ai-entry.md` 的分层，channel memory 表示和某个群体有关的长期记忆方向。

这层应该负责的内容更像：

- 这个群的风格
- 这个群长期在聊什么
- 群内稳定规则
- 群里约定俗成的表达方式

它强调的是“群体共享背景”，不是“我和某个人的关系”。

### 当前代码现状

这层和 relationship memory 一样，也已经有 scope，但真正有产品形状的部分主要还是 sticky note。

#### 1. `channel` 已经是正式 scope

相关代码在：

- `src/acabot/runtime/memory/structured_memory.py`
- `src/acabot/runtime/memory/memory_broker.py`

当前 structured memory 已经正式支持 `channel` scope，scope key 直接使用：

- `channel_scope`

#### 2. 当前最像 channel memory 的，是 channel sticky notes

代码在：

- `src/acabot/runtime/memory/file_backed/sticky_notes.py`
- `webui/src/views/MemoryView.vue`
- `src/acabot/runtime/pipeline.py`

现在 WebUI Memory 页里，最直接可管理的群体长期记忆就是：

- `channel` scope 下的 sticky notes

这和 `00` 里举的例子其实已经很接近了，比如：

- 群主是谁
- 群风格是什么
- 群里有什么黑话

#### 3. 通用长期记忆也支持 channel scope

`MemoryBroker.retrieve(...)` 和 `StructuredMemoryExtractor` 也都能读写 `channel` scope 下的长期记忆项。

但和 relationship memory 一样，这里当前仍然是“通用记忆项 + 通用检索写回”，还没有做出 channel memory 专用模块。

所以这层的真实现状可以概括成一句话：

> channel memory 已经有正式 scope，产品上最成型的部分是 channel sticky notes；除此之外，通用长期记忆也能落到 channel，但还没有独立的 channel memory 产品层。

## Thread Working Memory

### 设计理念 / 构想

按 `docs/00-ai-entry.md` 的定义，thread working memory 是最近几轮对话的短期上下文。

这一层负责的是：

- 当前线程里最近发生了什么
- 当前轮回复需要带上的近场上下文
- 超出预算时如何压缩历史

这一层本质上服务“正在进行的对话现场”，不是长期记忆仓库。

### 当前代码现状

这是当前记忆系统里落地最完整、边界也最清楚的一层。

#### 1. 运行时状态已经稳定

代码在：

- `src/acabot/runtime/contracts/records.py`
- `src/acabot/runtime/storage/threads.py`

当前 thread working memory 的核心字段就是：

- `ThreadState.working_messages`
- `ThreadState.working_summary`

`ThreadManager` 负责：

- 获取 thread
- 创建 thread
- 保存 thread
- 列出 thread

#### 2. 用户消息和 assistant 消息都会回写到 thread

代码在：

- `src/acabot/runtime/pipeline.py`

当前主线行为是：

- 进入 run 时，把当前轮用户内容写入 `working_messages`
- 回复真正送达后，再把 assistant 内容写回 `working_messages`

所以 thread 里保存的是“当前对话现场的模型可消费版本”，不是平台原始消息日志。

#### 3. context compaction 已经接上主线

代码在：

- `src/acabot/runtime/memory/context_compactor.py`
- `src/acabot/runtime/pipeline.py`

当前 compaction 会：

- 对 thread 做 snapshot
- 在预算内压缩上下文
- 生成 `effective_working_summary`
- 生成 `effective_compacted_messages`
- 必要时把结果 apply 回 thread

而且 pipeline 已经明确处理了并发 run 下的 snapshot / apply 语义。

#### 4. RetrievalPlanner 会把它装配回 prompt

代码在：

- `src/acabot/runtime/memory/retrieval_planner.py`

当前 thread working memory 在 prompt 里的入口包括：

- compaction 后保留下来的 history messages
- `thread_summary` prompt slot

所以这一层已经不是“只是存一下消息”，而是完整参与了主线的上下文装配。

所以这层的真实现状可以概括成一句话：

> thread working memory 已经是当前最完整、最接近生产形态的记忆层，短期上下文、压缩、回写和 prompt 装配都已经串起来了。

## Event / Message Facts

### 设计理念 / 构想

按 `docs/00-ai-entry.md` 的定义，event / message facts 负责记录真实发生过什么和真实发送过什么。

这一层的重点是“客观事实”，不是“给模型看的上下文草稿”。

可以直接拆成两半理解：

- event facts：外部平台真实发生过什么
- message facts：系统真实送达过什么

`00` 里也明确提到，后续可以在 WebUI 里给这层做专门查询页。

### 当前代码现状

这层在当前代码里已经拆成两个独立存储面，而且边界是清楚的。

#### 1. 事件事实：`ChannelEventStore`

相关代码在：

- `src/acabot/runtime/contracts/records.py`
- `src/acabot/runtime/storage/stores.py`
- `src/acabot/runtime/storage/event_store.py`

当前 `ChannelEventStore` 负责保存：

- thread_id
- actor_id
- channel_scope
- event_type
- 原始 payload
- 时间戳

它表达的是“平台侧真的发生过什么”。

#### 2. 消息事实：`MessageStore`

相关代码在：

- `src/acabot/runtime/contracts/records.py`
- `src/acabot/runtime/storage/stores.py`
- `src/acabot/runtime/storage/memory_store.py`

当前 `MessageStore` 负责保存：

- thread_id
- role
- content_text
- 平台消息信息
- 时间戳

它表达的是“系统真的发出去并送达了什么”。

#### 3. 控制面已经能按 thread 查询这两类事实

代码在：

- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/http_api.py`

现在已经有对应接口：

- `GET /api/runtime/threads/<thread_id>/events`
- `GET /api/runtime/threads/<thread_id>/messages`

所以这一层已经不是隐藏在 runtime 里的内部数据，它已经是控制面可见对象。

#### 4. 这层当前不直接等于 prompt 上下文

这两类事实虽然很重要，但当前不会直接替代：

- `ThreadState.working_messages`
- `working_summary`

也就是说，事实层和上下文层在当前代码里是分开的，这一点和 `00` 的方向是一致的。

所以这层的真实现状可以概括成一句话：

> event facts 和 message facts 已经有独立存储和控制面查询入口，边界也比较干净；它们现在是事实层，不是主 prompt 的直接上下文层。
