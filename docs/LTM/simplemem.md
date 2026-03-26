查看 
docs/00-ai-entry.md
docs/17-3-memory-long-term-memory.md
代码位于: /home/acacia/AcaBot/ref/SimpleMem

**SimpleMem 不是“把聊天存起来以后再搜”，而是“先把聊天压缩成标准化、可检索的原子记忆，再用多路检索把这些原子记忆捞回来，最后让模型根据这些记忆回答问题”。** 
论文把它总结成三段：
- `Semantic Structured Compression -> Recursive Consolidation -> Adaptive Query-Aware Retrieval`；

当前仓库里的主入口则更直白：
- 写入侧是 `add_dialogue() -> MemoryBuilder -> VectorStore`
- 查询侧是 `ask() -> HybridRetriever -> AnswerGenerator`
- ([arXiv](https://arxiv.org/html/2601.02553v1 "SimpleMem: Efficient Lifelong Memory for LLM Agents"))

**论文版 SimpleMem** 和 **当前仓库版 SimpleMem** 不是 100% 一样。
- 论文里第二阶段强调的是“异步递归整合”，第三阶段强调“按 query complexity 调整检索深度”；
- 而当前仓库代码更像“写入时做在线整理 + 检索时做信息需求分析、目标查询生成、可选 reflection”


## 从消息到入库

第一步，SimpleMem 的输入不是复杂对象，就是一条一条 `Dialogue`。
- 这个数据结构很薄，只有 `dialogue_id`、`speaker`、`content`、`timestamp`。
- 在主系统里，`add_dialogue()` 会把你传入的 speaker/content/timestamp 包成 `Dialogue`，然后交给 `MemoryBuilder`。包文档的最小例子也是这样用：先 `system.add_dialogue(...)` 连续塞消息，最后 `finalize()`

第二步，不是每来一条消息就立刻生成一条记忆，而是先进入 **buffer**，再按 **滑动窗口** 处理。
- 先把对话切成固定长度、带重叠的 sliding windows，再判断这个窗口是不是值得进入记忆；
- 实验配置给的是 `window size = 10 turns`，`stride = 5 turns`，也就是 50% 重叠。
- 当前代码实现里，`MemoryBuilder` 确实有 `window_size`、`overlap_size` 和 `step_size = window_size - overlap_size`，并且 `process_window()` 每次只前进 `step_size`，把尾部重叠部分留给下一个窗口。([arXiv](https://arxiv.org/html/2601.02553v1 "SimpleMem: Efficient Lifelong Memory for LLM Agents"))

- 这一步背后的原理不是“为了凑 batch”，而是为了两个目的。第一，聊天信息天然跨多轮，单条消息往往语义不完整，所以需要一个局部窗口来消解“他”“明天”“那个地方”这类上下文依赖。第二，窗口重叠能减少切边损失，避免某个事实刚好卡在两个窗口交界处时被抽取丢失。论文里把这一步叫做“Semantic Structured Compression”的前半段：先对连续交互做窗口化，再判断哪些窗口信息密度足够高。([arXiv](https://arxiv.org/html/2601.02553v1 "SimpleMem: Efficient Lifelong Memory for LLM Agents"))

第三步，窗口确定后，SimpleMem 会让 LLM 做一件很关键的事：**不是摘要，而是“提取并重写成原子记忆”**。`MemoryBuilder._generate_memory_entries()` 会把窗口内对话拼成纯文本，再把上一窗口的一小部分 `previous_entries` 作为参考上下文一起塞给 LLM，作用是“避免重复提取”。代码里这里只拿前 3 条上一窗口记忆做参考；顺序处理时每个窗口处理完，会把这批生成的 entries 放进 `self.previous_entries`，并作为下一窗口的参照。([GitHub](https://github.com/aiming-lab/SimpleMem/blob/main/core/memory_builder.py "SimpleMem/core/memory_builder.py at main · aiming-lab/SimpleMem · GitHub"))

这一步的 prompt 要求非常强硬。代码里明写了几条核心规则：
- 第一，**Complete Coverage**，要生成足够多的 memory entries，确保窗口里的信息都被覆盖；
- 第二，**Force Disambiguation**，严禁代词和相对时间，不能写 he/she/they，也不能写 yesterday/tomorrow；
- 第三，`lossless_restatement` 必须是完整、独立、可理解的一句话；
- 第四，还要顺手抽出 `keywords`、`timestamp`、`location`、`persons`、`entities`、`topic`。
- 也就是说，它追求的不是“压成短摘要”，而是“压成可检索、可独立存在的事实单元”

这正是论文里最值钱的思想：**把原始对话变成 context-independent memory units**。论文明确说，这一步包含两个关键规范化动作：一个是指代消解，一个是时间锚定。它甚至专门在消融实验里指出，去掉 atomization 之后，Temporal F1 会从 58.62 掉到 25.40，因为不再能稳定处理“相对时间 + 指代”这种对话常态。
- SimpleMem 最核心的不是“存”，而是“重写到适合以后搜”


举个最简单的例子。
- 原始聊天如果是：
	- “他明天下午两点去星巴克见 Bob。”
- SimpleMem 会重写成类似：
	- “Alice will meet Bob at Starbucks on 2025-11-16T14:00:00.”
- README 里就给了几乎这个意思的例子：输入是相对、模糊的，输出变成绝对、原子的。
- 这样一来，后面无论你问“什么时候见面”“在哪见面”“Alice 和 Bob 的会面”，它都比较容易命中。


第四步，LLM 输出的是 JSON 数组，代码会把它解析成 `MemoryEntry`。这个类就是 SimpleMem 的核心记忆单元。
- 字段非常重要：`entry_id` 是 UUID，`lossless_restatement` 是语义主体，`keywords` 给词法检索，`timestamp/location/persons/entities/topic` 给结构化过滤和辅助语义组织。
- 模型定义里直接把这三层写出来了：semantic、lexical、symbolic。



第五步，`MemoryEntry` 会被写入 `VectorStore`。
- 当前仓库用的是 **LanceDB**。
- 表 schema 里有 `entry_id`、`lossless_restatement`、`keywords`、`timestamp`、`location`、`persons`、`entities`、`topic`，再加一列 `vector`。
- 写入时会先拿所有 `lossless_restatement` 去做 embedding，然后把向量和这些结构字段一起写进去。也就是说，SimpleMem 入库不是“只进向量库”，而是“文本 + 结构字段 + 向量”一起落盘


第六步，入库以后它会建立三种检索入口。论文里把这叫 **multi-view indexing**：
- 一层是 dense semantic embedding；
- 一层是 sparse lexical index；
- 一层是 symbolic metadata。
- 当前代码里
	- dense 检索就是向量搜索；
	- lexical 检索是给 `lossless_restatement` 建 FTS 索引，然后拿关键词拼成字符串做全文搜索；
	- symbolic 检索则是按 `persons/location/entities/timestamp_range` 去构造 where 条件。
	- 这里有一个很实在的工程细节：词法检索虽然概念上叫 BM25-style keyword index，但仓库当前实现其实是 **LanceDB FTS on `lossless_restatement`**，不是单独对 `keywords` 字段建倒排索引。`keywords` 更多像是“生成查询词”的辅助信息。



## 从检索到得到结果

第一步，主系统的查询入口是 `ask(question)`。
- 代码非常直白：它先调用 `self.hybrid_retriever.retrieve(question)` 拿回一批 `MemoryEntry`，再把这些 entry 交给 `AnswerGenerator.generate_answer(question, contexts)`。
- 也就是说，检索和回答是两段式，不是“一问就直接对库搜一下然后拼接原文”


第二步，进入 `HybridRetriever.retrieve()` 后，它先看有没有开启 planning。没开的话就退化成最普通的 semantic search；开了的话，会走 `_retrieve_with_planning()`。当前仓库默认思路就是“先分析问题需要什么信息，再生成最少量的目标搜索 query”，而不是直接拿用户原句去搜一遍。


这一步的原理很好理解。用户问 “Alice 和 Bob 是什么时候在哪见面的？” 和问 “Alice 最近偏好喝什么？” 其实不是一个检索任务。前者需要时间、地点、人物三类线索同时命中；后者更像人物偏好事实查找。论文把这个抽象成 **Adaptive Query-Aware Retrieval**，说系统应该根据 query complexity 决定检索范围；当前代码版虽然没有把“复杂度分类器 + 深度 d”写成论文那个公式，但它确实会先做 **information requirements analysis**，把问题拆成 question type、key entities、required_info、relationships、minimal_queries_needed。


第三步，做完信息需求分析后，它会生成 **targeted queries**。代码里 `_generate_targeted_queries()` 的 prompt 说得很清楚：根据前一步的 `required_info` 和 `minimal_queries_needed`，生成最少量、互不重叠、各自覆盖不同信息需求的搜索 query，通常是 1 到 3 条，而且要包含原问题本身。然后这些 query 可以串行执行，也可以并行执行
- ***SimpleMem 不只是“把问句 embedding 一下”***。
- 它先问自己一句：“**回答这个问题，最少需要哪些信息块？**” 然后再把这些需求翻译成搜索动作。
- 这和普通 RAG 的最大差别就在这儿：普通 RAG 常常是一问一搜；
- SimpleMem 更像先做检索规划，再执行多路检索。


第四步，真正执行检索时，它不是只走向量检索，而是 **三路并行/并行可选的混合检索**。
- 第一路是 semantic search。代码里 `_semantic_search()` 直接调 `vector_store.semantic_search()`，***本质就是把 query 编成向量，然后在 LanceDB 里做近邻搜索***。这个适合搜“概念相近但措辞不完全一样”的东西。比如你问 “hot drink”，有机会捞到“latte”这类语义接近的记忆。论文也明确把这层定义成 semantic dense layer
- 第二路是 keyword search。这里它会先做 `_analyze_query()`，从用户问题里抽出 `keywords/persons/time_expression/location/entities`。然后 `_keyword_search()` 会取其中 `keywords`，如果抽不出来就退回整句 query，再走 `vector_store.keyword_search()`。而 `keyword_search()` 在当前代码里实际上是用这些关键词去做 FTS 搜索。这个适合命中人名、地点名、产品名、报错串这类“不能被语义空间稀释”的内容。
- 第三路是 structured search。`_structured_search()` 会根据 query analysis 里的 `persons/location/entities/time_expression` 构造过滤条件。时间表达式会先用 `_parse_time_range()` 变成绝对时间范围；然后在 `VectorStore.structured_search()` 里拼 where 子句，比如 `array_has_any(persons, ...)`、`location LIKE ...`、实体数组匹配，以及 `timestamp >= start AND timestamp <= end`。这一层特别适合“谁、在哪、什么时候”的硬条件约束。


第五步，三路结果会被合并，然后按 `entry_id` 去重。代码里的 `_merge_and_deduplicate_entries()` 就是用 `entry_id` 做 seen set。也就是说，同一条 memory entry 如果同时被语义检索、关键词检索、结构化检索命中，只会留下一个


第六步，如果开启了 reflection，检索不会在第一轮结束。当前仓库支持两种“再找一轮”的逻辑：一种是旧的 `_retrieve_with_reflection()`，一种是更智能的 `_retrieve_with_intelligent_reflection()`。后者会根据前面那份 `information_plan`，检查当前结果是否已经覆盖 `required_info`；如果不够，就再生成补充查询，继续走语义搜索，然后再合并去重。这一步本质上是在做“**检索结果是否足够回答问题**”的自检。


所以到这里，`HybridRetriever` 的输出不是答案，而是一组相对干净的 `MemoryEntry`。这些 entry 已经经过了：计划、目标查询生成、语义检索、词法检索、结构过滤、去重、可选补搜。你可以把它看成是 “answer-ready context set”


第七步，`AnswerGenerator` 负责最后一跳。它会把每条 `MemoryEntry` 格式化成带 `Content/Time/Location/Persons/Related Entities/Topic` 的上下文块，再给 LLM 一个很简单的 prompt：**只根据这些上下文回答问题，回答要很简洁，输出 JSON，其中包含 `reasoning` 和 `answer`**。如果没有检索到任何上下文，就直接返回 “No relevant information found”


注意这一步的定位。它不是再去“理解整段原聊天”，而是只吃已经标准化过的 memory units。也就是说，SimpleMem 的回答质量，很大程度取决于前面写入时 `lossless_restatement` 写得好不好、检索时三路合并是否把关键 facts 捞到了。**生成答案本身反而是最薄的一层。** 这也是为什么我前面一直说，SimpleMem 的灵魂不在 answer generation，而在“写入时怎么把记忆变成检索友好的形态”


如果把检索线再压成一句话，就是：
- **先分析“回答这个问题需要什么信息”，再生成最少量的目标查询；然后同时走语义、词法、结构化三路召回；必要时补搜；最后把命中的原子记忆交给一个很薄的 AnswerGenerator 来合成答案。** ([GitHub](https://github.com/aiming-lab/SimpleMem/blob/main/core/hybrid_retriever.py "SimpleMem/core/hybrid_retriever.py at main · aiming-lab/SimpleMem · GitHub"))

## 论文和代码差异
现在讲你最该注意的部分：**论文版和仓库版到底哪里不一样。**

第一，论文第二阶段写的是 **Recursive Consolidation**。论文说系统会根据语义相似度和时间接近度计算 affinity，把形成稠密簇的 memory units 异步整合成更高层抽象表示，从而减少长期冗余。它明确把这说成一个 **asynchronous background consolidation process**。但当前仓库主线代码里，你能看到的“整合”主要是两件事：一是窗口重叠，二是把上一窗口少量 `previous_entries` 当提示上下文避免重复；README 甚至直接把这一阶段写成 “Online Semantic Synthesis during write”。所以，**论文里的第二阶段更重、更像后台维护；仓库里的第二阶段更轻、更像写入期在线整理。** 

第二，论文第三阶段里有一个更明确的“query complexity -> retrieval depth d”设定。论文附录甚至把 planner prompt 写得很像分类器：LOW 表示单事实查找，HIGH 表示需要跨事件、多跳、时间比较，然后按复杂度动态调深度。当前仓库代码没有把这个“复杂度分类器 + 明确深度范围”直挺挺实现出来，而是换成了“information requirements analysis + targeted queries + optional reflection”。这两者精神是接近的，但实现形态已经不同了。


第三，论文里的 memory 设计更像一个长期维护的记忆拓扑；但当前仓库实现有一个明显工程缺口：**缺 provenance**。我这里说的是根据代码做的直接推断：`dialogue_ids` 会一路从 `_generate_memory_entries()` 传到 `_parse_llm_response()`，但真正创建 `MemoryEntry` 时，并没有任何 source 字段；`MemoryEntry` 模型和 LanceDB schema 也都没有 source span、source dialogue ids 之类的列。所以当前仓库更像“压缩记忆库”，而不是“可追溯、可审计、可精确删除的记忆系统”。这是你以后自己实现时很值得补上的地方。


第四，论文和代码的实验/实现细节也有一些不一致。论文实验表里 Stage 1 用的是 `window size 10 / stride 5 / threshold 0.35 / gpt-4o-mini`，Stage 2 的 embedding 模型是 `text-embedding-3-small`，存的 metadata 里还提到了 `salience`；但当前仓库/包文档默认环境变量里写的是 `SIMPLEMEM_EMBEDDING_MODEL = Qwen/Qwen3-Embedding-0.6B`，而当前 `MemoryEntry` 和表 schema 也没有 `salience` 字段。也就是说，**论文给的是研究设定，仓库给的是可跑实现，它们不是逐字段一比一。** 


所以，真正把 SimpleMem 吃透以后，你脑子里应该留下的不是一堆类名，而是这四个本质。
- 第一，**写入时就要做“面向未来检索”的改写**，而不是事后再想办法从原聊天里捞。
- 第二，**记忆单元要原子、独立、可消歧、可带结构字段**。`lossless_restatement + keywords + timestamp/location/persons/entities/topic` 这个组合就是它的基本配方。
- 第三，**检索不能只靠 embedding**。SimpleMem 真正强的地方是 semantic / lexical / symbolic 三层一起上。
- 第四，**回答不是核心，核心是“把对的记忆以对的形态捞回来”**。AnswerGenerator 很薄，MemoryBuilder 和 HybridRetriever 才是重头戏。


