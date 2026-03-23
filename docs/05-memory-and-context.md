# working memory、长期记忆和上下文组装

这一篇只讲两件事：

1. 现在系统里哪些东西看起来像“记忆”或“上下文”
2. 一条消息进来后，这些东西到底按什么顺序进入主线

如果你没先把这两件事分清楚，后面很容易把：

- thread working memory
- sticky note
- `/self`
- soul 文本
- 长期记忆
- 事件事实 / 消息事实

这些东西写混。

---

## 先讲结论

现在最容易记住的一句话是：

> **thread 负责短期上下文，memory store 负责长期记忆，sticky notes 和 soul 是额外稳定材料，event/message facts 负责记录真实发生过什么。**

也就是说，系统里现在至少有这几层：

1. `ThreadState.working_messages / working_summary`
2. `ChannelEventStore`
3. `MessageStore`
4. `MemoryStore`
5. file-backed sticky notes
6. soul / `/self` 相关材料

它们不是同一个东西。

---

## 一、现在有哪些“像记忆”的东西

## 1. `ThreadState.working_messages / working_summary`

这是当前 thread 的工作上下文。

它表达的是：

- 最近几轮对话
- 当前 thread 的压缩摘要

它的代码位置主要在：

- `src/acabot/runtime/contracts/records.py`
- `src/acabot/runtime/storage/threads.py`
- `src/acabot/runtime/pipeline.py`

### 它用来干什么

- 当前轮 agent 调用前的基础上下文
- context compaction 的输入
- retrieval planner 的输入
- 回复发送后，把 assistant 内容写回 thread

### 它不是什么

它不是：

- 长期记忆仓库
- 聊天记录事实表
- 平台事件事实表

---

## 2. `ChannelEventStore`

这是外部平台事件事实。

它表达的是：

> **平台上真的发生过什么。**

例如：

- 用户发来一条消息
- 某个 notice 事件发生了

它不是 assistant 回复事实，也不是短期上下文本体。

---

## 3. `MessageStore`

这是消息送达事实。

它表达的是：

> **系统真的发出去并成功送达了什么。**

它更像消息事实记录，不是直接给模型拼 prompt 的 working memory。

---

## 4. `MemoryStore`

这是长期记忆项仓库。

它表达的是：

> **一批可以被 retrieval 和 extraction 使用的持久化记忆项。**

它通过：

- `MemoryBroker.retrieve(...)`
- `MemoryBroker.extract_after_run(...)`

和主线接起来。

---

## 5. file-backed sticky notes

这是当前代码里已经正式存在的一类稳定记忆材料。

它的特点是：

- 现在更偏产品层和 WebUI 能直接看见的记忆形态
- 当前主要挂在：
  - `user`
  - `channel`
  这两个 scope 上
- pipeline 会直接从文件里读它们，再转成 `MemoryBlock`

对应代码主要在：

- `src/acabot/runtime/pipeline.py`
- `src/acabot/runtime/memory/retrieval_planner.py`
- `src/acabot/runtime/memory/file_backed/`

### 它和普通 `MemoryStore` 的关系

它们都能变成注入 prompt 的材料，
但 sticky notes 现在有一条很明确的 file-backed 路径，不完全等同于一般的长期记忆项。

---

## 6. soul 和 `/self`

这块最容易写混，所以单独讲清楚。

### `/self`

`/self` 是前台 bot 在 Work World 里的一块持久目录。

它在 computer 这条线上，表达的是：

- bot 自己可见、可写的一块文件区
- 不跟 thread 一起删
- subagent 看不到它

这块更偏：

- 前台 bot 自己维护的文件空间

### soul

当前 runtime 里还有一条单独的 soul 线：

- `src/acabot/runtime/soul/source.py`

`SoulSource` 会维护一组固定文件，比如：

- `identity.md`
- `soul.md`
- `state.yaml`
- `task.md`

然后把它们拼成稳定文本，在 pipeline 里放进：

- `ctx.metadata["soul_prompt_text"]`

最后再由 retrieval planner 注入 prompt。

### 它们的关系

可以先这样理解：

- `/self` 是前台 world 里的文件空间
- soul 是当前已经接入 prompt 的一条固定文本材料线

它们都和 bot 自己有关，但不是同一个接口。

---

## 二、当前主线里，上下文是怎么组起来的

相关代码主要在：

- `src/acabot/runtime/pipeline.py`
- `src/acabot/runtime/inbound/message_preparation.py`
- `src/acabot/runtime/inbound/message_projection.py`
- `src/acabot/runtime/memory/context_compactor.py`
- `src/acabot/runtime/memory/retrieval_planner.py`
- `src/acabot/runtime/memory/memory_broker.py`
- `src/acabot/runtime/memory/structured_memory.py`

当前大致顺序是：

1. `computer_runtime.prepare_run_context(ctx)`
2. `message_preparation_service.prepare(ctx)`
3. 把 history 版本写进 `thread.working_messages`
4. 如果是 `record_only`，提前收尾
5. context compaction 生成有效 summary 和保留消息
6. `pipeline._prepare_static_context(ctx)` 准备 soul 文本
7. `RetrievalPlanner.prepare(ctx)` 生成 retrieval plan
8. `MemoryBroker.retrieve(ctx)` 取长期记忆
9. pipeline 再从文件里收集 sticky notes
10. `RetrievalPlanner.assemble(...)` 把 summary、sticky notes、computer state、retrieved memory 组到 `ctx.messages`
11. `message_preparation_service.apply_model_message(ctx)` 把当前轮最终给模型看的 user message 应用上去
12. 调 agent
13. 发送动作
14. 更新 thread working memory
15. `MemoryBroker.extract_after_run(ctx)` 在 run 收尾后写长期记忆

### 这里最重要的一点

现在上下文不是“直接把 thread 最近几轮拿给模型”这么简单。

真正给模型看的消息，是多层材料一起拼出来的：

- compaction 后的 thread 内容
- soul 文本
- sticky notes
- retrieved memory
- computer state
- 当前轮整理后的 model message

---

## 三、消息整理层现在做什么

当前消息整理入口在：

- `src/acabot/runtime/inbound/message_preparation.py`

它内部拆成两步：

1. 把消息材料拿全
2. 按不同用途生成不同版本

### `MessagePreparationService.prepare(ctx)`

如果当前 profile 开了图片整理，它会继续做：

- 解析当前消息和 reply 材料
- 处理图片
- 生成 caption
- 生成 history 版本、model 版本和 memory 候选材料

### `MessageProjectionService`

它会把同一条消息拆成几种版本：

- `history_text`
  - 用来写进 thread working memory
- `model_content`
  - 用来作为当前轮最后那条 user message 的真正内容
- `memory_candidates`
  - 给长期记忆写回时参考

### 这意味着什么

如果你在改：

- 图片 caption
- reply 展开
- history 里写什么
- 当前轮真正给模型的内容长什么样

先看消息整理层，不要只改 pipeline 末端。

---

## 四、context compaction 现在做什么

当前代码在：

- `src/acabot/runtime/memory/context_compactor.py`

它负责：

- 在上下文预算内压缩 thread working memory
- 尽量保留最近完整轮次
- 必要时生成或更新 working summary

compaction 之后，pipeline 会把这些结果先放进 `ctx.metadata`：

- `effective_working_summary`
- `effective_compacted_messages`
- `effective_dropped_messages`

后面的 retrieval planner 和 memory broker 都会吃这些字段。

### 这一步的意义

它不是长期记忆，也不是普通摘要工具。

它的目标是：

> **在当前 run 开始前，把短期上下文压到模型还能吃下的大小。**

---

## 五、RetrievalPlanner 现在做什么

当前代码在：

- `src/acabot/runtime/memory/retrieval_planner.py`

它做两件事：

### 1. `prepare(ctx)`

计算当前 run 需要的 retrieval plan。

主要会得到：

- `requested_scopes`
- `requested_memory_types`
- `requested_tags`
- `sticky_note_scopes`
- `compressed_messages`
- `dropped_messages`
- `metadata`

### 2. `assemble(ctx, memory_blocks=...)`

把各类材料真正组装成最终 `ctx.messages`。

当前会组进去的主要东西有：

- context slots
- soul 文本
- sticky notes
- computer state
- thread summary
- retrieved memory
- compaction 后保留的消息

### 这里一个很关键的当前事实

sticky notes、thread summary、computer state 现在不是散落在各处随便拼接的，
而是通过 `PromptSlot` 这条线统一进 prompt 的。

---

## 六、MemoryBroker 现在的真实定位

当前代码在：

- `src/acabot/runtime/memory/memory_broker.py`

它不是一个“大而全的记忆大脑”，它现在更像统一入口。

它主要负责：

- 把 `RunContext` 转成 `MemoryRetrievalRequest`
- 把 `RunContext` 转成 `MemoryWriteRequest`
- 调 retriever / extractor
- 把结果规范成 `MemoryBlock`

### retrieval 入口

- `MemoryBroker.retrieve(ctx)`

### extraction 入口

- `MemoryBroker.extract_after_run(ctx)`

### 现在 retrieval 和 extraction 的输入来源

当前主线里，memory broker 主要会参考：

- `ctx.retrieval_plan`
- `ctx.context_decision`
- `ctx.extraction_decision`
- `ctx.thread`
- `ctx.delivery_report`
- `ctx.message_projection`
- `ctx.run`

也就是说，现在“要不要提取长期记忆”“往哪些 scope 写”“检索 tags 是什么”，都已经是 `SessionRuntime` 决策链的一部分了，不是旧的 `event policy` 主线了。

---

## 七、structured memory 现在真的做到了哪里

当前代码在：

- `src/acabot/runtime/memory/structured_memory.py`

它现在是一套**最小闭环**，不是完整记忆系统。

### `StoreBackedMemoryRetriever`

负责：

- 按 scope 和 memory_type 从 `MemoryStore` 取记忆项
- 转成 `MemoryBlock`

### `StructuredMemoryExtractor`

负责：

- 在 run 收尾后
- 按当前请求里的 scope hint
- 写入一条最小的 `episodic` 记忆

### 当前故意没做的事

这层现在还没真正做出完整产品体验的功能，比如：

- sticky note 自动提取
- reference 文档切片
- task scratchpad
- 向量检索
- 复杂记忆融合

所以如果你要做长期记忆大改，不要假设这里已经有很厚的一层抽象。

---

## 八、当前有哪些长期记忆 scope 和 memory_type

## 1. scope

scope 表达的是：

> **这条记忆归谁。**

当前正式跑通的主要是：

- `relationship`
- `user`
- `channel`
- `global`

对应的 key 规则现在写在 `structured_memory.py` 里：

- `relationship -> {actor_id}|{channel_scope}`
- `user -> {actor_id}`
- `channel -> {channel_scope}`
- `global -> global`

## 2. memory_type

memory_type 表达的是：

> **这条记忆是什么性质。**

当前代码里能看到的主要类型有：

- `sticky_note`
- `semantic`
- `relationship`
- `episodic`
- `reference`
- `task`

### 这里最容易搞混的一点

`episodic` 现在主要是 `memory_type`，不是 scope。

也就是说，当前系统表达的是：

- scope 决定“归谁”
- memory_type 决定“是什么类型”

---

## 九、sticky note、长期记忆、working memory 三者的区别

这是最值得专门记住的一组区别。

### working memory

- 在 `ThreadState`
- 偏当前对话现场
- 主要服务当前和最近几轮

### sticky note

- 现在有独立的 file-backed 路径
- 偏稳定事实、长期规则、零碎但有用的笔记
- 当前主要按 `user` 和 `channel` 注入

### 普通长期记忆

- 在 `MemoryStore`
- 通过 `MemoryBroker` 检索和写回
- 当前 retrieval / extraction 仍是最小实现

---

## 十、图片和上下文现在是什么关系

这块表面像多模态，其实已经深度进了上下文主线。

当前行为大致是：

1. 图片先通过 `computer` 做 staging
2. 消息整理层生成 caption
3. caption 会进入 history 版本
4. history 版本会写进 `thread.working_messages`
5. 如果当前轮是 `respond`，而且模型支持 vision，模型还会同时看到图片本体
6. memory broker 写回长期记忆时，还会参考消息整理层提供的 memory candidates

### 这意味着什么

- 图片说明不只是当前轮临时注入
- 它会进入后续几轮上下文
- 当前轮的图片本体和长期上下文里的 caption 是两条并行链

---

## 十一、当前实现里几个要注意的现实限制

## 1. 这块还是最小实现，不是完整体系

很多东西已经接进主线了，但抽象层还不算厚。
如果你要改大功能，通常要准备好补接口，而不是只在业务分支上打补丁。

## 2. working memory 和 compaction 有并发语义

`pipeline.py` 里现在已经明确是：

- 同一个 thread 的 run 之间允许并行
- compaction 用 snapshot + apply 方式回写

所以你如果要改 compaction 或 thread 回写方式，一定要注意并发语义。

## 3. 现在真正影响 memory 的是 session 决策链

如果你还在按旧的 `event policy` 理解“哪些消息会进长期记忆”，那已经不对了。

现在更应该看：

- `SessionRuntime.resolve_context(...)`
- `SessionRuntime.resolve_extraction(...)`
- `ctx.context_decision`
- `ctx.extraction_decision`
- `RetrievalPlanner`
- `MemoryBroker`

---

## 十二、如果你要改这里，先看哪些文件

建议按这个顺序：

1. `src/acabot/runtime/pipeline.py`
2. `src/acabot/runtime/inbound/message_preparation.py`
3. `src/acabot/runtime/inbound/message_projection.py`
4. `src/acabot/runtime/memory/context_compactor.py`
5. `src/acabot/runtime/memory/retrieval_planner.py`
6. `src/acabot/runtime/memory/memory_broker.py`
7. `src/acabot/runtime/memory/structured_memory.py`
8. `src/acabot/runtime/soul/source.py`
9. `src/acabot/runtime/memory/file_backed/`

如果你只记一句话，那就是：

> **thread 保存短期上下文，retrieval planner 负责把各种材料拼进 prompt，memory broker 负责长期记忆检索和写回，sticky notes 和 soul 是额外稳定材料。**
