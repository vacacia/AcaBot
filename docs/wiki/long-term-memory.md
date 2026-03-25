
**LTM 写入线最终设计**

- 写入是 `fact-driven + event-driven`，不是 `run-driven`
- 前台主线不负责“触发一次长期记忆提取”，只在**事实落盘成功后**顺手通知一下 LTM
- 通知方式用 `direct call`，不用 event bus
- `Store` 保持贫血，`ChannelEventStore` / `MessageStore` 只负责存取，不带副作用
- `mark_dirty(thread_id)` 发生在 `RuntimeApp` / `Outbox` 这种写入编排层
- LTM 内部自己维护一个内存 `Set[thread_id]` 作为 `dirty_threads`
- 不单独持久化 dirty 队列；进程启动时做一次 SQL 扫库，把“事实超过游标”的 thread 补回 dirty set
- 第一版只有一个 LTM worker 消费 dirty threads
- 两边落盘都打 dirty：
  - 用户/平台消息写入 `ChannelEventStore` 后打一次
  - bot 回复写入 `MessageStore` 后再打一次
- worker 被唤起后**立刻处理**，不等静默窗口
- 每个 thread 在 LTM 自己的存储里维护两根持久化游标：
  - `last_event_id`
  - `last_message_id`
- 游标记录的是两边各自的**自增主键 / sequence**，不是时间戳
- runtime 提供一个很薄的 `ConversationFactReader` 只读接口，负责：
  - 从 `ChannelEventStore` 拉 `event_id > last_event_id` 的增量
  - 从 `MessageStore` 拉 `message_id > last_message_id` 的增量
  - 合并成统一的“增量事实窗口”
- 合并顺序按：
  - 先 `timestamp`
  - 相同时间再按 `(source_kind, source_id)` 做稳定排序
- runtime 只负责把这段**增量事实窗口**交给 LTM
- LTM 自己决定是否回看更早上下文，自己做提取、区间去重、全局去重、落到自己的长期记忆存储
- 只有当这次写入成功时，LTM 才推进两根游标
- 如果 LTM 写入失败：
  - 不推进任何游标
  - thread 保持 dirty
  - 不主动重试，等下次新信号来了再一起拉
- `mark_dirty()` 失败不影响前台主线：
  - 事实已经落盘就是成功
  - dirty set 是派生状态
  - 启动扫库会补回来

一句话压缩就是：

> `RuntimeApp / Outbox` 在事实落盘后只负责 `mark_dirty(thread_id)`；  
> LTM 自己维护 dirty set、双游标、消费 worker，并通过 runtime 提供的薄 `ConversationFactReader` 拉取“增量事实窗口”来形成长期记忆。

---

run_id： Observability（可观测性）外键


## 6 个核心对象

1. **不能拖慢回复**
2. **绝对不能漏记**
3. **两边数据脱节**：用户的消息存在 `ChannelEventStore`，Bot 的回复存在 `MessageStore`，而供大模型提取的记忆必须是一段“你一句我一句”的完整对话流。
4. **灵活可控**：LTM 功能只是一个插件（或可选模块），绝对不能和核心代码发生强依赖。

基于 **CDC (Change Data Capture)** 与 **最终一致性** 的体系

### 1. 信号守门人：`LongTermMemoryIngress` (或`LongTermMemoryIngestor`)
**【应对需求】：前后台极速解耦，不拖慢回复。**
* **它是做什么的**：它是前台主线（Runtime）看得到的**唯一入口**。主线只要把消息保存到数据库，转手拍一下它的门 `mark_dirty(thread_id)` 就可以去接别的活儿了。
* **它的职责**：作为一个纯异步、纯内存的阀门，它把源源不断的 `dirty` 信号收拢进一个 Set 中，唤醒后台 Worker。零副作用，瞬间完成，绝对不卡主线。

### 2. 后台消化：`LongTermMemoryIngestor` (的核心 Worker)
**【应对需求】：可靠消费、失败重试与系统防崩溃。**
* **它是做什么的**：它是在后台无限循环的消费者。每当感知到有线程脏了，它就默默接管脏掉的 `thread_id`，去拉取增量，调用模型提取，写进向量库，最后更新游标。
* **它的职责**：它是整个 LTM 流水线的**总编排者 (Orchestrator)**。遇到模型提取失败时，它懂得“不抛异常、不写死游标、等下一次补救”；它还负责系统启动时，发出扫库指令，把历史遗留的僵尸线程捞回消化池（对付崩溃和中断）。

### 3. 数据隔离的结界：`ConversationFactReader`
**【应对需求】：两边数据脱节（群聊、双数据库问题）；底层 Schema 隐私。**
* **它是做什么的**：它是 Runtime 提供给 LTM 的**翻译官**。LTM Ingestor 只管伸手要“这个线程从某某点位到现在的话”，而 Reader 负责去脏活累活：翻阅 `ChannelEventStore`、翻阅 `MessageStore`，把双层数据打平、按时间搓揉、排序，最后整理成人类可读的对话流。
* **它的职责**：防腐层（Anti-Corruption Layer）。有了它，LTM 组件永远不需要知道 AcaBot 底层到底是怎么存消息的，哪怕明天你把 SQLite 换成 MySQL，LTM 的代码连标点符号都不用改。

### 4. 极致打包的货物：`ConversationDelta`
**【应对需求】：彻底消除系统内部的逻辑越权和各种边界崩溃（无发言、纯Bot发言等）。**
* **它是做什么的**：它是 `ConversationFactReader` 产出的“增量批次包裹”。包裹里不仅塞满了 `facts`（事实），上面还极其贴心地贴了张纸条：“老板，这包货里面的最大单号我帮你算好了，是 `max_event_id=105`，`max_message_id=99`”。
* **它的职责**：Payload + Next Cursor 模式的最佳实践。它让 `Ingestor` 彻底变成了瞎子和傻子：Ingestor 拿到货，喂给模型，成功后，**无脑照抄纸条上的号码去做存档（移动游标）**，完全不用费力去解析和遍历里面的事实。

### 5. 高维度的绝对坐标：`ConversationFact`
**【应对需求】：精准的大模型提取、多租户（群聊/不同房间）的精准归属。**
* **它是做什么的**：这是包裹里的每一件实体商品。它被高度抽象，去除了复杂的平台原始报文，只保留：这是什么时候（`timestamp`）、谁说的（`role/actor_id`）、在哪里说的（`thread_id/channel_scope`）、说了啥（`text`）。
* **它的职责**：它是 LLM 的饲料。它所独有的 `source_kind` 配合时间戳，作为 Tie-breaker，保证了即便是毫秒级并发，这些事实排列出来的顺序也和现实完全一致，让 LLM 能看到因果分明的历史。

### 6. 世界的锚点：`ThreadLtmCursor`
**【应对需求】：绝对不能漏记，重启不丢，防范脑裂与异常重影。**
* **它是做什么的**：它是每个线程专属的**记忆进度条（书签）**，里面记录着：这个线程的事实，我查看到哪一页了（`last_event_id/last_message_id`），以及我最后一次看它是什么时候（`updated_at`）。
* **它的职责**：它是这套弱一致性系统能正常跑下去的**真理之源（Source of Truth）**。这根进度条不保存在短暂的内存里，它坚如磐石地写在落地的介质里。有了它，“重启扫库补偿”、“优雅停止截断”、“防灾防泄漏”这些高级功能，才有了物理基础。

---
**一句话总结：**
前台丢下一个信号 (`Ingress`)，后台 (`Ingestor`) 醒来阅读进度条 (`ThreadLtmCursor`)，请翻译官 (`ConversationFactReader`) 打包出一个带有新进度条的对话包裹 (`ConversationDelta`)，包裹里装满统一格式的历史事实 (`ConversationFact`)，最后送给大模型吃掉，更新进度条，循环往复。