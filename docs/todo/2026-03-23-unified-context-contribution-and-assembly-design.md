# 2026-03-23 统一上下文条目与组装设计

这份文档定义前台 bot 进入模型前的正式上下文主线。

后续实现时，以这份文档为准。现有和它相关的讨论文档可以保留，但它们属于讨论记录，不再承担最终设计职责。

---

## 开头先记下这次已经达成的共识

下面这些点，是这次讨论里已经收清楚的共识，后面设计直接建立在这些共识上。

### 1. 真正要统一的不是字符串，而是上下文条目

系统里真正要统一的对象，不是 `ctx.system_prompt` 和 `ctx.messages` 这两个最终字段，而是“会进入上下文的每一条内容”。

也就是说，设计重点不是再找一个地方拼字符串，而是先把各个来源变成统一的上下文条目，再由一个正式组件完成最终组装。

### 2. `ContextAssembler` 不能只是接 field 的拼接器

如果 `ContextAssembler` 只是接收几段 field，再把它们拼成最终 prompt，那它只是一个后置 formatter，不是真正的上下文装配中心。

正式设计里，`ContextAssembler` 应该负责：

- 接收上游材料
- 统一转成 `ContextContribution`
- 再组装最终的 `system_prompt` 和 `messages`

### 3. `MemoryBroker` 继续保留，但只负责记忆读取

`MemoryBroker` 仍然是前台记忆来源的统一入口，但它只负责“读哪些记忆、怎么读出来”，不负责最终 prompt 装配。

它管理的范围包括：

- `/self`
- sticky note
- 长期检索记忆

它不管理：

- thread working memory
- 聊天记录
- 最终上下文排序

### 4. `RetrievalPlanner` 是先做计划，不是自己去取记忆

`RetrievalPlanner` 和 `MemoryBroker` 的关系：

- `RetrievalPlanner`
  - 根据当前消息、scope、thread、session 等信息，决定本轮该查哪些记忆来源，以及分别带什么条件去查
- `MemoryBroker`
  - 按这个计划，真的去对应记忆来源里把内容取出来

### 5. `context_labels` 默认不进入模型上下文

session 里的 `context_labels` 更像控制面标签、调试标签，不是给模型看的正文内容。

所以默认不进入正式模型上下文。

它们更适合留在：

- `ctx.context_decision`
- trace
- WebUI 调试面

### 6. session 不再保留“直接注入模型正文”的万能入口

session 侧不再保留类似 `prompt_slots` 这种“可以直接往模型正文塞内容”的通用入口。

如果 session 配置里需要表达不同语义，应该分别落到正式边界里：

- 场景标签
  - 留在 `context_labels`
- 记忆选择条件
  - 进入 `RetrievalPlanner`
- 全局或场景规则
  - 进入正式 prompt 配置，而不是临时上下文入口

### 7. `working_summary` 和保留下来的历史不是一回事

这两个概念已经分清楚：

- `working_summary`
  - 更早的历史被压缩后形成的一段摘要
- `retained_history`
  - 压缩之后仍然保留下来的历史消息

之前文档里写的 `compressed history` 容易让人误解，后面统一改成 `retained_history`。

### 8. 当前轮用户消息要区分 `history_text` 和 `model_content`

当前轮用户输入有两种用途：

- `history_text`
  - 写入 thread working memory
- `model_content`
  - 作为真正发给模型看的当前轮用户消息

如果当前轮消息有图片、引用、附件说明等内容，`model_content` 可能是多模态结构，而不是纯文本。


---

## 目标

这次要收好的不是某一个字符串拼接点，而是整条“模型可见上下文”的生产链。

最终目标有 4 个：

1. 所有会进入模型的上下文，都先变成统一的 `ContextContribution`
2. `ctx.system_prompt` 和 `ctx.messages` 只表示最终结果，不再复用为中间态
3. 记忆选择、记忆读取、最终组装三件事拆开，边界清楚
4. 后面不管是做 payload JSON、WebUI 调试面，还是做上下文可观测性，都建立在同一个模型上

---

## 最终主线

前台正式主线收成下面这条：

```text
ThreadPipeline
  -> RetrievalPlanner.prepare()
  -> MemoryBroker.retrieve()
  -> ModelAgentRuntime
       -> PromptLoader.load()
       -> ToolRuntimeResolver.resolve()
       -> ContextAssembler.collect_contributions(...)
       -> ContextAssembler.assemble(...)
       -> PayloadJsonWriter.write(...)
       -> BaseAgent.run(...)
```

每个组件的职责如下：

- `ThreadPipeline`
  - 准备 thread、message projection、compaction 结果这些上游材料
- `RetrievalPlanner.prepare()`
  - 计算本轮要查哪些记忆来源，以及各自的查询条件
- `MemoryBroker.retrieve()`
  - 真正去 `/self`、sticky note、长期检索记忆 这些来源里取结果
- `ContextAssembler`
  - 把上游材料统一转成 `ContextContribution`
  - 再组装最终 `system_prompt` 和 `messages`
- `ModelAgentRuntime`
  - 在调模型前完成最后接线，并写 payload JSON

---

## 上下文来源

这次正式进入上下文主线的来源，先收成下面这些：

- base prompt
- skill reminder
- subagent reminder
- `/self`
- sticky note
- 长期检索记忆
- working summary
- retained history
- 当前轮 user message 的 `model_content`

下面这些先不进入模型上下文：

- session context labels
- workspace state

---

## 核心数据对象

## `ContextContribution`

```python
@dataclass(slots=True)
class ContextContribution:
    source_kind: str
    target_slot: str
    priority: int
    role: str
    content: str | list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)
```

字段语义如下：

- `source_kind`
  - 这条上下文属于哪类来源
- `target_slot`
  - 这条内容最后要落到哪个正式槽位
- `priority`
  - 同一个槽位内部的排序优先级，数字越大越靠前
- `role`
  - 如果这条内容进入 `messages`，它对应的消息角色
- `content`
  - 真正给模型看的内容
- `metadata`
  - 其他补充信息，比如 scope、memory_type、history_index、来源文件等

---

## `source_kind` 正式枚举

第一阶段先固定这些正式值：

- `base_prompt`
- `skill_reminder`
- `subagent_reminder`
- `self_memory`
- `sticky_note`
- `retrieved_memory`
- `working_summary`
- `history_message`
- `current_user_message`

后面新增来源时，沿这个枚举继续扩。

---

## `target_slot` 正式语义

第一阶段只保留 4 个正式槽位：

- `system_prompt`
  - 最终 system prompt 本体
- `message_prefix`
  - 放在历史消息前面的模型可见上下文
- `message_history`
  - 保留下来的历史消息
- `message_current_user`
  - 当前轮真正发给模型看的用户消息

最终 `messages` 的结构固定为：

1. `message_prefix`
2. `message_history`
3. `message_current_user`

其中：

- `/self`
- sticky note
- working summary
- retrieval memory

这些都属于 `message_prefix`。

---

## 最终结果对象

## `AssembledContext`

```python
@dataclass(slots=True)
class AssembledContext:
    system_prompt: str
    messages: list[dict[str, Any]]
```

这就是最终真正发给模型的上下文结果。

它只保留：

- `system_prompt`
- `messages`

它不负责承载调试条目、source map 或中间态信息。

如果后面需要更强的可观测性，再单独引入 trace 对象。

---

## 组件职责

## `ThreadPipeline`

`ThreadPipeline` 继续负责准备运行现场，但不再负责组装最终模型输入。

它负责准备：

- `ctx.message_projection`
- `ctx.retrieval_plan`
- compaction 结果
- thread working memory

它写入 thread working memory 时，继续使用 `history_text`。

它不再负责：

- 把 `ctx.messages` 当中间态反复改写
- 拼最终前缀上下文
- 决定最后发模型的消息顺序

---

## `RetrievalPlanner`

`RetrievalPlanner` 只保留 `prepare()`。

它负责：

- 计算 `requested_scopes`
- 计算 `requested_memory_types`
- 计算 `requested_tags`
- 计算 sticky note 的读取范围
- 把 compaction 结果收成 retrieval plan

它的定位不是“真正检索记忆”，而是“本轮记忆选择器”。

它不负责：

- 真的去读记忆来源
- 最终 prompt 组装

---

## `MemoryBroker`

`MemoryBroker` 是前台记忆来源的统一读取入口。

它负责：

- 接收 retrieval plan
- 调用不同记忆来源
- 收集读取结果
- 统一发出 write-back request

这次明确纳入它管理范围的记忆来源有：

- `/self`
- sticky note
- 长期检索记忆

它不负责：

- thread working memory
- 聊天记录
- 最终上下文排序
- 最终 prompt 组装

第一阶段它产出的结果可以继续沿用 `MemoryBlock`，但语义上要正式区分：

- `self_memory`
- `sticky_note`
- `retrieved_memory`

---

## `ContextAssembler`

`ContextAssembler` 是最终模型上下文的唯一装配入口。

它负责两步：

1. 把上游材料统一转成 `ContextContribution[]`
2. 把这些 contribution 组装成最终 `AssembledContext`

只有它可以写：

- `ctx.system_prompt`
- `ctx.messages`

---

## `ModelAgentRuntime`

`ModelAgentRuntime` 负责进入模型前的最后接线：

1. 解析 `tool_runtime`
2. 加载 `base_prompt`
3. 调用 `ContextAssembler`
4. 把 `AssembledContext` 写回 `ctx`
5. 在真正调用 `BaseAgent.run(...)` 前写 payload JSON
6. 调模型

`ModelAgentRuntime` 不再自己拼最终 system prompt。

---

## 来源到 `ContextContribution` 的正式映射


| 来源                       | 上游字段                                                       | `source_kind`          | `target_slot`          | 说明                            |
| ---------------------------- | ---------------------------------------------------------------- | ------------------------ | ------------------------ | --------------------------------- |
| base prompt                | `PromptLoader.load(ctx.profile.prompt_ref)`                    | `base_prompt`          | `system_prompt`        | 人格设定和主 prompt 的正式入口  |
| skill summaries            | `tool_runtime.metadata["visible_skill_summaries"]`             | `skill_reminder`       | `system_prompt`        | skill 摘要提醒                  |
| subagent summaries         | `tool_runtime.metadata["visible_subagent_summaries"]`          | `subagent_reminder`    | `system_prompt`        | 子代理摘要提醒                  |
| `/self`                    | `MemoryBroker.retrieve()` 结果                                 | `self_memory`          | `message_prefix`       | bot 自我连续性上下文            |
| sticky note                | `MemoryBroker.retrieve()` 结果                                 | `sticky_note`          | `message_prefix`       | 稳定、按 scope 注入的长期笔记   |
| retrieval memory           | `MemoryBroker.retrieve()` 结果                                 | `retrieved_memory`     | `message_prefix`       | 按需检索记忆                    |
| working summary            | `ctx.retrieval_plan.metadata["working_summary_text"]` 等回退链 | `working_summary`      | `message_prefix`       | 更早历史被压缩后的摘要          |
| retained history           | `ctx.retrieval_plan.compressed_messages` 等回退链              | `history_message`      | `message_history`      | compaction 后保留下来的历史消息 |
| current user model message | `ctx.message_projection.model_content`                         | `current_user_message` | `message_current_user` | 当前轮真正发给模型看的用户消息  |

---

## 排序规则

### 1. `system_prompt`

所有 `target_slot="system_prompt"` 的 contribution 按 `priority` 降序排序，再依次拼接。

第一阶段建议优先级：

- `base_prompt`: `1000`
- `skill_reminder`: `900`
- `subagent_reminder`: `850`

### 2. `messages`

`messages` 按槽位固定顺序生成：

1. `message_prefix`
2. `message_history`
3. `message_current_user`

每个槽位内部规则如下：

- `message_prefix`
  - 按 `priority` 降序排序
- `message_history`
  - 保持原始历史顺序
- `message_current_user`
  - 固定为最后一条 `role=user`

第一阶段建议优先级：

- `self_memory`: `850`
- `sticky_note`: `800`
- `working_summary`: `700`
- `retrieved_memory`: `600`

---

## 当前轮用户消息的正式规则

当前轮用户输入继续保留两份语义：

- `history_text`
  - 写入 thread working memory
- `model_content`
  - 作为最终 `message_current_user`

这条规则很重要，因为它明确分开了：

- thread/history 用的文本版本
- 真正发给模型看的输入版本

以后不再通过反向改写 `ctx.messages` 来替换最后一条 user message。

---

## payload JSON

写入时机固定为：

`BaseAgent.run(...)` 前一刻

第一阶段建议记录：

- `model`
- `request_options`
- `system_prompt`
- `messages`
- `tools`
- `has_tool_executor`

如果后面确定要做更强的上下文可观测性，再单独为 payload JSON 增加 trace 内容。

---

## 迁移顺序

实现上按下面顺序最稳：

1. 新增 `ContextContribution` 和 `AssembledContext`
2. 新增 `ContextAssembler`
3. 在 `ModelAgentRuntime` 接入 `ContextAssembler`
4. 让 `ctx.system_prompt` / `ctx.messages` 只承载最终结果
5. 删除 `apply_model_message()`
6. 删除 `RetrievalPlanner.assemble()` 和前台 `PromptSlot` 组装路径
7. 把 `/self` 正式接进 `MemoryBroker`
8. 接入 payload JSON writer

---

## 最终结论

这次真正统一的对象是：

`ContextContribution`

以后前台主线只认下面这套边界：

- `RetrievalPlanner` 负责本轮该查什么
- `MemoryBroker` 负责把记忆真的取出来
- `ThreadPipeline` 负责准备 thread 和 message projection 原材料
- `ContextAssembler` 负责生成最终模型上下文
- `ModelAgentRuntime` 负责调模型前的最后接线和 payload 落盘

这样收完之后，整个上下文主线会变成：

- 记忆选择和记忆读取分开
- 中间态和最终态分开
- 真实聊天记录和前缀上下文分开
- 模型看到的内容和 thread 里保存的内容分开
