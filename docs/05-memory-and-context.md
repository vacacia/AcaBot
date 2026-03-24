# working memory、长期记忆和上下文组装

这一篇只讲当前代码里最重要的两件事：

1. 记忆和上下文现在分成哪些层
2. 一条消息进来后，这些层怎么进入最终模型输入

---

## 先讲结论

当前前台主线里，真正给模型看的上下文不是在 pipeline 里到处拼出来的。

现在稳定的主线是：

- `ThreadPipeline` 负责准备中间态
- `RetrievalPlanner` 只负责 prepare
- `MemoryBroker` 统一读取 `/self`、sticky notes、长期记忆
- `ContextAssembler` 统一组装最终 `system_prompt` 和 `messages`
- `PayloadJsonWriter` 在模型调用前落盘最终 payload json

也就是说：

> **`ctx.system_prompt` 和 `ctx.messages` 现在只表示最终结果，不再表示 pipeline 中间态。**

---

## 一、现在有哪些“像记忆”的层

## 1. thread working memory

这一层在：

- `src/acabot/runtime/contracts/records.py`
- `src/acabot/runtime/storage/threads.py`

它表达的是当前 thread 的短期上下文：

- `working_messages`
- `working_summary`

这层主要服务：

- 当前轮上下文压缩
- retained history 准备
- 回复后的 thread 回写

---

## 2. event / message facts

这两层还是记录真实发生过什么：

- `ChannelEventStore`
  - 平台上发生过什么
- `MessageStore`
  - 系统真正发送并送达了什么

它们不是给模型直接拼 prompt 的 working memory。

---

## 3. `/self`

`/self` 现在是前台 bot 的自我连续性文件区。

当前真实文件形状是：

```text
/self/
  today.md
  daily/
    2026-03-23.md
    2026-03-22.md
```

对应代码在：

- `src/acabot/runtime/soul/source.py`

虽然类名暂时还叫 `SoulSource`，但它现在管理的已经是 `/self`：

- `today.md`
  - 今天的极简连续性记录
- `daily/*.md`
  - 近几天整理过的总结稿

这一层由 bot 自己维护，用来保持 Aca 的行动连续性，不是人格 prompt，也不是 sticky note。

---

## 4. sticky notes

sticky notes 现在是 file-backed 的稳定记忆材料。

对应代码在：

- `src/acabot/runtime/memory/file_backed/sticky_notes.py`

当前正式支持的 scope 还是：

- `user`
- `channel`

每条 sticky note 依然是双区：

- `readonly.md`
- `editable.md`

这一层表达的是稳定事实和长期规则。

---

## 5. 普通长期记忆

普通长期记忆当前仍然在 `MemoryStore` 里。

对应代码在：

- `src/acabot/runtime/memory/memory_broker.py`
- `src/acabot/runtime/memory/structured_memory.py`

这条线现在已经跑通的主要是最小闭环：

- run 前 retrieval
- run 后 extraction

---

## 二、当前中间态是怎么准备的

## 1. 消息整理层

入口在：

- `src/acabot/runtime/inbound/message_preparation.py`

`MessagePreparationService.prepare(ctx)` 会先把当前消息准备成 `MessageProjection`：

- `history_text`
  - 用来写进 thread working memory
- `model_content`
  - 用来作为最终那条 current user message
- `memory_candidates`
  - 给长期记忆写回参考

所以当前消息在系统里本来就有多种用途，不是一份字符串走到底。

---

## 2. context compaction

入口在：

- `src/acabot/runtime/memory/context_compactor.py`

这一步会在预算内把 thread working memory 压成：

- `effective_working_summary`
- `effective_compacted_messages`
- `effective_dropped_messages`

这些结果先放在 `ctx.metadata`，后面的 planner 和 broker 再消费。

---

## 3. RetrievalPlanner

入口在：

- `src/acabot/runtime/memory/retrieval_planner.py`

`RetrievalPlanner` 现在是 prepare-only 组件。

它只产出 `RetrievalPlan`，不再负责最终 prompt 组装。

当前 `RetrievalPlan` 里最重要的内容是：

- `requested_tags`
- `sticky_note_scopes`
- `retained_history`
- `dropped_messages`
- `working_summary`
- `metadata["context_labels"]`

它表达的是：

> **这一轮共享给记忆来源的现场是什么、当前保留了哪些历史、当前 working summary 是什么。**


`RetrievalPlanner` 至少在做三件 `MemoryBroker` 不适合直接背上的事：

- 它把 short-term context 那条线的产物收成一个 run 级 `RetrievalPlan`。`prepare()` 会直接读 `effective_compacted_messages` 和 `effective_working_summary`，然后产出 `retained_history` 和 `working_summary`。这块本质上是“把 compaction 结果解释成检索现场”，不是“问记忆源要内容”。
- 它把这一轮的 retrieval tags、sticky note scopes、context labels 这些 run-local 条件收口。这属于“这轮到底在问什么”的准备层。
- 它产出的 `RetrievalPlan` 不只是给 broker 用，`ContextAssembler` 还直接拿它来组 `working_summary` 和 `retained_history` 进最终上下文

反过来看，`MemoryBroker` 当前更像执行层：
- 它拿到 `RunContext` 或已经准备好的 retrieval context，规范成 shared request
- 统一调用各个 memory source
- 合并、规范化 `MemoryBlock`
- 把结果交回主线

它的天然问题域是“怎么问 source、怎么收结果”，不是“这一轮短期上下文该怎么变成检索现场”。


所以更直白地说：
- `RetrievalPlanner` 回答的是：**这轮检索的现场是什么**
- `MemoryBroker` 回答的是：**拿着这个现场去问哪些记忆源，并把结果收回来**

如果只剩 `MemoryBroker`，那它最后就会同时碰：

- compaction 产物
- sticky note scopes / context labels
- retrieval request 组装
- memory source 调度
- memory block 规范化
- 甚至后面还可能顺手碰 assembler 输入

这样 broker 很容易重新长成一个大杂烩。

我自己的判断是：**这层可以改名，但不该消失。**  
`RetrievalPlanner` 这个名字现在确实有点误导，它更像 `RetrievalContextBuilder` 或 `RetrievalContextPreparer`。

---

## 三、MemoryBroker 现在做什么

入口在：

- `src/acabot/runtime/memory/memory_broker.py`

`MemoryBroker` 现在是所有“非聊天记录”的统一读取入口。

当前 retrieval 侧，它会把 `RunContext` 规范成 `MemoryRetrievalRequest`，然后交给组合 retriever：

- `SelfFileRetriever`
- `StickyNotesFileRetriever`
- `StoreBackedMemoryRetriever`

对应实现分别在：

- `src/acabot/runtime/memory/file_backed/retrievers.py`
- `src/acabot/runtime/memory/structured_memory.py`

所以现在 `/self`、sticky notes、普通长期检索记忆，已经都走 `MemoryBroker.retrieve(ctx)` 这一个入口。

---

## 四、最终上下文现在怎么组装

最终上下文组装入口在：

- `src/acabot/runtime/context_assembly/assembler.py`

`ContextAssembler` 会把上游材料统一转成 `ContextContribution`，再组装成：

- `AssembledContext.system_prompt`
- `AssembledContext.messages`

当前真正参与组装的来源有：

- base prompt
- visible skill summaries
- visible subagent summaries
- memory blocks
  - `/self`
  - sticky notes
  - retrieved memory
- `working_summary`
- retained history
- current user `model_content`

当前 slot 结构是：

- `system_prompt`
- `message_prefix`
- `message_history`
- `message_current_user`

其中：

- `working_summary`、`/self`、sticky note、retrieved memory`
  - 进入 `message_prefix`
- retained history
  - 进入 `message_history`
- 当前轮用户输入
  - 进入 `message_current_user`

---

## 五、主线顺序现在是什么

当前真实顺序可以按这条线记：

1. `MessagePreparationService.prepare(ctx)`
2. pipeline 把 `history_text` 写进 thread working memory
3. `ContextCompactor` 生成 effective summary / retained history
4. `RetrievalPlanner.prepare(ctx)`
5. `MemoryBroker.retrieve(ctx)`
6. `ModelAgentRuntime.execute(ctx)`
7. `ContextAssembler.assemble(ctx, ...)`
8. `PayloadJsonWriter.write(...)`
9. `BaseAgent.run(...)`

这里最关键的一点是：

> **最终上下文只在 `ModelAgentRuntime -> ContextAssembler` 这一步落地。**

pipeline 不再直接拼最终 `ctx.messages`。

---

## 六、当前几层边界怎么记

可以直接记这四句：

- thread 保存短期上下文
- `RetrievalPlanner` 决定这一轮怎么查、保留哪些历史
- `MemoryBroker` 统一读取 `/self`、sticky note、长期记忆，只负责 retrieval 收发和汇总
- `ContextAssembler` 统一把这些材料变成最终模型输入

如果你后面要继续改：

- `/self` 文件结构
- sticky note 检索范围
- retained history 和 working summary 的关系
- 最终 prompt / messages 到底长什么样

先看：

- `src/acabot/runtime/soul/source.py`
- `src/acabot/runtime/memory/file_backed/retrievers.py`
- `src/acabot/runtime/memory/retrieval_planner.py`
- `src/acabot/runtime/memory/memory_broker.py`
- `src/acabot/runtime/context_assembly/assembler.py`
