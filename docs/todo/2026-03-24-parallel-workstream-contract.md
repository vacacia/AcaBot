# 2026-03-24 并行开发协作契约

这份文档是给 3 条并行开发线用的约束说明：

1. 上下文主线重构
2. 长期记忆接入
3. 前端 Memory UI

目标只有一个：三者可以并行推进，但不要互相改同一层语义，不要围着正在删除的旧结构继续做设计，也不要把还没稳定的内部实现当成外部契约。



---

## 适用范围

这份文档约束的是“并行开发阶段”的边界，不是最终架构解释文档。

真正的主设计仍然以这两份文档为准：

- `docs/todo/2026-03-23-unified-context-contribution-and-assembly-design.md`
- `docs/superpowers/plans/2026-03-24-unified-context-assembly.md`

如果这份协作文档和上面两份文档冲突，以上面两份为准。

---

## 先锁死的共识

下面这些点，三条开发线都必须当成稳定前提：

- `ContextAssembler` 是唯一的最终上下文组装中心。
- `ctx.system_prompt` 和 `ctx.messages` 只表示最终结果，不再当中间态。
- `RetrievalPlanner` 负责 `prepare()`，也就是决定“查什么”；它不再负责最终 prompt assembly。
- `MemoryBroker` 负责“真的去读哪些记忆来源”；它不负责最终上下文排序。
- `/self`、sticky note、长期记忆都属于 `MemoryBroker` 后面的外部记忆来源。
- `session prompt slots` 是旧设计残留，正在删除。新的前端和新的长期记忆都不要再围绕它设计。
- Memory UI 第一版只设计 3 层：
  - `self`
  - `sticky notes`
  - `长期记忆`

---

## 三条线的 ownership

### 1. 上下文主线重构 agent

这条线是当前主线 owner，负责把旧的 prompt-slot / message-rewrite 路径收掉。

这条线拥有的热点文件：

- `src/acabot/runtime/context_assembly/*`
- `src/acabot/runtime/model/model_agent_runtime.py`
- `src/acabot/runtime/pipeline.py`
- `src/acabot/runtime/inbound/message_preparation.py`
- `src/acabot/runtime/contracts/context.py`
- `src/acabot/runtime/contracts/__init__.py`
- `src/acabot/runtime/memory/retrieval_planner.py`
- `src/acabot/runtime/memory/memory_broker.py`
- `src/acabot/runtime/bootstrap/builders.py`
- `src/acabot/runtime/bootstrap/__init__.py`
- `src/acabot/runtime/bootstrap/components.py`
- `src/acabot/runtime/soul/source.py`

其他两条线在并行阶段默认不要碰这些文件。

如果确实必须碰，先把改动缩成“最小 additive patch”，并且以主线 agent 的分层为准，不能倒回旧模型。

### 2. 长期记忆 agent

这条线的任务不是直接修改 `ContextAssembler`，而是把“长期记忆”这条能力做成一个能和当前主线稳定对接的记忆来源。

它应该优先新建自己的目录和测试，不直接改主线上下文文件。

推荐写入范围：

- `src/acabot/runtime/memory/long_term/*`
- `tests/runtime/test_long_term_memory_*.py`
- 如有必要，再加一份自己的说明文档

这条线不拥有：

- `ContextAssembler`
- `ModelAgentRuntime`
- `ThreadPipeline`

但它需要给前端提供长期记忆这一层的正式数据契约，保证 WebUI 可以稳定消费。

### 3. 前端 Memory UI agent

这条线的任务是把 Memory 页收成 3 层结构，并理解“当前 session config 的结构”，不是等待长期记忆后端完全落地。

推荐写入范围：

- `webui/src/views/MemoryView.vue`
- `webui/src/views/SessionsView.vue`
- `webui/src/lib/api.ts`
- `webui/src/components/*`
- 新增 `webui/src/components/memory/*` 这类局部组件目录也可以

这条线不拥有：

- `src/acabot/runtime/*`
- `ContextAssembler`
- `RetrievalPlanner`
- `MemoryBroker`

---

## 给长期记忆 agent 的正式约束

### 目标

长期记忆这条线在这一阶段要完成 4 件事：

1. 能作为一个新的 memory source 被 `MemoryBroker` 调用
2. 能消费 `RetrievalPlanner.prepare()` 产出的选择结果
3. 能定义给 WebUI 使用的长期记忆查询 / 列表 / 详情数据契约
4. 自己决定长期记忆底层怎么实现，包括向量数据库、索引策略、写回策略

但这份协作文档只约束它和当前主线的接口，不约束它底层具体选型。

### 它需要理解的最终上下文落点

长期记忆 agent 需要知道自己的检索结果最终会进入模型可见上下文。

当前主线设计里的稳定事实是：

- 长期记忆检索结果先作为 `MemoryBlock` 从 `MemoryBroker.retrieve()` 返回
- 后续会被主线映射成 `retrieved_memory`
- 再进入 `ContextAssembler` 的消息侧前缀上下文
- 最终落到模型输入的 `messages` 里，而不是 `system_prompt`

也就是说：

- 长期记忆 agent 必须理解自己的结果最终会被喂给模型
- 但它不负责拼最后那层 prompt 包裹格式
- 它负责的是把“长期记忆检索结果”做成稳定的 provider 输出

如果主线后续把这一段前缀上下文 materialize 成某种 `user` role 包装，那也是主线 owner 的事情，不是长期记忆 retriever 自己去拼。

### 允许依赖的正式输入契约

长期记忆 agent 应该围绕下面这些契约工作：

```python
@dataclass(slots=True)
class MemoryRetrievalRequest:
    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    channel_scope: str
    event_id: str
    event_type: str
    event_timestamp: int
    query_text: str
    working_summary: str
    requested_scopes: list[str]
    requested_memory_types: list[str]
    requested_tags: list[str]
    event_tags: list[str]
    metadata: dict[str, Any]
```

```python
@dataclass(slots=True)
class MemoryWriteRequest:
    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    channel_scope: str
    event_id: str
    event_type: str
    event_timestamp: int
    run_mode: str
    run_status: str
    user_content: str
    delivered_messages: list[str]
    requested_scopes: list[str]
    event_tags: list[str]
    metadata: dict[str, Any]
```

```python
@dataclass(slots=True)
class MemoryBlock:
    title: str
    content: str
    scope: str
    source_ids: list[str]
    metadata: dict[str, Any]
```

### 和当前 `RetrievalPlanner` / `MemoryBroker` 的对接方式

长期记忆 agent 真正需要对接的是下面这条链：

```text
ThreadPipeline
  -> RetrievalPlanner.prepare()
  -> MemoryBroker._build_retrieval_request(ctx)
  -> LongTermMemoryRetriever.__call__(request)
  -> list[MemoryBlock]
  -> ContextAssembler
```

这里面它真正要依赖的是两件事：

1. `RetrievalPlanner.prepare()` 决定本轮“该不该查长期记忆、带什么条件查”
2. `MemoryBroker` 把这些选择结果整理成 `MemoryRetrievalRequest`

所以长期记忆 agent 不应该直接依赖：

- `ctx.messages`
- `prompt_slots`
- `RetrievalPlanner.assemble()`

它应该只依赖：

- `MemoryRetrievalRequest`
- `MemoryWriteRequest`
- `MemoryBlock`

### 检索侧的正式接口

长期记忆检索的职责是：

- 收到 `MemoryRetrievalRequest`
- 按 request 中的 query / scope / tags / actor 等条件去长期库检索
- 返回统一的 `MemoryBlock[]`

推荐的最小实现形状：

```python
class LongTermMemoryRetriever:
    async def __call__(self, request: MemoryRetrievalRequest) -> list[MemoryBlock]:
        ...
```

它至少要消费这些 request 字段：

- `query_text`
- `actor_id`
- `channel_scope`
- `thread_id`
- `requested_scopes`
- `requested_memory_types`
- `requested_tags`
- `event_tags`
- `working_summary`

它至少要产出统一的 `MemoryBlock`。

推荐约定长期记忆返回的 `metadata` 里包含：

- `memory_source`: 固定为 `long_term`
- `memory_type`: 例如 `semantic` / `episodic`
- `memory_id`: 稳定 ID
- `scope_key`: 命中的 scope key
- `tags`: 标签列表
- `score`: 检索分数

这里最关键的是：

- 主线 owner 通过 `MemoryBlock.metadata` 来识别“这是长期检索记忆”
- 长期记忆 agent 不要直接返回 prompt 片段
- 也不要自己构造 `ContextContribution`

可以把实现思路参考 `simplemem` 一类方案理解：

- 来消息时，用消息内容、发送人、scope 等做 query
- 去向量库取相关 hits
- 再把 hits 变成统一的 `MemoryBlock`

向量数据库、embedding、索引切分策略、rerank 策略都属于长期记忆 agent 自己的任务，这份协作文档不限制。

### 写回侧的正式接口

如果长期记忆 agent 要做 write-back，也必须通过 `MemoryExtractor` 语义接入，而不是去改 pipeline 主线。

推荐形状：

```python
class LongTermMemoryExtractor:
    async def __call__(self, request: MemoryWriteRequest) -> None:
        ...
```

它可以自己决定写回策略，例如：

- 每个 session / thread 攒够一定数量消息后触发
- 让 LLM 做抽取和归纳
- 再写入数据库

底层怎么提取、写到哪种 DB、怎样分桶，都由长期记忆 agent 自己决定。

### 这次主线改动会不会影响长期记忆 agent

如果长期记忆 agent 只依赖上面那 3 个契约：

- `MemoryRetrievalRequest`
- `MemoryWriteRequest`
- `MemoryBlock`

那这次上下文主线重构对它的影响是可控的。

会变化的部分：

- `prompt_slots` 会被删除
- `RetrievalPlanner.assemble()` 会被删除
- `ThreadPipeline` 不再写中间态 `ctx.messages`

不会变成它阻塞点的部分：

- `RetrievalPlanner.prepare()` 仍然负责“这轮查什么”
- `MemoryBroker.retrieve()` 仍然是统一读取入口
- 长期记忆仍然通过 `MemoryBlock[]` 提供检索结果

所以长期记忆 agent 只要别依赖旧的 prompt assembly 路径，就不会被主线这次改动卡死。

### 长期记忆 agent 不能做的事

- 不能改 `ContextAssembler`
- 不能改 `ctx.system_prompt` / `ctx.messages` 的生成逻辑
- 不能往 `ThreadPipeline` 里重新塞一条 prompt assembly 路径
- 不能依赖 `prompt_slots`
- 不能假设自己拥有 `/self` 或 sticky notes 的读取权

### 并行阶段的集成规则

为了不和主线 agent 抢热点文件，长期记忆 agent 在并行阶段尽量做到：

- 新建自己的 retriever / extractor 实现
- 新建自己的测试
- 明确自己给前端的 query/list/detail response contract
- 最多只声明一个清晰的构造入口，例如：

```python
def build_long_term_memory_retriever(...) -> MemoryRetriever:
    ...
```

最终把它组合进 `MemoryBroker` 的 bootstrap wiring，交给主线集成时统一接。

也就是说，长期记忆 agent 负责“把长期记忆来源做出来”，不负责“在主线里最后怎么接电”。

---

## 给前端 agent 的正式约束

### 目标

前端这一阶段只需要完成：

1. 重新组织 Memory 页面信息架构
2. 让用户能看到三层 memory：
   - `self`
   - `sticky notes`
   - `长期记忆`
3. 理解当前 session config 的结构，避免 UI 围着快删掉的旧字段去设计

前端不需要等待：

- 长期记忆后端完全完成
- `ContextAssembler` 实现结束
- `/self` 最终所有 API 全部改名

### 当前前端应当理解的 session 结构

前端应优先以当前 `/api/sessions` 使用的 UI 形状来理解 session，而不是直接把运行时 dataclass 当成表单模型。

当前 `SessionsView.vue` 里实际消费的是这个结构：

```ts
type SessionRecord = {
  display_name: string
  thread_id: string
  channel_scope: string
  channel_template_id: string
  ai: {
    prompt_ref: string
    model_preset_id: string
    summary_model_preset_id: string
    context_management: {
      strategy: string
    }
    enabled_tools: string[]
    skills: string[]
  }
  message_response: {
    rules: Array<{
      event_type: string
      enabled: boolean
      run_mode: string
      persist_event: boolean
      memory_scopes: string[]
    }>
  }
  other: Record<string, never>
}
```

这是前端这条线现在应该看的 session 结构。

### 前端还需要知道的运行时 context 结构

底层 runtime 里 `ContextDecision` 现在长这样：

```python
@dataclass(slots=True)
class ContextDecision:
    sticky_note_scopes: list[str]
    prompt_slots: list[dict[str, Any]]
    retrieval_tags: list[str]
    context_labels: list[str]
    notes: list[str]
```

但这里有一条硬约束：

- `prompt_slots` 虽然代码里现在还在，但它是正在删除的旧字段
- 新 UI 不要围绕它设计
- 新 UI 也不要把它当成“可编辑能力”

前端如果要理解 memory 相关的 session 概念，只需要先理解：

- `memory_scopes`
- `sticky_note_scopes`
- `retrieval_tags`
- `context_labels`

其中：

- `memory_scopes` 更偏“事件写入 / 提取”的 session 侧控制
- `sticky_note_scopes` 和 `retrieval_tags` 更偏“本轮上下文检索”的控制
- `context_labels` 是控制面 / 调试标签，不是模型正文

### Memory UI 第一版的信息架构

Memory 栏第一版只收成 3 个展开子页：

1. `Self`
2. `Sticky Notes`
3. `Long-Term Memory`

推荐的前端信息架构：

- Memory 根页只负责切层级
- 每一层各有自己的列表 / 详情 / 编辑区域
- 不把三层 memory 混在一个统一编辑器里

### 前端可以依赖的现有接口语义

#### 1. Self

当前 `/api/self/*` 已经存在，但底层还是 `SoulSource` 兼容别名。

前端在并行阶段可以把它当成“self 文件浏览 / 编辑接口”来设计，不需要关心底层现在还是 soul 还是已经切到 `today.md + daily/`。

要依赖的只是这层语义：

- 可以列文件
- 可以读文件
- 可以写文件
- 后面目录结构会朝 `/self/today.md + /self/daily/*.md` 靠拢

#### 2. Sticky Notes

这个是现成接口，可以直接设计和使用：

- `/api/memory/sticky-notes/scopes`
- `/api/memory/sticky-notes`
- `/api/memory/sticky-notes/item`
- `/api/memory/sticky-notes/readonly`

#### 3. Long-Term Memory

长期记忆这一层的数据 shape，应该由长期记忆 agent 和前端 agent 共同对齐。

前端不需要等真实后端全部完成，但长期记忆 agent 应该尽早给出一个正式的 query/list/detail contract。

在真实接口还没落地前，前端可以先围绕下面这个占位 shape 设计：

```ts
type LongTermMemoryHit = {
  memory_id: string
  scope: string
  scope_key: string
  title: string
  content_preview: string
  tags: string[]
  score?: number
  source_ids: string[]
  created_at?: string
  updated_at?: string
}
```

```ts
type LongTermMemoryQueryResponse = {
    query: string
    items: LongTermMemoryHit[]
    total: number
}
```

也就是说：

- 长期记忆 agent 负责尽快把这层 contract 定下来
- 前端 agent 负责基于这层 contract 把页面结构做出来
- API 没落地时允许本地 mock
- 不要反向要求主线上下文重构先完成

### 前端 agent 不能做的事

- 不能等待 `prompt_slots` 保留下来
- 不能假设 `ContextAssembler` 会提供前端专用接口
- 不能直接改 `src/acabot/runtime/*`
- 不能把 Memory UI 和最终模型上下文 source map 绑定在一起

Memory UI 现在展示的是“记忆层”和“配置层”，不是“最终 prompt payload 调试面”。

---

## 两条并行线共同遵守的禁改区

前端 agent 和长期记忆 agent 在并行阶段都不要碰下面这些语义：

- 最终 `system_prompt` 如何生成
- 最终 `messages` 如何排序
- `ContextContribution` 的核心模型
- `/self` 与 sticky notes 的归属边界
- `prompt_slots` 的复活

如果遇到“为了方便先在 pipeline 里塞一段 prompt”这种想法，直接视为越界。

---

## 推荐的交付物

### 长期记忆 agent 的交付物

- 一套长期记忆 retriever 实现
- 可选的一套 extractor 实现
- 自己的测试
- 一份短说明，写清楚：
  - 它消费哪些 request 字段
  - 它产出什么 `MemoryBlock.metadata`
  - 它还缺什么真正的 backend 配置

### 前端 agent 的交付物

- Memory 页的 3 层结构
- `self` / `sticky notes` / `长期记忆` 的页面骨架
- 现有 session config 结构的对齐说明
- 如果长期记忆 API 还没好，就提供一个明确的 mock contract

---

## 集成顺序

推荐的集成顺序是：

1. 主线 agent 先把 `ContextAssembler` 主线和 `RetrievalPlanner.prepare()` 收稳
2. 长期记忆 agent 基于 `MemoryRetriever / MemoryExtractor` 契约提供长期记忆来源
3. 前端 agent 独立完成 Memory UI 的三层结构，不阻塞后端
4. 最后由主线集成 owner 把长期记忆 retriever 接进 broker wiring，并把前端真实接口名对齐

这里的关键原则是：

- 长期记忆 agent 提供来源能力
- 前端 agent 提供展示和交互骨架
- 最终接线和主线收口，仍由上下文主线 owner 负责

---

## 一句话版本

并行阶段里：

- 长期记忆 agent 只做 `MemoryBroker` 后面的新记忆来源
- 前端 agent 只做 Memory UI 和当前 session 结构理解
- 主线 agent 继续收 `ContextAssembler`

谁都不要去复活 `prompt_slots`，谁都不要把最终 prompt assembly 拉回 pipeline。
