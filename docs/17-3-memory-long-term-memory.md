# 长期记忆怎么和现有框架交互

这一篇只讲一件事：

- 类似 SimpleMem 这种“从完整对话里提取内容，形成长期记忆，并在后续检索时提供给前台上下文”的能力，应该怎样接进 AcaBot 当前框架

这一篇不展开：

- 长期记忆内部怎么抽取
- 长期记忆内部怎么合并
- embedding / rerank / 向量库
- prompt 和算法细节

---

## 当前代码已经落地的形状

现在仓库里的长期记忆正式实现已经落在：

- `src/acabot/runtime/memory/long_term_memory/`
- `src/acabot/runtime/memory/long_term_ingestor.py`
- `src/acabot/runtime/bootstrap/builders.py`

当前运行形态是：

- 配置 `runtime.long_term_memory.enabled = true`
- runtime 自动装配 `LanceDbLongTermMemoryStore`
- 写侧走 `LongTermMemoryIngestor -> LtmWritePort`
- 读侧走 `MemoryBroker -> CoreSimpleMemMemorySource`
- 模型位点统一走：
  - `system:ltm_extract`
  - `system:ltm_query_plan`
  - `system:ltm_embed`

这里要注意:

- 打开开关只负责把链路装起来
- 真正可用还要先给这三个 `system:ltm_*` target 配好 `model_binding`

---

## 先讲结论

长期记忆在 AcaBot 里，应该按两条线接入：

- **写入线是 fact-driven**
- **检索线是 run-driven**

换句话说：

- 长期记忆的形成，依赖事实层里已经落盘的完整对话
- 长期记忆的使用，依赖当前这一轮 run 的检索现场

对应到组件边界，就是：

- 长期记忆组件自己读取 `ChannelEventStore + MessageStore`
- 长期记忆组件自己决定保留什么、什么时候写、写到哪里
- 前台 runtime 在需要上下文时，再通过 `MemoryBroker` 向长期记忆组件取回记忆

所以这套系统里，长期记忆更像一个双面组件：

- 一面是 **Ingestor / Writer**
  - 平时自己消费事实层
  - 自己形成长期记忆
- 一面是 **Source / Retriever**
  - 在 retrieval 阶段被主线调用
  - 把长期记忆转成 `MemoryBlock`

---

## 这篇在讨论什么

这里说的“长期记忆”，专指这一类能力：

- 它面对的是完整对话事实，而不是某一轮 run 临时拼出来的一份材料
- 它会把值得保留的内容沉淀成结构化长期材料
- 它平时自己维护自己的长期记忆存储
- 当前台这一轮需要时，它再把相关长期记忆提供出来

它和下面几层不是同一个东西：

- `thread working memory`
  - 当前 thread 的短期上下文
- `event / message facts`
  - 平台真实发生过什么、系统真实发送过什么
- sticky note
  - 可直接维护的稳定笔记
- `/self`
  - Aca 自己的连续性文件区

长期记忆在这里更像：

- 一个建立在事实层之上的经验提炼系统
- 一个平时自己整理、用时再被检索的长期材料库

---

## 一、写入线：长期记忆怎样接到事实层

长期记忆写入的核心边界只有一句话：

> 长期记忆写入是 `fact-driven + event-driven`，不是 `run-driven`。

这里的意思不是“前台完全不参与”，而是：

- 前台主线只负责在事实落盘成功后，顺手通知 LTM 一下
- LTM 自己维护待处理队列、消费节奏、增量游标和写入状态
- 前台不负责“发起一次长期记忆提取”

### 1. 长期记忆的消息内容正式来源

长期记忆要拿到完整对话，正式来源只有两套事实存储：

- `ChannelEventStore`
  - 保存平台侧真实进来的事件和用户消息
- `MessageStore`
  - 保存 bot 自己真正发出去并送达成功的回复

这两边合起来，才是一份完整对话。

也就是说，长期记忆获取消息内容的正式来源是：

`ChannelEventStore + MessageStore`

这两层事实还需要满足一个很重要的前提：

- 事实记录按稳定 UID 幂等写入
- 同一个 UID 只能重复写入同一条事实
- 如果有人想用同一个 UID 静默改写另一条内容，事实层应该直接报错

长期记忆写入线依赖的就是这层不可变性。只有事实本身稳定，`last_event_id / last_message_id` 这种 sequence 游标才有意义。

如果只读 `ChannelEventStore`，拿不到 bot 自己的回复；如果只读前台某次 run 的临时材料，拿到的也不是完整事实。

### 2. 事实落盘后，前台只做一个很薄的 direct call

写入线不用 event bus，也不用让 `Store` 带副作用。

这里的边界是：

- `Store` 只负责存取，保持贫血
- 副作用放在写入编排层
- 事实落盘成功后，编排层直接调用写侧对象的业务入口：
  - `LongTermMemoryIngestor.mark_dirty(thread_id)`

对应到当前主线：

- `RuntimeApp` 成功写入 `ChannelEventStore` 后，调用一次 `LongTermMemoryIngestor.mark_dirty(thread_id)`
- `Outbox` 成功写入 `MessageStore` 后，调用一次 `LongTermMemoryIngestor.mark_dirty(thread_id)`

这里 `Outbox` 写入 assistant message 事实时，还要把真实的 `conversation_id` 一起带上，不能在后面再用 `thread_id` 去猜。

前台主线到这里就结束了。

它不负责：

- 立刻分析长期记忆
- 决定这条消息值不值得保留
- 决定什么时候写入 LTM
- 决定写入哪一种长期材料

### 3. LTM 自己维护 `dirty_threads`

LTM 这一侧把 `mark_dirty(thread_id)` 当成一个轻量信号。

第一版最简单也最稳的形状是：

- LTM 内部维护一个内存 `Set[thread_id]`
- 同一个 thread 连续来 10 条消息，Set 里仍然只有 1 个 `thread_id`
- worker 看到这个 thread dirty 后，一次性拉这一段新增事实

这里不需要专门持久化一张 dirty 表。

原因是 dirty set 只是派生状态，不是真相源。真正的真相源只有两样：

- 事实存储里的消息本身
- LTM 自己保存的双游标

所以进程重启后，只需要在启动时做一次 SQL 扫库，把“事实已经超过游标”的 thread 补回 dirty set 就够了。

### 4. LTM 自己维护单 worker 和双游标

第一版写入线默认只有一个 `LongTermMemoryIngestor` worker。

这个 worker 自己负责：

- 消费 `dirty_threads`
- 读取该 thread 当前的增量窗口
- 调用 LTM 内部提取逻辑
- 成功后推进游标

每个 thread 在 LTM 自己的存储里维护两根持久化游标：

- `last_event_id`
- `last_message_id`

它们记录的不是时间戳，而是两边各自的自增主键 / sequence。

这样做的原因是：

- 边界最稳定
- 不怕同一毫秒内多条消息
- 不需要靠时间戳去猜边界

这两根游标属于 LTM 自己的状态，不属于 runtime 公共存储。

### 5. runtime 提供薄 `ConversationFactReader`

为了不让具体的 LTM 实现直接理解两套底层事实表的拼接细节，runtime 侧应该提供一个很薄的只读能力：

- `ConversationFactReader`

它的职责很窄：

- 从 `ChannelEventStore` 拉 `event_id > last_event_id` 的增量
- 从 `MessageStore` 拉 `message_id > last_message_id` 的增量
- 把两边归一化成统一的 `ConversationFact`
- 合并成一段统一的“增量事实窗口”

这层不是 LTM 算法层，只是事实层的统一读取接口。

也就是说，runtime 对 LTM 写入线提供的正式输入，不是 run context，也不是 prompt 材料，而是：

`ConversationFactReader.get_thread_delta(thread_id, last_event_id, last_message_id)`

### 6. 增量事实窗口怎么合并

两边 store 的自增主键彼此独立，所以 merge 顺序不能直接比 ID。

统一事实窗口的排序规则应该固定成：

- 先按统一 `timestamp`
- 如果时间相同，再按 `(source_kind, source sequence)` 做稳定 tie-break

这样可以保证：

- user / assistant 两边来源能合成一条稳定对话流
- 同一批事实每次重拉时顺序一致

runtime 这一侧只负责把新增事实整理成一段稳定的增量窗口。

至于 LTM 需要不要回看更早上下文，是 LTM 自己的事。

### 7. LTM 只吃增量窗口，是否回看由自己决定

worker 每次处理一个 dirty thread 时，runtime 只提供这一段**新增事实窗口**。

也就是说，runtime 负责的是：

- 找到这一轮新增了哪些事实
- 把新增事实整理成统一对话片段

runtime 不负责：

- 主动给 LTM 补一整条 thread 历史
- 猜 LTM 提取时需要多大的上下文窗口
- 替 LTM 做跨区间去重

如果 LTM 觉得提取时还要回看更早材料，它可以：

- 读取自己的长期记忆存储
- 或者再次回查原始事实层

### 8. 成功才推进游标，失败只保留 dirty

LTM 写入线的推进规则应该固定成：

- 只有当这批增量成功写入长期记忆后，才推进 `last_event_id` 和 `last_message_id`
- 如果写入失败，不推进任何游标
- thread 保持 dirty
- 不主动重试，等下次新信号来了再一起拉

这条语义把 runtime 和 LTM 的责任切得很干净：

- runtime 只保证事实可读
- LTM 自己决定怎么处理重复区间
- 幂等、区间去重、全局去重，都是 LTM 自己的责任

### 9. `mark_dirty()` 失败不影响前台主线

`mark_dirty(thread_id)` 只是对 LTM 的 best-effort 通知。

所以它的失败语义应该是：

- `ChannelEventStore` / `MessageStore` 落盘失败：主线失败
- 事实已经落盘，但 `mark_dirty()` 失败：主线继续，只记日志和指标

原因很简单：

- 事实已经落盘，真相没有丢
- dirty set 只是派生状态
- 启动时的扫库会把漏掉的 dirty thread 补回来

所以这里最终可以收成一句话：

> 前台只负责在事实落盘成功后调用 `LongTermMemoryIngestor.mark_dirty(thread_id)`；LTM 自己负责消费 dirty thread、维护双游标、读取增量事实窗口并形成长期记忆。

---

## 二、新增对象与边界

写入线定下来之后，真正需要新增到系统里的对象并不多。

这里最重要的要求不是“多拆几层”，而是把每个对象的边界钉死，避免后面一边写代码一边又把责任揉回一起。

### 1. `LongTermMemoryIngestor`

它是写入线唯一对 runtime 暴露的业务对象。

从逻辑上看，它同时扮演两个角色：

- Producer 入口
  - 接收 `mark_dirty(thread_id)` 信号
- Consumer 执行体
  - 后台消费 `dirty_threads`

但在代码实现上，这两个角色先合成一个类更自然，因为它们必须共享同一组核心状态：

- `dirty_threads: set[str]`
- 唤醒 worker 的并发原语
- worker 生命周期状态

这个类的最小公开接口应该只有三项：

```python
class LongTermMemoryIngestor:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def mark_dirty(self, thread_id: str) -> None: ...
```

这里的边界要明确：

- `mark_dirty(thread_id)` 是同步方法
- 它只做两件事：
  - 把 `thread_id` 放进内存 `Set`
  - 唤醒后台 worker
- 它不做：
  - `await`
  - 读 store
  - 读写游标
  - 提取长期记忆
  - 长期记忆落库

生命周期语义也一起定死：

- `start()`
  - 先启动 worker，让系统立刻具备消费能力
  - 再以独立 task 发起一次“启动扫库补 dirty”
  - 扫库过程中复用同一个 `mark_dirty(thread_id)` 机制
  - `start()` 自己不等待扫库完成，立即返回
- `mark_dirty(thread_id)`
  - 可以在 `start()` 之前被调用
  - 这时它只是先把 `thread_id` 留在内存 `Set` 里
  - 等 `start()` 之后再由 worker 自然消费
- `stop()`
  - 不再继续处理新的 dirty thread
  - 允许当前正在处理的那个 thread 跑完
  - `Set` 里还没开始处理的 thread 可以直接丢弃
  - 下次启动时靠扫库补回来

这一层是写侧编排，不是 LTM 内部算法层。

### 2. `ConversationFactReader`

这是 runtime 提供给 LTM 写入线的一个薄只读服务。

它的职责只有：

- 从 `ChannelEventStore` 读取指定 thread 的事件增量
- 从 `MessageStore` 读取指定 thread 的 assistant 消息增量
- 统一归一化
- 合并成稳定排序后的增量事实窗口

它不负责：

- 判断什么值得保留
- 提取长期记忆
- 去重
- 写入 LTM

它的公开接口可以收成：

```python
async def get_thread_delta(
    thread_id: str,
    after_event_id: int | None,
    after_message_id: int | None,
) -> ConversationDelta
```

它回答的问题是：

- “这个 thread 从这两个游标之后，多出来了哪些事实？”

而不是：

- “这些事实该不该变成长期记忆？”

### 3. `ConversationDelta`

这是 `ConversationFactReader` 吐给 `LongTermMemoryIngestor` 的统一结果。

它应该只表示一个 thread 的**增量事实窗口**，而不是整条 thread 历史。

最小字段可以收成：

- `facts`
- `max_event_id`
- `max_message_id`

这样 `LongTermMemoryIngestor` 不需要自己再从 facts 里反推新游标边界。

### 4. `ConversationFact`

这是 runtime 对 LTM 写入线暴露的最小事实单位。

它的字段需要同时满足两件事：

- 对 LTM 来说足够表达一段对话事实
- 不把平台细节和 LTM 内部细节混进来

最小字段集可以收成：

- `thread_id`
- `timestamp`
- `source_kind`
  - `channel_event` / `message`
- `source_id`
- `role`
  - `user` / `assistant`
- `text`
- `payload`
- `actor_id`
- `actor_display_name | None`
- `conversation_id`
- `run_id | None`

这里有两个字段的边界要写死：

- `actor_id`
  - 是稳定身份锚点
  - 用于归属、去重、关联
- `actor_display_name`
  - 是给 LLM 和人类阅读的友好名字
  - 可能来自 QQ 用户名、群昵称、备注名等展示层信息
  - 不能当作身份主键

### 5. `ThreadLtmCursor`

这是 LTM 自己维护的持久化游标状态。

它属于 LTM 自己的存储，不属于 runtime 公共存储。

最小字段可以收成：

- `thread_id`
- `last_event_id`
- `last_message_id`
- `updated_at`

其中：

- `last_event_id`
- `last_message_id`

都记录各自 store 的自增主键 / sequence，不使用时间戳做边界。

`updated_at` 只是观测字段，用于排查和调试，不参与业务判断。

这里也顺手划一条边界：

- `ThreadLtmCursor` 属于 LTM 自己的持久化状态
- 至于 LTM 内部到底是一个总 store，还是再细拆成 cursor store / memory store / dedup store，不属于这篇讨论范围

---

## 三、检索线：长期记忆怎样接回前台主线

长期记忆的使用，服务的是当前这一轮上下文，所以 retrieval 这一侧应该明确接回前台 run 主线。

这条线的正式形状是：

`ThreadPipeline -> RetrievalPlanner -> MemoryBroker.retrieve -> LongTermMemorySource -> ContextAssembler`

### 1. `ThreadPipeline` 负责把这一轮带到 retrieval 阶段

前台一次 run 开始后，`ThreadPipeline` 会先走：

- 消息准备
- working memory compaction
- retrieval 准备

这一步的意思不是“形成长期记忆”，而是：

- 当前这轮已经准备好去问各种记忆来源了

### 2. `RetrievalPlanner` 负责准备这一轮的检索现场

`RetrievalPlanner` 在这里负责的，是把这轮 retrieval 用到的现场收出来。

它收的东西主要是：

- 当前 run 的 query text
- `thread_id`
- `actor_id`
- `conversation_id`
- retained history
- working summary
- 其他 retrieval 相关的上下文信息

这一层回答的是：

- 当前这一轮是谁在问
- 当前这一轮在什么场景里问
- 当前这一轮还保留着哪些短期上下文

### 3. `MemoryBroker` 负责统一调用各个记忆来源

`MemoryBroker` 在 retrieval 这一侧仍然是统一入口。

它负责：

- 接住当前 run 的 retrieval 上下文
- 向所有已注册的 memory source 发请求
- 收集它们返回的 `MemoryBlock`
- 做最小的标准化和失败隔离

它不负责：

- 形成长期记忆
- 决定要不要写长期记忆
- 决定长期记忆内部怎么命中

在这条线里，`MemoryBroker` 的身份就是：

- retrieval broker

### 4. 长期记忆组件以 `Source` 身份接进来

长期记忆组件接回前台主线时，不是以“后台分析器”的身份接，而是以 `Source` 身份接。

也就是说，长期记忆组件需要暴露一个 retrieval 面：

- `LongTermMemorySource`

它收到 retrieval request 后，自己决定：

- 这轮要不要返回内容
- 从自己的长期记忆存储里取哪些内容
- 这些内容怎么转成 `MemoryBlock`

然后把结果交给 `MemoryBroker`。

### 5. `ContextAssembler` 负责把长期记忆排进最终上下文

长期记忆的检索结果最终不会直接拼进 prompt 字符串里，而是先变成 `MemoryBlock`，再交给 `ContextAssembler`。

`ContextAssembler` 只关心：

- 这块内容放到哪个 slot
- 优先级是多少
- 在整体上下文里排在哪里

它不需要知道：

- 这块内容是不是 SimpleMem 生成的
- 这块内容是怎么分析出来的
- 长期记忆内部用的是什么存储

所以检索线可以直接收成一句话：

> 长期记忆读取看当前 run，并通过 `MemoryBroker -> MemoryBlock -> ContextAssembler` 接回前台主线。

---

## 四、长期记忆组件在系统里的最终形状

如果按这套边界继续往下长，一个长期记忆组件更适合拆成下面两个面。

### 1. `LongTermMemoryIngestor`

它负责写入线：

- 对外暴露 `start() / stop() / mark_dirty(thread_id)`
- 接收 `mark_dirty(thread_id)` 信号
- 维护 `dirty_threads`
- 维护 worker 生命周期
- 读取每个 thread 的 `last_event_id / last_message_id`
- 通过 `ConversationFactReader` 读取统一的增量事实窗口
- 自己分析哪些内容要保留
- 自己做区间去重 / 全局去重
- 写入自己的长期记忆存储

### 2. `LongTermMemorySource`

它负责检索线：

- 接收 retrieval request
- 从自己的长期记忆存储中查相关材料
- 转成 `MemoryBlock`
- 在 retrieval 阶段交回前台主线

这样一个长期记忆组件，既不需要侵入前台 pipeline，也不需要让前台 runtime 理解它内部的算法和存储。

---

## 五、把这两条线画成一张最小装配图

### 写入线

```text
RuntimeApp --(event 落盘成功)--> LongTermMemoryIngestor.mark_dirty(thread_id)
Outbox     --(message 落盘成功)-> LongTermMemoryIngestor.mark_dirty(thread_id)

LongTermMemoryIngestor
  -> dirty_threads(Set[thread_id])
  -> load last_event_id / last_message_id
  -> ConversationFactReader.get_thread_delta(...)
  -> LongTermMemoryStore
  -> success 时推进双游标
```

### 检索线

```text
ThreadPipeline
  -> RetrievalPlanner
  -> MemoryBroker.retrieve
      -> LongTermMemorySource
      -> other memory sources
  -> ContextAssembler
  -> ModelAgentRuntime
```

---

## 最后把最终边界收成一句话

在 AcaBot 里，长期记忆和现有框架的交互方式应该是：

> **写入线由前台在事实落盘后做 `mark_dirty(thread_id)`，再由 LTM 自己读取事实层形成长期记忆；检索线再通过 `MemoryBroker` 以 `Source` 的身份接回当前 run。**

更短一点就是：

- **写的时候看事实流**
- **读的时候看当前 run**
