# 记忆层与上下文组装

本文档说明 AcaBot 的记忆分层体系，以及一条消息从进入系统到组装成最终模型输入的完整流程。同时包含 Sticky Notes 和 Long-Term Memory 两个子系统的完整设计细节。

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

Sticky Note 是 AcaBot 的实体级便签系统，在系统启动时自动激活。每张便签只对应一个实体，通过 `entity_ref` 标识，系统根据 `entity_ref` 自动判断出 `entity_kind`，用于文件目录分组、列表过滤和人类阅读辅助。当前只支持 `user` 和 `conversation` 两类实体。同一张便签同时用于 bot 工具读取、上下文注入、管理界面中的人工编辑和 HTTP API 管理。

#### 核心对象与实体模型

`entity_ref` 的常见格式是 `<platform>:<type>:<id>`，由具体的平台适配器决定。

| `entity_ref` | `entity_kind` |
|---|---|
| `qq:user:10001` | `user` |
| `qq:group:20002` | `conversation` |
| `discord:channel:987654321` | `conversation` |

数据模型 `StickyNoteRecord` 包含四个字段：`entity_ref`（主键）、`readonly`（人工确认的高可信事实，bot 只读不改）、`editable`（bot 追加的观察区域）、`updated_at`。另有 `combined_text`，每次读取时实时把 `readonly` 和 `editable` 合并后生成的完整文本视图，不是持久化字段。

`entity_ref` 的校验和 `entity_kind` 的判断由同一个共享解析函数负责。当前实现允许系统内部标准实体 id 里常见的字符（字母、数字、`:`、`-`、`_`、`.`、`@`、`!`），并明确拒绝路径分隔符、`..`、`thread:`、`session:` 这类非法输入。关键函数集中在 `src/acabot/runtime/memory/sticky_note_entities.py`：

- `parse_sticky_note_entity_ref(entity_ref)` — 校验并解析实体引用
- `derive_sticky_note_entity_kind(entity_ref)` — 从 ref 派生实体类型
- `normalize_sticky_note_entity_kind(entity_kind)` — 类型标准化

其他层只复用这里的结果，不自己再实现一套规则。

#### 存储模型

每张 sticky note 在逻辑上是一条便签记录，在物理上保留双文件结构。目录按 `entity_kind` 分组，目录名直接使用 `entity_ref`。`updated_at` 取 `readonly.md` 和 `editable.md` 两个文件修改时间的最大值。当前没有单独的索引文件，也没有 `note_key` 这一层逻辑寻址。

```
.acabot-runtime/sticky-notes/
├── user/
│   └── <entity_ref>/
│       ├── readonly.md
│       └── editable.md
└── conversation/
    └── <entity_ref>/
        ├── readonly.md
        └── editable.md
```

#### 组件结构

整体链路为 `StickyNoteFileStore → StickyNoteService → StickyNoteRenderer → builtin tools / StickyNoteRetriever / control plane / HTTP API`。各组件的文件位置和职责如下：

| 组件 | 文件 | 职责 |
|---|---|---|
| entity 解析 | `src/acabot/runtime/memory/sticky_note_entities.py` | 校验 `entity_ref`，派生 `entity_kind`，统一 sticky note 的命名边界 |
| 文件存储层 | `src/acabot/runtime/memory/file_backed/sticky_notes.py` | 定义 `StickyNoteRecord`，管理文件布局，读取、保存、追加、删除和列表查询 |
| 渲染器 | `src/acabot/runtime/memory/sticky_note_renderer.py` | 把 `StickyNoteRecord` 渲染成统一 XML 风格文本（`render_combined_text(record)`） |
| 服务层 | `src/acabot/runtime/memory/sticky_notes.py` | 提供 bot 面和人类控制面的稳定业务接口 |
| 上下文检索适配层 | `src/acabot/runtime/memory/file_backed/retrievers.py` | 根据 `sticky_note_targets` 精确读取 sticky note，转换成 `MemoryBlock` |
| 内建工具 | `src/acabot/runtime/builtin_tools/sticky_notes.py` | 注册 `sticky_note_read` 和 `sticky_note_append`，把服务层结果转成工具返回对象 |
| 控制面 | `src/acabot/runtime/control/control_plane.py` | 暴露人类控制面使用的 sticky note 管理动作 |
| HTTP API | `src/acabot/runtime/control/http_api.py` | 把控制面的 sticky note 动作暴露成本地 API |
| runtime 启动接线 | `src/acabot/runtime/bootstrap/__init__.py` | 创建 store 和 service，接进 builtin tool 注册、memory broker、control plane 和 runtime components |
| memory broker 接线 | `src/acabot/runtime/bootstrap/builders.py` | 在 `MemoryBroker` 中注册 `StickyNoteRetriever`（`build_memory_broker(...)`） |
| runtime 组件导出 | `src/acabot/runtime/bootstrap/components.py` | 把 `sticky_notes_source` 和 `sticky_notes` 暴露给其他组件 |

#### 服务层接口

服务层（`src/acabot/runtime/memory/sticky_notes.py`）将文件存储层收成稳定的业务接口。Bot 侧接口为 `read_note(entity_ref)` 和 `append_note(entity_ref, text)`，其中 `append_note(...)` 只接受单行文本，空白文本直接拒绝，写入只发生在 `editable`。人类控制面接口为 `load_record(entity_ref)`、`save_record(record)`、`create_record(entity_ref)`、`delete_record(entity_ref)`、`list_records(entity_kind=...)`。`create_record(...)` 可以重复调用，如果 note 已存在，直接返回现有内容，不会覆盖 `readonly` 或 `editable`。

文件存储层（`src/acabot/runtime/memory/file_backed/sticky_notes.py`）提供对应的底层方法：`StickyNoteFileStore.load_record`、`.save_record`、`.create_record`、`.append_editable_text`、`.delete_record`、`.list_records`。

#### 上下文注入流程

默认"要读取哪些便签"是在 `SessionRuntime._default_sticky_note_targets(facts)` 中决定的。群聊默认选择当前发言人的 user note 和当前对话容器的 conversation note；私聊默认只选择当前发言人的 user note——群聊里通常需要同时记住"这个人是谁"和"这个群在聊什么"。

完整注入路径：`SessionRuntime._default_sticky_note_targets` → `RetrievalPlanner.prepare`（收成 `sticky_note_targets: list[str]`）→ `MemoryBroker._build_retrieval_request` → `StickyNoteRetriever`（只读取明确给出的目标，不做全文搜索，也不做目录全量扫描）→ `StickyNoteRenderer` → `ContextAssembler`。

#### Bot 工具

当前正式工具只有两个：`sticky_note_read(entity_ref)` 和 `sticky_note_append(entity_ref, text)`，由 bootstrap 直接注册进 `ToolBroker`，但仍然受 `enabled_tools` 控制。调用路径：

```
# 读取
ToolBroker → BuiltinStickyNoteToolSurface.sticky_note_read
  → StickyNoteService.read_note → StickyNoteFileStore.load_record
  → StickyNoteRenderer.render_combined_text

# 追加
ToolBroker → BuiltinStickyNoteToolSurface.sticky_note_append
  → StickyNoteService.append_note → StickyNoteFileStore.append_editable_text
  → StickyNoteFileStore.save_record
```

代码：`src/acabot/runtime/builtin_tools/sticky_notes.py`、`src/acabot/runtime/builtin_tools/__init__.py`

#### 控制面与 HTTP API

Control plane 提供的 sticky note 动作：`list_sticky_notes(entity_kind)`、`get_sticky_note_record(entity_ref)`、`save_sticky_note_record(entity_ref, readonly, editable)`、`create_sticky_note(entity_ref)`、`delete_sticky_note(entity_ref)`。

HTTP API 端点如下，仅接受 `entity_kind = user | conversation`，非法分类返回 `400`：

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/memory/sticky-notes?entity_kind=...` | 列出某类实体的 sticky notes |
| `GET` | `/api/memory/sticky-notes/item?entity_ref=...` | 读取一张完整便签 |
| `POST` | `/api/memory/sticky-notes/item` | 创建一张空 note |
| `PUT` | `/api/memory/sticky-notes/item` | 保存整张 note |
| `DELETE` | `/api/memory/sticky-notes/item?entity_ref=...` | 删除一张 note |

Bot 只能 read（完整渲染视图）和 append（追加单行到 editable）；人类通过 WebUI 可以编辑双区、迁移整理、删除。Retrieval 策略：群聊拉 `[actor_id, conversation_id]`，私聊拉 `[actor_id]`，不存在则安静跳过。

#### 测试文件分布

| 主题 | 测试文件 |
|---|---|
| 文件真源 | `tests/runtime/test_sticky_note_file_store.py` |
| 渲染 | `tests/runtime/test_sticky_note_renderer.py` |
| 服务层 | `tests/runtime/test_sticky_note_service.py` |
| retrieval | `tests/runtime/test_sticky_note_retriever.py`、`tests/runtime/test_file_backed_memory_retrievers.py` |
| builtin tools | `tests/runtime/test_sticky_note_builtin_tools.py`、`tests/runtime/test_builtin_tools.py` |
| control plane / HTTP API | `tests/runtime/test_control_plane.py`、`tests/runtime/test_http_api_sticky_notes.py`、`tests/runtime/test_webui_api.py` |
| planner / broker / bootstrap | `tests/runtime/test_retrieval_planner.py`、`tests/runtime/test_memory_broker.py`、`tests/runtime/test_bootstrap.py`、`tests/runtime/test_session_runtime.py` |

### Long-Term Memory — 长期记忆

从完整对话事实中提炼的结构化经验库，基于 Core SimpleMem + LanceDB 实现。整体架构基于 **CDC（Change Data Capture）** 与**最终一致性**：前台在事实落盘成功后仅通知 LTM，LTM 自行维护脏集合、双游标、后台 worker，通过 runtime 提供的薄读接口拉取增量事实窗口来形成长期记忆。设计需要解决四个核心矛盾——不能拖慢回复、绝对不能漏记、用户消息与 bot 回复存在两个不同的 store（`ChannelEventStore` / `MessageStore`）中需要合流、LTM 作为可选模块不能与核心代码强耦合。

#### 双线架构

**写入线（fact-driven）**：前台主线不负责"触发一次长期记忆提取"，只在事实落盘成功后顺手调用 `LongTermMemoryIngestor.mark_dirty(thread_id)`。LTM 内部自己维护 dirty set 和后台 worker，通过 `ConversationFactReader` 读取增量事实窗口，经 `LtmWritePort` 完成滑窗提取、embedding 和 LanceDB upsert，成功后推进 `last_event_id` / `last_message_id` 双游标。通知方式用 direct call，不用 event bus；Store 保持贫血，`ChannelEventStore` / `MessageStore` 只负责存取，不带副作用；`mark_dirty(thread_id)` 发生在 `RuntimeApp` / `Outbox` 这种写入编排层。

**检索线（run-driven）**：`RetrievalPlanner` → `MemoryBroker.retrieve` → `LtmMemorySource`（query planning → semantic/lexical/symbolic 三路召回 → reranking → XML 渲染）→ `ContextAssembler`。

需要三个 model target：`system:ltm_extract`、`system:ltm_query_plan`、`system:ltm_embed`。

#### 六个核心对象

| 对象 | 定位 | 职责说明 |
|---|---|---|
| `LongTermMemoryIngress` / `LongTermMemoryIngestor` | 信号守门人 | 前台主线看得到的**唯一入口**。主线把消息保存到数据库后，调用 `mark_dirty(thread_id)` 即可返回。它是纯异步、纯内存的阀门，把 dirty 信号收拢进 Set，唤醒后台 Worker。零副作用，瞬间完成，绝对不卡主线。 |
| `LongTermMemoryIngestor` Worker | 后台消费者 | 后台无限循环的消费者，感知到线程脏了就接管该 `thread_id`——拉取增量、调用模型提取、写进向量库、更新游标。它是整个 LTM 流水线的**总编排者（Orchestrator）**。遇到模型提取失败时不抛异常、不写死游标、等下一次补救；系统启动时发出扫库指令，把历史遗留的僵尸线程捞回消化池。 |
| `ConversationFactReader` | 防腐层（Anti-Corruption Layer） | Runtime 提供给 LTM 的只读翻译官。LTM Ingestor 只管伸手要"某线程从某点位到现在的对话"，Reader 负责翻阅 `ChannelEventStore` 和 `MessageStore`，把双层数据打平、按时间搓揉排序，整理成人类可读的对话流。有了它，LTM 组件永远不需要知道底层存储细节。 |
| `ConversationDelta` | 增量批次包裹 | `ConversationFactReader` 的产出物，采用 **Payload + Next Cursor** 模式。包裹里不仅塞满 `facts`（事实），还自带 `max_event_id` 和 `max_message_id`。Ingestor 拿到货，喂给模型，成功后无脑照抄包裹上的号码移动游标，完全不用解析和遍历内部事实。 |
| `ConversationFact` | 高维度绝对坐标 | 包裹中的每一条实体事实，高度抽象后只保留：`timestamp`（何时）、`role` / `actor_id`（谁说的）、`thread_id` / `channel_scope`（在哪里说的）、`text`（说了什么）。`source_kind` 配合时间戳作为 tie-breaker，保证毫秒级并发下事实排列顺序与现实一致。 |
| `ThreadLtmCursor` | 每线程书签（Source of Truth） | 每个线程专属的记忆进度条，包含 `last_event_id`、`last_message_id`、`updated_at`。游标记录的是两边各自的自增主键/sequence，不是时间戳。它持久化落盘，是弱一致性系统正常运转的真理之源——重启扫库补偿、优雅停止截断、防灾防泄漏都依赖这根进度条。 |

一句话串联：前台丢下一个信号（Ingress），后台（Ingestor）醒来阅读进度条（ThreadLtmCursor），请翻译官（ConversationFactReader）打包出一个带有新进度条的对话包裹（ConversationDelta），包裹里装满统一格式的历史事实（ConversationFact），最后送给大模型吃掉，更新进度条，循环往复。

#### Dirty 追踪机制

LTM 内部维护一个内存 `Set[thread_id]` 作为 `dirty_threads`，不单独持久化 dirty 队列。进程启动时做一次 SQL 扫库，把"事实超过游标"的 thread 补回 dirty set，实现重启恢复。

`mark_dirty` 的时机有两个：用户/平台消息写入 `ChannelEventStore` 后打一次，bot 回复写入 `MessageStore` 后再打一次——两边落盘都打 dirty。`mark_dirty()` 失败不影响前台主线，因为事实已经落盘就是成功，dirty set 是派生状态，启动扫库会补回来。

#### 双游标系统

每个 thread 在 LTM 自己的存储里维护两根持久化游标：`last_event_id` 和 `last_message_id`，记录的是两边各自的自增主键/sequence，不是时间戳。`ConversationFactReader` 从 `ChannelEventStore` 拉 `event_id > last_event_id` 的增量，从 `MessageStore` 拉 `message_id > last_message_id` 的增量，合并成统一的增量事实窗口。合并顺序先按 `timestamp`，相同时间再按 `(source_kind, source_id)` 做稳定排序。

#### 失败处理

Worker 被唤起后**立刻处理**，不等静默窗口。如果 LTM 写入失败：不推进任何游标，thread 保持 dirty，不主动重试——等下次新信号来了再一起拉。LTM 自己决定是否回看更早上下文，自己做提取、区间去重、全局去重，落到自己的长期记忆存储。只有当这次写入成功时，LTM 才推进两根游标。

代码：`src/acabot/runtime/memory/long_term_memory/`、`src/acabot/runtime/memory/long_term_ingestor.py`。详细实现设计见 `docs/LTM/`。

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

`MemoryBroker` 负责"拿着这个现场去问哪些记忆源，并把结果收回来"——将 `RunContext` 规范成 `SharedMemoryRetrievalRequest`，调用已注册的三个 memory source（`SelfFileRetriever`、`StickyNoteRetriever`、`LtmMemorySource`），合并并规范化 `MemoryBlock`。

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
6. `src/acabot/runtime/memory/sticky_note_entities.py`
7. `src/acabot/runtime/memory/file_backed/sticky_notes.py`
8. `src/acabot/runtime/memory/sticky_notes.py`
9. `src/acabot/runtime/memory/long_term_ingestor.py`
10. `src/acabot/runtime/memory/long_term_memory/`
