# AcaBot Core SimpleMem Structured Design
先看:
docs/00-ai-entry.md
docs/superpowers/plans/2026-03-25-sticky-note-refactor.md
docs/LTM/core-simplemem-design.md

这一页是 `core-simplemem-design.md` 的结构化整理稿。
原文件继续保留为结论累积池；这一页负责把已经拍板的内容按主题收束，方便后续实现、review 和 wiki 整理。

## 当前仓库实现

当前代码已经有一版可装配的 `long_term_memory`:

- `contracts.py` 定义 `MemoryEntry`、`MemoryProvenance`、`FailedWindowRecord`
- `storage.py` 提供 `LanceDbLongTermMemoryStore`
- `write_port.py` 提供 `LtmWritePort`
- `source.py` 提供 `CoreSimpleMemMemorySource`
- `bootstrap/builders.py` 在 `runtime.long_term_memory.enabled = true` 时自动装配写入线和检索线

当前统一模型位点是:

- `system:ltm_extract`
- `system:ltm_query_plan`
- `system:ltm_embed`

## 1. 设计边界

### 1.1 目标

AcaBot 当前的 LTM 目标明确是 `Core SimpleMem`，不是弱化版替身。

正式主线是：

- 原子记忆写入
- 混合检索
- query-aware retrieval

当前讨论范围只收在 `LTM 内部设计`。
这轮不展开 runtime 主线怎么重构，也不展开别的 memory layer 怎么统一抽象。

### 1.2 与外部 runtime 的交接边界

对外部 runtime 的要求先收窄到“接口形状能挂上现有插槽”即可：

- 写侧能挂到 `LongTermMemoryWritePort`
- 读侧能挂到 `MemorySource`

`MemoryEntry` 是 Core SimpleMem 的正式真对象，但 AcaBot 外部不需要全局直接理解它。

### 1.3 正式归属范围

Core SimpleMem 的正式记忆归属范围确定为 `conversation_id`。

这意味着：

- 同一个对话容器里的多次对话，会沉淀到同一套长期记忆里
- `thread_id` 仍然可以出现在 provenance 或运行时边界里
- `thread_id` 不作为长期记忆的正式归属主键

后续写入、检索、去重、以及内部索引分区，都先以 `conversation_id` 作为第一层边界思考。

## 2. 正式对象模型

### 2.1 `MemoryEntry`

Core SimpleMem 拥有自己的正式记忆对象 `MemoryEntry`，不复用 `MemoryItem` 或别的通用外壳。

原子化提取出来的结果，会直接以 `MemoryEntry` 的身份进入：

- 存储
- 索引
- 去重
- 检索

### 2.2 字段分组

`MemoryEntry` 的正式字段分成两类。

检索与解释字段：

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

对象身份与管理字段：

- `entry_id`
- `conversation_id`
- `created_at`
- `updated_at`
- `extractor_version`

前者服务于召回与解释，后者服务于稳定主键、幂等更新和系统治理。

### 2.3 不额外引入的字段

当前不额外引入 `fact_modality` 或 `fact_polarity`。

这里的正式边界是：

- 只有那些真的能显著提升 symbolic retrieval 和索引能力的信息，才值得结构化成一等字段
- 语气、姿态、否定、条件这类更高层语义，继续交给高质量正文和 LLM 理解能力去处理

原因不是这些语义不重要，而是它们已经变成了提取成本、校验成本、文档成本都在，但运行收益几乎没有的字段。

## 3. Provenance、身份与更新语义

### 3.1 `provenance` 的正式边界

`provenance` 是 Core SimpleMem 的正式能力之一。

系统要求：

- `provenance` 只记来源引用，不存来源文本快照
- 事实层 `ChannelEventStore + MessageStore` 是稳定、不可变的真源
- LTM 不重复保存证据正文

一句话边界是：

`LTM 负责总结（归纳），事实库负责留存证据（真源）`

### 3.2 `fact_ids`

每条 `MemoryEntry` 都正式保存细粒度 `fact_ids`，而不是只记窗口范围或批次范围。

`fact_ids` 的正式规则：

- 存储形态是 `list[str]`
- 不用 `list[FactRef]`
- 入站事实写成 `e:event_uid`
- 出站事实写成 `m:message_uid`

这样做的目标是让 `MemoryEntry` 保持自包含。只要拿到一条 entry，就能立刻知道应该回到哪一类事实真源、用哪个 UID 去取证据。

### 3.3 LLM 输出依据的方式

LLM 不直接输出正式 `fact_ids`。

正式机制是两段式映射：

- 系统先给当前 `ConversationDelta` 里的 fact 分配本地编号
- LLM 只输出本地编号列表
- 系统后处理再把本地编号回填成正式 `fact_ids`

本地编号规则：

- 采用 `f1`、`f2`、`f3` 这种带前缀短编号
- 只在当前提取窗口里有效
- 不追求在整个 `conversation_id` 范围内保持稳定

### 3.4 `provenance-first`

Core SimpleMem 的正式原则是：

`provenance-first`
`同源即同义`

这里的“同源”按规范化后的 `fact_ids` 集合判断，采用严格集合相等：

- 先去重
- 再排序
- 按集合比较
- 不看原始顺序

因此：

- `["f1", "f2"]` 和 `["f2", "f1"]` 是同一个对象
- `["f1", "f2"]` 和 `["f1", "f2", "f3"]` 不是同一个对象

### 3.5 `entry_id`

`entry_id` 不采用随机 UUID，而是由稳定身份字段派生：

- `conversation_id`
- `sorted(set(fact_ids))`

实现上可以使用类似 UUIDv5 这种确定性主键方案。

因此：

- 同一个 `conversation_id` 下、同一组 canonical `fact_ids`
- 在重抽、重跑和幂等写入时
- 始终得到同一个 `entry_id`

本设计的幂等边界建立在 provenance 集合稳定的前提下。若提取器升级导致事实拆分 / 合并方式变化，从而产生新的 canonical `fact_ids` 集合，则系统直接视为生成新的 `MemoryEntry`；系统不尝试跨 provenance 集合自动判定它与旧对象是否“其实还是同一个东西”。

### 3.6 有效性条件

`MemoryEntry` 的正式有效性条件继续收紧为：

- 正文必须成立
- `provenance.fact_ids` 必须至少包含 1 个依据
- `topic` 必须非空

没有依据的 entry 直接视为非法对象，不予入库。

### 3.7 覆盖与历史

同一 `entry_id` 只要再次被抽出，就允许直接覆盖旧内容。

这里的覆盖不是“新对象替掉旧对象”，而是“同一个 provenance 对象刷新成当前抽取结果”。

系统只保留同一 `entry_id` 的最新值，不在主表里保留旧版正文、旧版主题或旧版检索字段的版本历史。

### 3.8 `created_at` / `updated_at` / `extractor_version`

- `created_at` 表示这条记忆对象第一次进入 LTM 的时间
- `updated_at` 表示这条记忆对象当前版本的更新时间
- `extractor_version` 表示这条当前记忆对象由哪一代提取器 / prompt 契约写出来

不额外引入 `rebuilt_at`。

`extractor_version` 属于管理类字段：

- 不参与向量化
- 不进入 FTS
- 不作为 SQL 检索条件
- 不默认暴露给上游模型

### 3.9 什么算实质变化

`updated_at` 不因为“相同对象又被重抽了一次”就刷新。

只有正式字段发生实质变化时，才更新 `updated_at`。

这包括：

- `lossless_restatement`
- `topic`
- `keywords`
- `time_point`
- `time_interval_start`
- `time_interval_end`
- `location`
- `persons`
- `entities`
- `provenance`
- `extractor_version`

但要注意：

- `provenance` 不是同一对象下可变的覆盖字段
- 它本身就是对象身份的一部分
- 只要 `conversation_id + canonical fact set` 变化了，就必然得到新的 `entry_id` 和新的 `MemoryEntry`

## 4. 写侧窗口与失败处理

### 4.1 计量单位

写侧窗口统一按 `fact` 计算。

这里的 `fact` 是事实层里的最小输入单元，当前包括：

- 入站 `event`
- 出站 `message`

### 4.2 默认窗口参数

当前默认值收成：

- `window_size = 50`
- `overlap_size = 10`

这意味着：

- 每个提取窗口默认查看 50 个 fact
- 相邻窗口重叠 10 个 fact
- 自然向前推进的步长是 40 个新 fact

系统不再单独保留 `flush_threshold` 作为独立配置项。
标准滑窗里，触发下一次提取的阈值直接由：

`step_size = window_size - overlap_size`

派生出来。

### 4.3 重试

`max_retry_count` 允许作为写侧策略参数开放配置。

重试过程中也允许切换到更强的提取模型作为兜底，但重试语义始终针对同一个失败窗口，不改变 provenance 或窗口边界。

### 4.4 失败窗口

当某个窗口在重试耗尽后仍然失败时：

- 这个窗口不能被静默吞掉
- 也不能被伪装成成功消费
- 系统必须把它记录进专门的 failed / dead-letter 队列

同时：

- `conversation_id` 级别的 LTM 写侧状态要明确进入 degraded
- 后续窗口可以继续处理
- 但失败窗口留下的 provenance 空洞必须被显式暴露

## 5. 字段语义与规范化

### 5.1 时间字段

时间语义拆成三类正式字段：

- `time_point`
- `time_interval_start`
- `time_interval_end`

规则如下：

- `time_point` 与 interval 字段不得并存
- 能稳定锚到单个时间点时，填写 `time_point`
- 能稳定锚到区间时，填写 `time_interval_start / time_interval_end`
- 两者都无法稳定锚定时，就都保持 `null`
- 完整时间语义继续保留在 `lossless_restatement`

区间字段规则：

- 不采用单个字符串字段
- 使用 `start/end` 两个边界字段
- 两边都采用规范化后的字符串边界
- 允许单侧有界区间
- 但 `time_interval_start` 与 `time_interval_end` 不得同时为空
- 单侧有界区间只在原事实明确表达单侧边界时才合法
- 区间边界两端允许精度不完全一致，但必须保持诚实和规范化

正式允许的时间字符串形态只保留 4 种：

- `YYYY`
- `YYYY-MM`
- `YYYY-MM-DD`
- `YYYY-MM-DDTHH:MM:SSZ`

也就是说，`time_point`、`time_interval_start`、`time_interval_end` 都只能落成这 4 种规范化形态之一，不再额外引入 `YYYY-W12`、`Q4`、`half-year`、区间拼接字符串之类并行语法。

像“上周”“去年 Q4”“2025 上半年”这类时间表达，在进入存储前统一改写成公历边界：

- 周、季度、半年这类表达不保留原形
- 统一展开成对应的年 / 月 / 日边界
- 再写入 `time_point` 或 `time_interval_start / time_interval_end`

只要时间值已经精确到时分秒，就要求它带稳定时区语义，并统一存成 UTC 的 `...Z` 形式。
如果原事实无法稳定确定时区，就不要硬升到时分秒精度，宁可退回 `YYYY-MM-DD` 或更粗粒度的合法形态。

### 5.2 查询侧时间条件

查询侧一旦识别出时间条件，也必须走同一套规范化逻辑。

也就是说：

- 先把“上周”“三月到五月”“去年 Q4”收成规范化边界
- 再去和 `time_point / time_interval_start / time_interval_end` 对接

时间区间查询的命中规则采用 overlap 语义：

- 只要 query 区间与 entry 区间有交集，就视为命中
- 不要求一方完整包含另一方

处理单侧有界区间时，缺失边界按无穷边界解释。

### 5.3 `location`

- `location` 允许为 `null`
- 正式形态保持为单个自然语言字符串
- 不进一步拆成城市、建筑、房间号这类分层地点对象

标准写法主要在 prompt 契约里约定：

- 模型提取时尽量输出稳定、可复用、少噪声的地点表达
- 系统侧只保留轻量规范化比较兜底
- 不引入重语义归一或地点 canonical id

### 5.4 `persons` / `entities`

`persons`、`entities`、`keywords` 这类列表字段：

- 不允许为 `null`
- 允许为空列表 `[]`

`persons` 与 `entities` 的规则：

- 同一条 `MemoryEntry` 里不允许重叠
- 规范化后的集合必须满足 `set(persons) ∩ set(entities) = ∅`
- 人名优先落 `persons`
- 公司、项目、产品、组织优先落 `entities`

存储形态继续保留可读字符串：

- 不引入 canonical id
- prompt 主约束标准写法
- 系统只做轻量规范化比较兜底

基础清洗要求：

- 空字符串不允许落盘
- 纯空白不允许落盘
- 规范化后为空的不允许落盘
- 纯标点噪声不允许落盘

### 5.5 `keywords`

`keywords` 的职责是 lexical retrieval 的正式组成部分。

它们：

- 和 `lossless_restatement` 一起进入词法层
- 可以与 `persons`、`entities`、`location` 重叠
- 但不应该机械复制结构字段全部内容

`keywords` 的保留优先级：

- 高区分度专名
- 正文里不一定稳定复现但对搜索很有帮助的短词
- 主题锚点词
- 泛词

`keywords` 的规范化规则：

- 在单条 `MemoryEntry` 内必须做规范化比较去重
- 大小写、空白、全半角、常见标点差异，不应导致重复保存
- 去重后保留原有出现顺序
- 空字符串、纯空白、规范化后为空、纯标点噪声都不允许进入落盘结果

长度控制：

- 当前不拍死统一硬上限
- 允许在 prompt 契约里直接给软上限
- 当前默认目标仍然是尽量产出 3 到 5 个关键词

### 5.6 `topic`

`topic` 的正式边界是：

- 法定必填字段
- 必须非空
- 不是完整句子或小摘要
- 必须是短主题短语
- 保持自由短语，不收成受控词表

标准写法同样以前置 prompt 约定为主：

- 模型尽量输出稳定、少噪声的短主题短语
- 系统只做轻量规范化比较兜底
- 不做重语义归并

### 5.7 `lossless_restatement`

`lossless_restatement` 的主约束靠句子形态，而不是靠字数上限。

它的职责是：

- 用一条干净、可独立理解、可嵌入、可展示的事实陈述
- 把这条记忆的核心语义钉住

必须满足：

- 单条完整陈述
- 单句或单主句结构
- 指代消解后
- 时间语义尽量绝对化
- 可脱离原上下文独立理解
- 只陈述事实，不陈述“我觉得 / 可能 / 建议”这类模型附加判断
- 与 provenance 可对齐，可举证

明确禁止：

- “他 / 她 / 这个 / 那个 / 上次那个”这类悬空指代
- 多句散文式解释
- 推理、评价、建议
- “这说明……” “因此可以看出……”
- “用户似乎……” “可能……”，除非原事实本身就在表达不确定性
- 把多个并列事实硬塞成一段流水账

单条 `MemoryEntry` 只允许承载一个核心事实核。
只要一句话里已经包含两个可以各自独立成立、各自值得被检索和引用的并列事实，就应该拆成两条 entry。

## 6. 检索主线

### 6.1 词法层

词法层正式同时使用：

- `lossless_restatement`
- `keywords`

实现上允许把它们拼成一个统一的词法真源，再只建立一个 FTS 索引。

### 6.2 语义向量层

语义向量层采用增强文本，但使用固定的结构化拼接配方：

`Topic: {topic}. Fact: {lossless_restatement}`

规则是：

- `topic` 进入 embedding 输入
- `keywords` 不进入 embedding 输入

### 6.3 Symbolic 层

`symbolic` 层是一个完全独立的召回通道，与 `semantic` 和 `lexical` 平级。

这意味着正式检索主线是：

- 语义向量一路
- 词法索引一路
- 结构字段一路
- 然后统一合流

### 6.4 Query Analysis

query analysis 的主输入只看当前用户消息本身。

LLM 也只针对当前消息提取查询意图与检索目标，不把整段 runtime 上下文重写成新的“主问题”。

`working_summary`、`retained_history` 只作为弱辅助输入存在：

- 用来补充理解当前消息里的省略语义
- 不反客为主地改写检索目标
- 给多少辅助上下文允许自主配置
- 当前默认上限是 5 条

### 6.5 非阻塞原则

AcaBot 的消息处理主线不应被 query analysis 和后续检索拖住。

因此：

- analysis 应按异步、并行、可延后的方式执行
- retrieval 也应按异步、并行、可延后的方式执行
- 有新消息到来时，它们可以并行启动
- 但不应成为 bot 回消息的阻塞前置条件

## 7. 合流与排序

### 7.1 合流原则

三路召回后的合流策略，不采用简单并集去重，而采用带来源权重的优先合并。

合流阶段显式承认不同召回通道的业务置信度不同。

### 7.2 位权分数

正式位权分数是：

- `symbolic hit = +100`
- `semantic hit = +40`
- `lexical hit = +10`

组合分数天然对应正式排序：

- `150` = Triple-Hit
- `140` = Symbolic + Semantic
- `110` = Symbolic + Lexical
- `100` = Symbolic-only
- `50` = Semantic + Lexical
- `40` = Semantic-only
- `10` = Lexical-only

### 7.3 排序层级

从高到低收成：

1. `symbolic + semantic + lexical`
2. `symbolic + semantic`
3. `symbolic + lexical`
4. `semantic + lexical`
5. `symbolic-only`
6. `semantic-only`
7. `lexical-only`
8. `rejected`

### 7.4 平手规则

当多条命中记忆的最终 `rerank_score` 完全相同时，平手规则按 `updated_at` 倒序打破。

## 8. Reflection

Reflection 作为一种“检索结果不足时自动补搜”的能力，架构上合法，但主线不启用。

理由是：

- 即时通讯场景对延迟敏感
- 第一轮并行三路召回通常已经覆盖绝大多数相关事实
- LTM 只是 AcaBot 的一层记忆来源，系统外部还有 `sticky note`、`self` 等别的上下文层

## 9. 注入与渲染

### 9.1 `long_term_memory` block

`LongTermMemorySource` 不把每条命中的 `MemoryEntry` 单独作为独立 `MemoryBlock` 交给主线，而是把命中的多条 entry 聚合成一个统一的 `long_term_memory` block。

原因是：

- 只有 LTM 自己完整知道每条 entry 的命中来源、排序位置和检索元数据
- 如果把它们完全拆散交给主线，这些对渲染最有价值的信息会被明显削弱

### 9.2 注入选择

注入选择直接复用前面已经拍板的位权分数与统一排序结果。

规则是：

- 按最终 `rerank_score` 从高到低做 `top-k`
- 不再额外引入分桶截断
- 不引入 `max_ltm_tokens`
- `max_entries` 作为最终注入条数上限保留
- 当前默认值是 `8`
- 但允许配置

### 9.3 XML 渲染

`long_term_memory` block 的正式渲染格式采用 XML。

XML 的价值是：

- 稳定表达“这是一个长期记忆块，里面有若干条 entry”
- 允许 LTM 在不破坏正文可读性的前提下，把时间锚点、对象标识、来源桥接等辅助线显式带给上游模型

每条命中的记忆在 XML 中继续保持逐条展开，正文仍然放在标签内部作为纯文本；排序优先级默认通过 XML 中从上到下的物理顺序表达。

### 9.4 渲染配置

XML 渲染层的小决策统一做成可配置项：

- 是否暴露 `id`
- 是否暴露 `topic`
- 是否暴露 `time`
- 是否暴露 `sources`
- 是否额外暴露 `rank / tier`
- `sources` 的具体表现形式

这些配置只影响输出给上游模型时的渲染外观，不改变 `MemoryEntry` 内部正式字段本身的存在与语义。

当前默认模板继续采用轻量 XML 方向，默认形态可收成：

- `<entry topic="..." time="...">...</entry>`

默认暴露规则：

- `topic` 默认暴露
- `time` 默认在存在时暴露
- `lossless_restatement` 正文默认暴露
- `id` 默认不显式暴露
- `sources` 默认不显式暴露
- `rank / tier` 默认不显式暴露，只靠物理顺序表达

`persons`、`entities`、`location` 这类已经能从正文中直接读出的信息，默认不在 XML 属性里重复暴露。
