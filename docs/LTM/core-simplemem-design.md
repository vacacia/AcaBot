# AcaBot Core SimpleMem Design
先看:
docs/00-ai-entry.md
docs/superpowers/plans/2026-03-25-sticky-note-refactor.md
这一页只记录已经拍板的 Core SimpleMem 设计结论。

## 已确认决定

1. AcaBot 的这一轮 LTM 目标明确是 `Core SimpleMem`，不是 `SimpleMem-lite`。也就是说，目标不是先做一个只有 FTS 或 metadata filter 的弱化版替身，而是朝“原子记忆写入 + 混合检索 + query-aware retrieval”这条正式主线设计。
2. 当前讨论范围只收在 `LTM 内部设计`。这轮先不展开 runtime 主线怎么重构、字段名最终怎么收束、以及别的 memory layer 怎么统一抽象。
3. 对外部 runtime 的要求先收窄到“接口形状能挂上现有插槽”即可。也就是说，现阶段只要求写侧能挂到 `LongTermMemoryWritePort`，读侧能挂到 `MemorySource`；至于部分字段在重构中暂时不完全对齐，不作为当前 LTM 内部设计的阻碍。
4. Core SimpleMem 后续文档和设计表述统一跟随 [00-ai-entry.md](/home/acacia/AcaBot/docs/00-ai-entry.md) 的全局命名约束，不再把正式术语写成 `channel`。
5. 如果是在表达“消息发生在哪个对话容器里”或“记忆归属在哪个对话容器下”，正式术语统一写成 `conversation_id`。
6. 因此，后续如果要表达“按对话容器建长期记忆”，正式写法是“按 `conversation_id` 组织的记忆”，不再写 `channel-local memory`、`channel scope`、`channel memory` 这一类说法。
7. Core SimpleMem 的正式记忆归属范围，确定为 `conversation_id`，不按 `thread_id` 建独立长期记忆。
8. 这意味着同一个对话容器里的多次对话，会沉淀到同一套长期记忆里；`thread_id` 仍然可以出现在 provenance 或运行时边界里，但不作为长期记忆的正式归属主键。
9. 因此，后续写入、检索、去重、以及内部索引分区，默认都先以 `conversation_id` 作为第一层边界来思考。
10. Core SimpleMem 拥有自己的正式记忆对象 `MemoryEntry`，不复用通用 `MemoryItem` 或别的外层通用记忆壳子作为正式内部对象。
11. 这意味着原子化提取出来的结果，会直接以 `MemoryEntry` 的身份进入后续的存储、索引、去重和检索流程，而不是先被压扁成一段普通文本再塞进别的通用模型。
12. `MemoryEntry` 和 AcaBot 的交接边界保持清楚：对内它是 Core SimpleMem 的正式真对象；对外只要求它能通过适配层接到 AcaBot 现有 runtime 插槽，而不是要求 AcaBot 全局都改成直接理解 `MemoryEntry`。
13. `MemoryEntry` 正式带 `provenance`，不把来源追踪留到以后再补。
14. 这意味着一条原子记忆写进去之后，系统内部仍然能明确知道它是根据哪些原始对话事实提取出来的，而不是只剩一条改写后的结论文本。
15. `provenance` 是 Core SimpleMem 的正式能力之一。后续排查抽取错误、定向删除、重建记忆、或解释某条记忆为什么存在，都建立在这条能力之上。
16. `provenance` 只记来源引用，不存来源文本快照。
17. 事实层 `ChannelEventStore + MessageStore` 是稳定、不可变的真源，LTM 不重复保存证据正文；需要展示证据时，直接通过来源引用回到事实层动态读取和渲染。
18. Core SimpleMem 的边界明确收成一句话：`LTM 负责总结（归纳），事实库负责留存证据（真源）`。
19. `provenance` 采用细粒度设计，每条 `MemoryEntry` 都正式保存自己依赖的 `fact_ids`，而不是只记录一个粗粒度的窗口范围或批次范围。
20. 这意味着一条长期记忆和它的原始事实证据之间，存在明确的一跳关联；后续 WebUI、Debug 页面、审计工具都可以从一条记忆直接回到生成它的那几条原始对话事实。
21. 这种细粒度 `fact_ids` 设计是可解释、可审计、可定向遗忘能力的正式基础，也把 `provenance-first` 收成明确原则：同源即同义。`ConversationDelta` 进入提取阶段时就带上事实 id，LLM 输出契约也要正式要求返回对应依据。
22. `MemoryEntry.provenance` 里的 `fact_ids` 正式采用 `list[str]`，不采用 `list[FactRef]` 这种结构化对象列表。
23. 这样做的原因是：在 LanceDB 里，`list[str]` 是更紧凑、更直接的存储形态；如果改成对象列表，会引入大量重复 key，明显增加冗余。
24. 这也意味着事实引用的规范化责任前置到 LTM 和事实层边界上：先定义稳定的字符串事实 id，再把它们直接作为 `MemoryEntry` 里的正式 provenance 引用值保存下来。只要两条候选记忆锚定到同一组正式 `fact_ids`，系统就先把它们视为同一语义对象，而不是先把不同改写当成两条独立长期记忆。
25. `fact_ids` 中保存的正式事实引用，采用规范化后的字符串主键。先明确区分两类来源：
    - 入站事实写成 `e:event_uid`
    - 出站事实写成 `m:message_uid`
26. 这样做的目标是让 `MemoryEntry` 保持自包含。只要拿到一条 entry，就能立刻知道应该回到哪一类事实真源、用哪个 UID 去取证据。
27. LLM 不直接输出完整的正式 `fact_ids`。像 `e:f47ac10b-...` 这种长字符串不适合作为模型输出依据，既增加理解负担，也会提升输出错误率。
28. provenance 采用“两段式映射”：
    - 系统先给当前 `ConversationDelta` 里的事实分配本地编号
    - LLM 只输出本地编号列表作为依据
    - 系统在后处理阶段再把这些本地编号回填成正式的 `fact_ids`
29. 给 LLM 的本地事实编号采用带前缀的短编号，不用纯数字序号。正式形态收成类似 `f1`、`f2`、`f3` 这种特殊锚点。
30. 这样做的原因有三层：第一，它能明显区分“事实编号”与普通数字内容，减少模型把编号和正文里的时间、数量、楼层等信息混淆；第二，`f1` 这种短锚点在自然对话里几乎不会自发出现，模型识别它的稳定性会明显高于单独的 `1`、`2`、`3`；第三，后处理和校验也更顺手，系统可以稳定用简单规则识别和回填这些本地编号。
31. 因此，交给 LLM 的对话事实材料，要显式携带这种短锚点编号；模型输出契约中的依据字段也对应返回这组短编号，而不是直接输出正式 `fact_ids`。
32. 这组本地短编号只在当前提取窗口里有效，不追求在整个 `conversation_id` 范围内保持稳定。
33. 也就是说，每次进入一次新的提取窗口，系统都可以重新按当前窗口内事实顺序分配 `f1`、`f2`、`f3` 这类局部编号；窗口结束后，这组编号的意义也随之结束。
34. 这样做的目标是把本地编号严格收窄成 prompt 内部的临时锚点，而不是再额外维护一套 conversation 级的稳定编号系统。正式长期可追溯性继续由回填后的 `fact_ids` 承担。
34.1 写侧窗口的计量单位统一按 `fact` 计算。这里的 `fact` 就是事实层里的最小输入单元，当前包括入站 `event` 和出站 `message` 两类，而不是按 message turn 或别的更高层单位计数。
34.2 当前窗口策略的默认值收成：`window_size = 50`、`overlap_size = 10`。这意味着每个提取窗口默认查看 50 个 fact，相邻窗口重叠 10 个 fact，因此自然向前推进的步长是 40 个新 fact。
34.3 不再单独保留 `flush_threshold` 作为独立配置项。标准写侧滑窗里，触发下一次提取的阈值直接由 `step_size = window_size - overlap_size` 派生；在当前默认值下，这个步长就是 40。
34.4 `max_retry_count` 允许作为写侧策略参数开放配置；重试过程中也允许切换到更强的提取模型作为兜底，但重试语义始终针对同一个失败窗口，不改变 provenance 或窗口边界本身。
35. `MemoryEntry.provenance.fact_ids` 严格要求至少包含 1 个依据；没有依据的 entry 直接视为非法对象，不予入库。
36. 这意味着 provenance 不是“尽量有就行”的附加信息，而是 `MemoryEntry` 的正式有效性条件之一。只要依据为空，这条 entry 就不成立。
37. 这样做的目标，是把“每条长期记忆都必须能举证”收成系统硬约束，避免后续在定向删除、隐私清理、WebUI 反查、审计解释等链路里到处写防御性分支。
38. prompt 和输出契约都要明确强化这条规则；Schema 层正式要求依据字段至少包含一个本地事实编号，不能留空。
39. 当前窗口里只要出现任意一条非法 entry，默认语义就是整窗失败重试，而不是只丢弃单条 entry 继续入库其余结果。
40. 这意味着 provenance 的合法性不只是 entry 级要求，也是窗口级输出质量要求。只要当前窗口输出中混入无法举证的记忆，这一整批结果就不算合格。
41. 因此，系统默认站在“整窗 correctness 优先于局部容错”的一侧，让模型把“完整且可举证地完成整个窗口提取”当成一次整体任务来负责。
42. 把“整窗失败重试”固定为正式行为，不开放成用户配置。
43. 这意味着窗口级 provenance 合法性不是可切换策略，而是 Core SimpleMem 的固定架构边界。只要当前窗口输出中存在非法 entry，就统一按整窗失败处理。
44. 这样做的目标，是让提取语义保持硬约束、单一路径和稳定可预期，避免过早把窗口级 correctness 规则拆成配置项，导致文档、测试和运行行为分叉。
44.1 当某个窗口在重试耗尽后仍然失败时，这个失败窗口不能被静默吞掉，也不能被伪装成成功消费。系统必须把它记录进专门的 failed / dead-letter 队列，供后续人工处理或后台修复任务继续接手。
44.2 在存在 failed window 的情况下，`conversation_id` 级别的 LTM 写侧状态要明确进入 degraded，而不是继续表现为“全部健康”。后续窗口可以继续被处理，但失败窗口留下的 provenance 空洞必须被显式暴露，而不是靠主流程静默跳过。
45. `MemoryEntry` 的检索相关结构信息，必须做成正式一等字段，不重新压扁回 `metadata`。
46. 这条决定直接服务于 Core SimpleMem 的 `Multi-View Indexing`。`lossless_restatement`、`keywords`、`time_point`、`time_interval_start`、`time_interval_end`、`persons`、`entities`、`location`、`topic`、`provenance` 都属于正式模型的一部分，而不是后挂的附属信息。
47. 这样做的原因很直接：这些字段如果只是 JSON `metadata` 里的松散内容，数据库层的索引支持、过滤表达能力、查询性能、以及 Query-Aware Retrieval 的硬约束精度都会明显下降。
48. 因此，`MemoryEntry` 的正式形态继续朝这种方向收束：
    - `entry_id`
    - `conversation_id`
    - `lossless_restatement`
    - `keywords`
    - `time_point`
    - `time_interval_start`
    - `time_interval_end`
    - `persons`
    - `entities`
    - `location`
    - `topic`
    - `provenance`
49. 结构字段的空值策略，正式遵循“诚实大于完整”。如果事实里不存在某个维度，这个字段必须允许为空，而不是为了形式完整去编造。
50. `location` 允许为 `null`。很多对话天然不包含空间属性，这类 entry 不应该因为没有地点就被视为不完整。
50.1 `location` 的正式形态保持为单个自然语言字符串，不进一步拆成城市、建筑、房间号这类分层地点对象。这样更符合对话事实本身的松散性，也与 SimpleMem 当前把 `location` 定义成 natural language location description 的方向保持一致。
50.2 `location` 的标准写法主要在 prompt 契约里约定，让模型在提取时尽量输出稳定、可复用、少噪声的自然语言地点表达；系统侧只保留轻量规范化比较兜底，用来消除大小写、首尾空白、全半角、常见标点这类表面差异，不额外引入重语义归一或地点 canonical id 体系。
51. 时间语义拆成三类正式字段：`time_point`、`time_interval_start`、`time_interval_end`。它们都允许为 `null`，但单条 `MemoryEntry` 里 `time_point` 与 interval 字段不得并存。
52. 能稳定锚到单个时间点时，填写 `time_point`，并把 `time_interval_start`、`time_interval_end` 留空；能稳定锚到时间区间时，填写 interval 边界，并把 `time_point` 留空；两者都无法稳定锚定时，就都保持 `null`，把时间语义只保留在 `lossless_restatement` 里。
53. 区间时间不采用单个字符串字段，而是拆成 `start/end` 两个正式边界字段。这样做的原因是：单点时间和区间时间是两种不同的结构语义，不应该混在同一个字段里；同时，区间一旦要参与 SQL 过滤、排序和 overlap 判断，边界字段会明显比单个字符串更稳定、更直接。
54. `time_point`、`time_interval_start`、`time_interval_end` 的值都采用规范化后的字符串边界，而不是自由文本。也就是说，系统在提取后要把它们收成稳定、可比、可序列化的标准化时间字符串；文档先拍死“必须规范化”，不让时间边界格式在不同 entry 之间漂移。
55. Core SimpleMem 正式允许单侧有界区间。仅有 `time_interval_start` 表示从该时间开始、结束未知或未给出的区间；仅有 `time_interval_end` 表示截至该时间为止、开始未知或未给出的区间。两者不要求必须同时存在，但也不得同时为空；如果两端都空，就不构成合法的 interval 结构。
56. 单侧有界区间只在原事实明确表达单侧时间边界时才合法；系统不能把抽取不完整、理解失败或根本没有锚定清楚的时间语义，伪装成一个看似合法的半开区间。
57. 区间边界两端允许精度不完全一致，但必须保持诚实和规范化。也就是说，如果事实里只能稳定锚到月级，就写月级；如果能稳定锚到日级，就写日级；系统不为了让起止精度看起来整齐，就额外补编并不存在的具体时间。
58. 查询侧一旦识别出时间条件，也必须走同一套规范化逻辑，而不是把自然语言时间碎片直接丢进 retrieval。也就是说，像“上周”“三月到五月”“去年 Q4”这类查询时间条件，在进入 `symbolic retrieval` 之前，也要先被收成同样风格的时间点或时间区间边界，再去和 `time_point / time_interval_start / time_interval_end` 对接。
59. 时间区间查询与 entry 区间的命中规则，正式采用 overlap 语义，而不是包含语义。只要 query 侧规范化后的时间区间与 entry 的 `time_interval_start / time_interval_end` 存在交集，就视为命中；不要求一方完整包含另一方。
60. 查询侧在处理单侧有界区间时，缺失边界按无穷边界解释。也就是说，只有 `time_interval_start` 的对象按“从该点延伸到未来”理解，只有 `time_interval_end` 的对象按“从过去延伸到该点”理解；overlap 判断也沿用这套语义。
61. `persons`、`entities`、`keywords` 这类列表字段不允许为 `null`，但允许为空列表 `[]`。这样后续消费端统一使用 `if x:` 就能判断是否存在内容，不需要到处写额外的空值分支。
62. 虽然 `keywords` 允许为空列表，但 prompt 要强引导模型尽量产出 3 到 5 个关键词，因为这是词汇层检索能力的生命线，不能把它退化成“可有可无的装饰字段”。
62.1 这三类列表字段当前不拍死统一的硬长度上限，但允许直接在 prompt 契约里给出软上限和保留优先级，让模型在过长时优先保留更有检索价值的项，而不是无差别穷举。
62.2 `persons` 的保留优先级是：正文主语或核心参与者优先，其次是被明确动作关联的人，最后才是边缘提及者。
62.3 `entities` 的保留优先级是：与 `topic` 直接相关的核心实体优先，其次是正文中高区分度的专名，最后才是边缘上下文实体。
62.4 `keywords` 的保留优先级是：高区分度专名优先，其次是正文里不一定稳定复现但对搜索很有帮助的短词，再其次是主题锚点词，最后才是泛词。
63. `persons` 和 `entities` 不允许在同一条 `MemoryEntry` 里出现重叠值。对同一条 entry，规范化后的字符串集合必须满足 `set(persons) ∩ set(entities) = ∅`。
64. 归类优先级也收成明确规则：人名优先落 `persons`；公司、项目、产品、组织这类对象优先落 `entities`。系统不接受同一个规范化后的字符串既被当成人，又被当成实体，在两个字段里重复挂载。
64.1 `persons` 和 `entities` 的正式存储形态继续保留可读字符串，不引入额外的 canonical id 体系。系统只在去重和互斥判断时做规范化比较，但落盘值仍然保持对人类和模型都直观可读的字符串形态。
64.1.1 `persons`、`entities`、`location` 也要做同等级别的基础规范化清洗。空字符串、纯空白、规范化后为空的值，以及纯标点这类明显没有信息量的噪声项，都不允许进入最终落盘结果。
64.1.2 `persons` 和 `entities` 的标准写法同样以前置 prompt 约定为主，让模型在提取时尽量输出稳定、可复用、少噪声的可读表达；系统侧只保留轻量规范化比较兜底，用来消除大小写、首尾空白、全半角、常见标点这类表面差异，不额外引入重语义归一、人物字典或实体 canonical id 体系。
64.2 当前不额外引入 `fact_modality` 或 `fact_polarity` 这类字段。理由不是这些语义不重要，而是它们已经变成了提取成本、校验成本、文档成本都在，但运行收益几乎没有的字段。
64.3 这里的正式边界继续保持克制：只有那些真正能显著提升 symbolic retrieval 和索引能力的信息，才值得被结构化成一等字段；像语气、姿态、否定、条件这类更高层语义，继续交给高质量正文和 LLM 理解能力去处理。
65. `keywords` 允许与 `persons`、`entities` 重叠。也就是说，同一个高价值专名既可以作为 symbolic 槽位值存在，也可以同时进入 lexical 真源，不要求这三类字段彼此完全互斥。
66. 但 `keywords` 的职责不是机械复制 `persons`、`entities` 的全部内容，而是保留那些对词法召回真正有帮助的高区分度词项。系统允许重叠，不等于鼓励把结构字段原样整份抄进 `keywords`。
66.1 `keywords` 在单条 `MemoryEntry` 内部必须做规范化比较去重。大小写、空白、全半角、常见标点差异不应导致同一词项被重复保存；系统应当把这些表面差异视为同一关键词后只保留一份。
66.1.1 空字符串、纯空白、规范化后为空的词项，以及纯标点这类明显没有检索价值的噪声项，都属于规范化阶段直接剔除的无效关键词，不允许进入最终落盘结果。
66.2 `keywords` 去重后保留原有出现顺序，不做按字母或其它规则的二次排序。也就是说，系统既要消除重复噪声，也要尽量保留提取阶段给出的词项先后信息，不把关键词列表压平为无序集合。
67. `location` 也允许与 `keywords` 重叠。也就是说，同一个地点表达既可以作为 `location` 进入 symbolic retrieval，也可以同时作为高区分度词项进入 lexical 真源，不要求地点字段和关键词字段彼此互斥。
68. 不过，这条规则的含义仍然是“允许重叠”，不是“要求复制”。`location` 只有在确实对词法召回有帮助时，才值得再进入 `keywords`；系统不鼓励把所有地点表达无差别地复制一遍。
60. `topic` 作为主题组织字段，应当保持非空；一条完全没有主题锚点的记忆，在后续聚类、汇总和主题组织阶段会明显更混乱。
61. `topic` 是 `MemoryEntry` 的法定必填字段，不是“尽力而为”的软要求。
62. `topic` 的正式形态不是完整句子或小摘要，而是短主题短语。只要模型已经能写出一条合格的 `lossless_restatement`，它就应当也有能力用很短的主题短语概括“这条记忆在说什么”；如果连这样一个短主题都无法稳定给出，通常说明这条记忆本身的提取质量也值得怀疑。
63. `topic` 保持自由短语，不收成受控词表。也就是说，系统要求它短、小、稳定、可读，但不要求它从一套固定标签里挑选。这样可以避免把细微但重要的语义差别过早压扁成少数硬标签。
64. 这和 `time_point`、`time_interval_start`、`time_interval_end`、`location` 这类字段不同。后者是否存在取决于事实里有没有对应维度，强行要求它们非空会提升幻觉风险；而 `topic` 本质上是对正文的主题归纳，属于模型最基础、最稳定的能力之一。
65. 因此，`MemoryEntry` 的合法性条件继续收紧为：正文必须成立，依据必须存在，`topic` 也必须非空。
65.1 `lossless_restatement` 的主约束靠句子形态，而不是靠字数上限。它的职责不是把所有信息重新解释一遍，而是用一条干净、可独立理解、可嵌入、可展示的事实陈述，把这条记忆的核心语义钉住。
65.2 正式风格约束收成：`lossless_restatement` 必须是单条完整陈述，采用单句或单主句结构，完成指代消解，时间语义尽量绝对化，能够脱离原上下文独立理解，并且只陈述事实，不陈述“我觉得 / 可能 / 建议”这类模型附加判断；同时它必须和 provenance 可对齐、可举证。
65.3 明确禁止的写法包括：悬空指代词，如“他 / 她 / 这个 / 那个 / 上次那个”；多句散文式解释；夹带推理、评价、建议；写成“这说明……”“因此可以看出……”这类结论句；写成“用户似乎……”“可能……”这类不确定表述，除非原事实本身就在表达不确定性；以及把多个并列事实硬塞成一段流水账。
65.4 单条 `MemoryEntry` 只允许承载一个核心事实核。也就是说，只要一句话里已经包含两个可以各自独立成立、各自值得被检索和引用的并列事实，它就不再是合格的原子记忆，应该拆成两条 entry，而不是继续勉强塞进一条 `lossless_restatement`。
66. 词法层正式同时使用 `lossless_restatement` 和 `keywords`，不把 `keywords` 降级成仅供展示或调试的附属字段。
67. 这意味着 `keywords` 是词法检索能力的正式组成部分。它们承载的项目代号、缩写、实体名等高密度词汇，要和正文一起进入 lexical retrieval，而不是只让正文独自承担词法召回。
68. 实现上允许把 `lossless_restatement + keywords` 拼成一个统一的词法真源，再只建立一个 FTS 索引。这样既保留了正文的自然语言语义，也把关键词带来的高区分度一起收进词法层。
68. 语义向量层采用增强文本，但采用固定的结构化拼接配方，而不是把所有结构字段随意堆进 embedding 输入。
69. 当前确定的正式 embedding 输入模板是：`Topic: {topic}. Fact: {lossless_restatement}`。
70. 把 `topic` 纳入 embedding 输入，是为了给 dense 向量增加一个高度浓缩的语义导航锚点，让主题词和正文语义一起进入向量空间，提升相近意图和主题的召回稳定性。
71. `keywords` 不进入 embedding 输入。它们已经在词法层承担硬匹配职责；如果再把大量零散关键词塞进 dense 向量，会更容易把本来清晰的事实语义稀释成标签堆，反而降低语义搜索质量。
72. `symbolic` 层是一个完全独立的召回通道，与 `semantic` 和 `lexical` 平级，不降级成只给其它通道打补丁的过滤器或重排器。
73. 这意味着 Core SimpleMem 的正式检索主线是并行三路召回：语义向量一路、词法索引一路、结构字段一路，然后再统一合流。
73.1 query analysis 的主输入只看当前用户消息本身，LLM 也只针对当前消息提取查询意图与检索目标，不把整段 runtime 上下文重写成一个新的“主问题”。
73.2 `working_summary`、`retained_history` 这类 runtime 上下文只作为弱辅助输入存在，用来补充理解当前消息里的省略语义，而不是反客为主地改写检索目标。给多少辅助上下文允许自主配置，当前默认上限收成 5 条。
73.3 这也意味着 Query-Aware Retrieval 的边界继续保持克制：主问题来自当前消息，runtime 上下文只帮助 disambiguation，不负责替用户发明新的查询任务。
73.4 AcaBot 的消息处理主线不应被 query analysis 和后续检索拖住。因此，analysis 和 retrieval 都应按异步、并行、可延后的方式执行；有新消息到来时，它们可以并行启动，但不应成为 bot 回消息的阻塞前置条件。
74. 这样设计的根本原因是：既然前面已经花费提取成本把 `persons`、`entities`、`location`、`time_point`、`time_interval_start`、`time_interval_end` 这类结构字段抽出来，就应该允许系统在检索时直接利用它们的符号化定址能力，而不是再退回模糊的概率匹配。
70. 三路召回后的合流策略，不采用简单并集去重，而采用带来源权重的优先合并。
71. 合流阶段要显式承认不同召回通道的业务置信度并不相同；`symbolic` 的精准定址命中，不应和单纯的语义擦边命中被平起平坐地对待。
72. 当前排序原则至少包含两层：第一，多路同时命中的条目优先级最高；第二，单路命中的条目之间，后续要继续区分不同来源通道的业务价值，而不是只做无差别拼接。
73. 当前优先合并策略进一步明确：在只有单路命中的情况下，`symbolic-only hit` 的优先级明确高于单路 `semantic-only` 或 `lexical-only`。
74. 这样做的原因是，`symbolic` 命中代表的是对人名、时间、地点、实体等硬约束的直接定址；它的业务语义不是“像”，而是“对上了”。
75. 因此，统一合流的优先级骨架已经收成三档：第一档是 `multi-hit`，第二档是 `symbolic-only hit`，第三档才是其它单路命中的候选条目。
76. 在只命中单一路的情况下，`semantic-only` 的优先级明确高于 `lexical-only`。
77. 这样做的原因是：如果一个词真的是人名、项目代号、地点或别的关键硬实体，它更应该在 `symbolic` 层被精准命中，进入更高的档位；如果它最终只落在 `lexical-only`，那它更像是一种字面兜底，而不是高价值命中。
78. 因此，Rerank 的四桶合流策略正式收成：
    1. `Top Tier (Multi-hit)`: 任意两路或三路同时命中
    2. `Second Tier (Symbolic-only)`: 仅结构字段硬约束命中
    3. `Third Tier (Semantic-only)`: 仅语义层命中
    4. `Bottom Tier (Lexical-only)`: 仅词法层命中
79. `Top Tier (Multi-hit)` 内部继续细分，不把所有双命中或三命中结果视为完全同档。
80. 当前 `Rerank` 的正式优先级从高到低收成：
    1. `Tier 1.1: Triple-Hit` = `symbolic + semantic + lexical`
    2. `Tier 1.2: Fact-Intent Match` = `symbolic + semantic`
    3. `Tier 1.3: Fact-Word Match` = `symbolic + lexical`
    4. `Tier 1.4: Intent-Word Match` = `semantic + lexical`
    5. `Tier 2.1: Symbolic-only`
    6. `Tier 2.2: Semantic-only`
    7. `Tier 2.3: Lexical-only`
    8. `Tier 3: Rejected`
81. 可以直接采用位权分数来实现这套排序，不需要写复杂的嵌套判断：
    - `symbolic hit = +100`
    - `semantic hit = +40`
    - `lexical hit = +10`
82. 这样得到的组合分数天然对应正式排序：
    - `150` = Triple-Hit
    - `140` = Symbolic + Semantic
    - `110` = Symbolic + Lexical
    - `100` = Symbolic-only
    - `50` = Semantic + Lexical
    - `40` = Semantic-only
    - `10` = Lexical-only
83. 这套分数并不是在做精细统计学意义上的统一相关性建模，而是在把已经拍板的业务置信度顺序编码成一个简单、稳定、可调试的合流规则。
83.1 当多条命中记忆的最终 `rerank_score` 完全相同时，平手规则按 `updated_at` 倒序打破。也就是说，在同等业务置信度下，最近一次发生实质变化的记忆对象优先级更高。
84. Reflection 作为一种“检索结果不足时自动补搜”的能力，架构上是合法的，但主线不启用。
85. 主线先把写入质量、三路召回、以及合流排序做稳，不让所有请求都默认背上额外的反思判定、补充检索和后续生成开销。
86. 这样做的原因主要有三点：第一，即时通讯场景对延迟敏感，reflection 会显著拉长响应时间；第二，第一轮并行三路召回通常已经覆盖绝大多数相关事实，为少数极端问题让全部请求承担额外成本，收益递减明显；第三，LTM 只是 AcaBot 的一层记忆来源，系统外部还有 `sticky note`、`self` 等别的上下文层，不需要要求 LTM 单独把复杂问题兜到底。
87. `LongTermMemorySource` 不把每条命中的 `MemoryEntry` 单独作为独立 `MemoryBlock` 交给主线，而是把命中的多条 entry 聚合成一个统一的 `long_term_memory` block。
88. 这样做的核心原因是：只有 LTM 自己完整知道每条 entry 的命中来源、排序位置和检索元数据；如果把它们完全拆散交给主线的通用层，这些对渲染最有价值的信息会被明显削弱。
89. 因此，统一的 `long_term_memory` block 仍然保持原子记忆逐条展开，但由 LTM 自己负责渲染这一整块内容，把每条 entry 的 rank、topic、命中辅助线等上下文信息一起带进最终输出。
89.1 注入选择直接复用前面已经拍板的位权分数与统一排序结果，不再额外引入分桶截断或 token budget。系统按最终 `rerank_score` 从高到低做 `top-k` 选择，把最靠前的若干条命中记忆装进 `long_term_memory` block 即可。
89.2 `max_entries` 作为最终注入条数上限保留，当前默认值收成 `8`，但允许配置。也就是说，注入阶段的主控制量是“排好序后的前 N 条 entry”，而不是再额外维护一套按桶配额或 token 预算分发的复杂规则。
90. `long_term_memory` block 的正式渲染格式采用 XML，而不是 Markdown 或普通自由文本模板。
91. XML 的价值在于：它能稳定表达“这是一个长期记忆块，里面有若干条 entry”，并允许 LTM 在不破坏正文可读性的前提下，把时间锚点、对象标识、来源桥接等辅助线一起显式带给上游模型。
92. 每条命中的记忆在 XML 中继续保持逐条展开，正文仍然放在标签内部作为纯文本；排序优先级默认继续通过 XML 中从上到下的物理顺序表达。
93. XML 渲染层的这类小决策不再继续拍死成硬边界，而是统一做成可配置项。这里说的小决策，指的是：
    - 是否暴露 `id`
    - 是否暴露 `topic`
    - 是否暴露 `time`
    - 是否暴露 `sources`
    - 是否额外暴露 `rank / tier`
    - `sources` 的具体表现形式
94. 这些配置只影响 LTM 输出给上游模型时的“渲染外观”，不改变 `MemoryEntry` 内部正式字段本身的存在与语义。比如 `topic` 仍然是 `MemoryEntry` 的法定必填字段，但它在 XML 中是否显式露出，属于 renderer 配置。
95. 当前默认模板继续采用轻量 XML 方向，默认形态可收成：
    - `<entry topic="..." time="...">...</entry>`
96. 在这个默认模板里：
    - `topic` 默认暴露
    - `time` 默认在存在时暴露
    - `lossless_restatement` 正文默认暴露
    - `id` 默认不显式暴露
    - `sources` 默认不显式暴露
    - `rank / tier` 默认不显式暴露，只靠物理顺序表达
97. `persons`、`entities`、`location` 这类已经能从正文中直接读出的信息，默认不在 XML 属性里重复暴露，避免把同一语义重复编码成噪声；但它们同样属于后续可配置项，而不是被架构永久封死。
98. `provenance-first` 继续收紧成正式身份规则：同源即同义，而且这里的“同源”按规范化后的 `fact_ids` 集合判断，采用严格集合相等，不接受“多一个或少一个事实也算同一个对象”的宽松判定。
99. 这意味着 `fact_ids` 在进入身份判定前必须先做 canonical 化：去重、排序、按集合比较，不看原始顺序。`["f1", "f2"]` 和 `["f2", "f1"]` 是同一个对象；`["f1", "f2"]` 和 `["f1", "f2", "f3"]` 不是同一个对象。
100. `entry_id` 不采用随机 UUID，而是由 `conversation_id + sorted(set(fact_ids))` 这一组稳定身份字段派生出来。实现上可以使用类似 UUIDv5 这种确定性主键方案，让同一个 `conversation_id` 下、同一组 canonical `fact_ids` 在重抽、重跑和幂等写入时始终得到同一个 `entry_id`。
101. 同一 `entry_id` 只要再次被抽出，就允许直接覆盖旧内容，不再把“日常写入”和“重建”分成两套不同的覆盖语义。这里的覆盖不是“新对象替掉旧对象”，而是“同一个 provenance 对象刷新成当前抽取结果”。
102. Core SimpleMem 的主存储只保留同一 `entry_id` 的最新值，不在 `MemoryEntry` 主表里保留旧版正文、旧版主题或旧版检索字段的版本历史。证据真源始终留在事实层，LTM 不负责长期保存旧派生结果。
103. `updated_at` 继续作为这条记忆对象当前版本的更新时间；`created_at` 同时作为正式管理字段保留，用来记录这条记忆对象第一次进入 LTM 的时间。不额外引入 `rebuilt_at`，避免与 `updated_at` 语义重复。
104. `extractor_version` 作为 `MemoryEntry` 的正式字段保留，用来标记这条当前记忆对象是由哪一代提取器 / prompt 契约写出来的。它服务于重刷、审计、问题定位和批量重算，不是临时日志字段。
105. `extractor_version` 这类信息属于管理类字段，不属于检索类字段。它们不参与向量化、不进入 FTS、不作为 SQL 检索条件，也不默认暴露给上游模型；系统内部只把它们当作运维和治理所需的元信息维护。
106. 这也意味着 `MemoryEntry` 的正式字段继续分成两类：一类是 `lossless_restatement`、`keywords`、`time_point`、`time_interval_start`、`time_interval_end`、`persons`、`entities`、`location`、`topic`、`provenance` 这组检索与解释字段；另一类是 `entry_id`、`conversation_id`、`created_at`、`updated_at`、`extractor_version` 这组对象身份与管理字段。前者服务于召回与解释，后者服务于稳定主键、幂等更新和系统治理。
107. `updated_at` 不因为“相同对象又被重抽了一次”就刷新。只有当对象内容或管理元信息发生实质变化时，才更新 `updated_at`；这里的实质变化至少包括 `lossless_restatement`、`topic`、`keywords` 或 `extractor_version` 发生变化。相同内容的重复抽取只视为一次幂等命中，不产生新的更新时间。
108. `keywords` 不只是正文旁边的附属索引提示，而属于记忆内容的一部分。因此，只要 `keywords` 发生变化，即便正文不变，也应当视为对象内容发生了实质变化，允许覆盖并刷新 `updated_at`。
109. 同样地，`time_point`、`time_interval_start`、`time_interval_end`、`location`、`persons`、`entities`、`provenance` 这类正式检索与解释字段的变化，也一律算作对象发生了实质变化。只要任何正式检索字段或正式管理字段发生变化，系统就允许覆盖并刷新 `updated_at`；既然这些字段已经被定义为一等字段，它们的变化就不能再被当成“无关紧要的附属抖动”。
110. 不过，`provenance` 的地位和其它检索字段不同：它不是“同一对象下可变的覆盖字段”，而是对象身份本身的一部分。只要 `conversation_id + canonical fact set` 变化了，就必然得到新的 `entry_id` 和新的 `MemoryEntry`；因此，同一 `entry_id` 的覆盖更新只发生在 provenance 不变的前提下。
