# 记忆层与上下文组装

本文档说明 AcaBot 的记忆分层体系，以及一条消息从进入系统到组装成最终模型输入的完整流程。各子系统的详细实现见 `docs/wiki/`。

## 架构总览

最终模型输入不在 pipeline 各阶段零散拼接，而是由 `ContextAssembler` 统一组装。核心组件链路：

```
ThreadPipeline → MessagePreparationService → ContextCompactor
    → RetrievalPlanner（准备检索现场）
    → MemoryBroker（统一读取 /self、sticky notes、长期记忆）
    → ContextAssembler（组装最终 system_prompt + messages）
    → PayloadJsonWriter → BaseAgent.run()
```

`ctx.system_prompt` 和 `ctx.messages` 只表示最终结果，不表示 pipeline 中间态。

## 记忆分层

AcaBot 区分五个层次的"类记忆"数据。前两层（thread working memory、event/message facts）是消息事实，后三层（/self、sticky notes、长期记忆）才是真正的记忆系统。

### Thread Working Memory

当前 thread 的短期上下文，存储在 `ThreadState.working_messages` 和 `ThreadState.working_summary` 中。服务于当前轮上下文压缩、retained history 准备和回复后的 thread 回写。

代码：`src/acabot/runtime/contracts/records.py`、`src/acabot/runtime/storage/threads.py`

### Event / Message Facts

客观事实记录层。`ChannelEventStore` 记录平台上真实发生过什么，`MessageStore` 记录系统真正发送并送达了什么。它们不直接参与 prompt 拼接，但为长期记忆的写入线提供原始数据源，也通过 `/api/runtime/threads/<thread_id>/events` 和 `/messages` 暴露给控制面。

### /self — 自我连续性

记录 Aca 自己经历了什么、正在和谁互动、有哪些持续中的状态和承诺。不是人格 prompt（人格在配置 prompt 里），不是 sticky note（强绑具体对象的信息放 sticky note），而是 bot 自己通过 computer 工具维护的连续性空间。

```
runtime_data/soul/
  today.md            # 今天的极简连续性记录（bot 调用工具追加）
  daily/              # 近几天整理过的总结稿
    2026-03-23.md
```

代码：`src/acabot/runtime/soul/source.py`（类名 `SoulSource`）。前台 world 可见性在 `computer/world.py`，retrieval 走 `MemoryBroker` → `SelfFileRetriever`，控制面走 `/api/self/*`。Subagent 默认看不见 `/self`。

### Sticky Notes — 实体便签

围绕实体的长期稳定笔记，让 bot 能持续理解某个用户或某个群。以 `entity_ref`（如 `qq:user:12345`）为主键，只支持 `user` 和 `conversation` 两种实体类型，几乎每轮都会注入上下文。

数据模型 `StickyNoteRecord`：`entity_ref`（主键）、`readonly`（人工确认的高可信事实）、`editable`（bot 追加的观察）、`updated_at`。物理形态为文件系统双区：

```
runtime_data/sticky_notes/
  user/<entity_ref>/readonly.md + editable.md
  conversation/<entity_ref>/readonly.md + editable.md
```

组件链路：`StickyNoteFileStore` → `StickyNoteService` / `StickyNoteRenderer` → `StickyNoteRetriever`（retrieval 注入）+ builtin tools（`sticky_note_read` / `sticky_note_append`）+ control plane / HTTP API。

Bot 只能 read（完整渲染视图）和 append（追加单行到 editable）；人类通过 WebUI 可以编辑双区、迁移整理、删除。Retrieval 策略：群聊拉 `[actor_id, conversation_id]`，私聊拉 `[actor_id]`，不存在则安静跳过。

### Long-Term Memory — 长期记忆

从完整对话事实中提炼的结构化经验库，基于 Core SimpleMem + LanceDB 实现。采用双线架构：

**写入线（fact-driven）**：前台在事实落盘成功后调用 `LongTermMemoryIngestor.mark_dirty(thread_id)`，LTM 自己维护 dirty set 和后台 worker，通过 `ConversationFactReader` 读取增量事实窗口，经 `LtmWritePort` 完成滑窗提取、embedding 和 LanceDB upsert，成功后推进 `last_event_id` / `last_message_id` 双游标。

**检索线（run-driven）**：`RetrievalPlanner` → `MemoryBroker.retrieve` → `CoreSimpleMemMemorySource`（query planning → semantic/lexical/symbolic 三路召回 → reranking → XML 渲染）→ `ContextAssembler`。

需要三个 model target：`system:ltm_extract`、`system:ltm_query_plan`、`system:ltm_embed`。详细实现设计见 `docs/LTM/`。

代码：`src/acabot/runtime/memory/long_term_memory/`、`src/acabot/runtime/memory/long_term_ingestor.py`

## Pipeline 执行顺序

一条消息从进入到回复的完整流程：

| 步骤 | 组件 | 产物 |
|------|------|------|
| 1 | `MessagePreparationService.prepare(ctx)` | `MessageProjection`（history_text、model_content、memory_candidates） |
| 2 | Pipeline 写入 thread | 当前消息进入 `working_messages` |
| 3 | `ContextCompactor` | `effective_working_summary`、`effective_compacted_messages` |
| 4 | `RetrievalPlanner.prepare(ctx)` | `RetrievalPlan`（retained_history、sticky_note_targets、context_labels） |
| 5 | `MemoryBroker.retrieve(ctx)` | `MemoryBlock[]`（/self、sticky notes、LTM） |
| 6 | `ContextAssembler.assemble(ctx, ...)` | `AssembledContext`（最终 system_prompt + messages） |
| 7 | `PayloadJsonWriter` → `BaseAgent.run(...)` | 模型调用 |

## ContextAssembler 的 Slot 结构

`ContextAssembler` 将所有上游材料转成 `ContextContribution`，按 slot 组装成最终输入：

| Slot | 内容来源 |
|------|---------|
| `system_prompt` | base prompt、visible skill/subagent summaries |
| `message_prefix` | working_summary、/self、sticky notes、LTM retrieved memory |
| `message_history` | retained history（compaction 后保留的历史消息） |
| `message_current_user` | 当前轮用户输入的 model_content |

## RetrievalPlanner 与 MemoryBroker 的分工

`RetrievalPlanner` 负责"这轮检索的现场是什么"——把 compaction 产物解释成检索现场，收口 retrieval tags、sticky note targets 和 context labels。它的产物 `RetrievalPlan` 同时被 `MemoryBroker` 和 `ContextAssembler` 消费。

`MemoryBroker` 负责"拿着这个现场去问哪些记忆源，并把结果收回来"——将 `RunContext` 规范成 `SharedMemoryRetrievalRequest`，调用已注册的三个 memory source（`SelfFileRetriever`、`StickyNoteRetriever`、`CoreSimpleMemMemorySource`），合并并规范化 `MemoryBlock`。

这两层的分离是刻意的：如果合并到 broker，broker 就会同时碰 compaction 产物、scope 选择、request 组装、source 调度和 block 规范化，容易退化成大杂烩。

### MemoryBroker 设计原则

MemoryBroker 是 runtime 和各种记忆来源之间的**唯一入口**，但它自己不是任何一种记忆的真源。每次 run 开始前，它根据当前身份、thread、消息内容、compaction 结果和本轮允许范围，决定去问哪些记忆来源。真正翻文件、查库、做检索的是各来源模块，broker 只负责把结果收齐、整理成统一格式、补上来源元信息，然后交给 ContextAssembler。

**读取线之外，broker 还应承担写回线的统一出口**：一轮结束后，把"这轮可能要更新哪些记忆"的请求统一发出（要不要补长期记忆、更新 sticky note、写入 /self），再交给各自写入模块处理。这样 broker 能追踪本轮读了什么、用了什么、写了什么，为前端展示和问题排查提供统一出口。

**MemoryBroker 明确不管的事：**

| 不管 | 归属 |
|------|------|
| thread working memory | thread + compaction |
| event/message facts 的存储 | 事实记录线 |
| /self 的目录结构和文件编辑 | SoulSource 文件真源 |
| sticky note 的增删改查 | StickyNoteService |
| 记忆在 prompt 中的排列顺序 | ContextAssembler |

## 源码阅读顺序

1. `src/acabot/runtime/soul/source.py`
2. `src/acabot/runtime/memory/file_backed/retrievers.py`
3. `src/acabot/runtime/memory/retrieval_planner.py`
4. `src/acabot/runtime/memory/memory_broker.py`
5. `src/acabot/runtime/context_assembly/assembler.py`
