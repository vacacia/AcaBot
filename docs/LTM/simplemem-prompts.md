# SimpleMem Prompt 参考手册

本文档列出 SimpleMem 中所有 LLM prompt 的原文及中文翻译，按处理阶段分类。

每个 prompt 标注了**源文件相对路径**（相对于 SimpleMem 仓库根目录），以及行号。
SimpleMem 有三套实现：Core（`core/`）、MCP Server（`MCP/server/core/`）、SKILL（`SKILL/simplemem-skill/src/core/`，结构与 MCP 基本一致）。

---

## 流水线总览

SimpleMem 把检索拆成了一条多步流水线，不是只有"提取记忆"和"改写 query"两步。完整链路如下：

```
用户提问
  │
  ├─① Query 分析（analyze）── 理解问题本身：提取实体、判断问题类型、评估复杂度
  │                           输出: key_entities, question_type, required_info, complexity_score
  │
  ├─② Query 生成（generate）── 基于①的分析结果，生成实际要丢进向量库搜索的 query 文本
  │                           输出: ["query1", "query2", ...]
  │
  ├─③ 执行检索（semantic + keyword + structured）
  │
  ├─④ 充分性检查 ── 判断③检索到的结果够不够回答问题
  │     │
  │     └─ 不够 → ⑤ 补漏 query 生成 → 回到③（最多 2 轮）
  │
  └─⑥ 答案生成
```

### Query 分析 vs Query 生成

- **Query 分析**是 planning：理解"这个问题需要什么信息"，输出结构化的需求描述（实体、关系、信息类型、优先级）。
- **Query 生成**是 execution：把上面的需求描述变成实际的搜索词（1-4 条），丢进向量库 / 关键词索引去检索。

分析的输出（`required_info`, `key_entities` 等）会作为生成 prompt 的输入。

### for AcaBot 

核心的是

1. **记忆提取**（§1）— 对话 → 结构化记忆条目。这是写入侧的核心。
2. **Query 分析 + 生成**（§2 + §3，可合并成一步）— 用户提问 → 搜索 query。这是读取侧的核心。

**答案生成**（§5）和**记忆摘要**（§6）是 SimpleMem 自带的独立问答功能。AcaBot 不需要——因为 AcaBot 的 pipeline 最终是把检索结果注入到 agent 上下文里，由 agent 自己回答，不需要单独一个"答案生成"环节。这里列出来仅作参考。

---

## 目录

1. [记忆提取（Memory Extraction）](#1-记忆提取memory-extraction)
2. [Query 分析（Query Analysis）](#2-query-分析query-analysis)
3. [Query 生成（Query Generation）](#3-query-生成query-generation)
4. [充分性检查（Completeness Check）](#4-充分性检查completeness-check)
5. [答案生成（Answer Generation）](#5-答案生成answer-generation)
6. [记忆摘要（Memory Summarization）](#6-记忆摘要memory-summarization)

---

## 1. 记忆提取（Memory Extraction）

### 1.1 Core 版本

**文件:** `core/memory_builder.py`
**行号:** 190-306（system message 在 L191-193，user prompt 在 `_build_extraction_prompt` L238-306）
**温度:** 0.1

#### System Message

```
You are a professional information extraction assistant, skilled at extracting structured, unambiguous information from conversations. You must output valid JSON format.

你是一个专业的信息提取助手，擅长从对话中提取结构化的、无歧义的信息。你必须输出有效的 JSON 格式。
```

#### User Prompt（原文）

Your task is to extract all valuable information from the following dialogues and convert them into structured memory entries.

{context}

[Current Window Dialogues]
{dialogue_text}

[Requirements]

1. **Complete Coverage**: Generate enough memory entries to ensure ALL information in the dialogues is captured
2. **Force Disambiguation**: Absolutely PROHIBIT using pronouns (he, she, it, they, this, that) and relative time (yesterday, today, last week, tomorrow)
3. **Lossless Information**: Each entry's lossless_restatement must be a complete, independent, understandable sentence
4. **Precise Extraction**:
   - keywords: Core keywords (names, places, entities, topic words)
   - timestamp: Absolute time in ISO 8601 format (if explicit time mentioned in dialogue)
   - location: Specific location name (if mentioned)
   - persons: All person names mentioned
   - entities: Companies, products, organizations, etc.
   - topic: The topic of this information

[Output Format]
Return a JSON array, each element is a memory entry:

```json
[
  {
    "lossless_restatement": "Complete unambiguous restatement (must include all subjects, objects, time, location, etc.)",
    "keywords": ["keyword1", "keyword2", ...],
    "timestamp": "YYYY-MM-DDTHH:MM:SS or null",
    "location": "location name or null",
    "persons": ["name1", "name2", ...],
    "entities": ["entity1", "entity2", ...],
    "topic": "topic phrase"
  },
  ...
]
```

[Example]
Dialogues:
[2025-11-15T14:30:00] Alice: Bob, let's meet at Starbucks tomorrow at 2pm to discuss the new product
[2025-11-15T14:31:00] Bob: Okay, I'll prepare the materials

Output:

```json
[
  {
    "lossless_restatement": "Alice suggested at 2025-11-15T14:30:00 to meet with Bob at Starbucks on 2025-11-16T14:00:00 to discuss the new product.",
    "keywords": ["Alice", "Bob", "Starbucks", "new product", "meeting"],
    "timestamp": "2025-11-16T14:00:00",
    "location": "Starbucks",
    "persons": ["Alice", "Bob"],
    "entities": ["new product"],
    "topic": "Product discussion meeting arrangement"
  },
  {
    "lossless_restatement": "Bob agreed to attend the meeting and committed to prepare relevant materials.",
    "keywords": ["Bob", "prepare materials", "agree"],
    "timestamp": null,
    "location": null,
    "persons": ["Bob"],
    "entities": [],
    "topic": "Meeting preparation confirmation"
  }
]
```

Now process the above dialogues. Return ONLY the JSON array, no other explanations.

#### User Prompt（中文）

你的任务是从以下对话中提取所有有价值的信息，并将其转换为结构化的记忆条目。

{context}

[当前窗口对话]
{dialogue_text}

[要求]

1. **完整覆盖**: 生成足够多的记忆条目，确保对话中的所有信息都被捕获
2. **强制消歧**: 绝对禁止使用代词（他、她、它、他们、这、那）和相对时间（昨天、今天、上周、明天）
3. **无损信息**: 每条记忆的 lossless_restatement 必须是一个完整的、独立的、可理解的句子
4. **精确提取**:
   - keywords: 核心关键词（人名、地点、实体、话题词）
   - timestamp: ISO 8601 格式的绝对时间（如果对话中明确提到了时间）
   - location: 具体地点名称（如果提到了）
   - persons: 提到的所有人名
   - entities: 公司、产品、组织等
   - topic: 该条信息的主题

[输出格式]
返回一个 JSON 数组，每个元素是一条记忆条目：

```json
[
  {
    "lossless_restatement": "完整无歧义的重述（必须包含所有主语、宾语、时间、地点等）",
    "keywords": ["关键词1", "关键词2", ...],
    "timestamp": "YYYY-MM-DDTHH:MM:SS 或 null",
    "location": "地点名称 或 null",
    "persons": ["人名1", "人名2", ...],
    "entities": ["实体1", "实体2", ...],
    "topic": "主题短语"
  },
  ...
]
```

[示例]
对话：
[2025-11-15T14:30:00] Alice: Bob，我们明天下午2点在星巴克见面讨论新产品吧
[2025-11-15T14:31:00] Bob: 好的，我会准备材料

输出：

```json
[
  {
    "lossless_restatement": "Alice 于 2025-11-15T14:30:00 建议与 Bob 在 2025-11-16T14:00:00 于星巴克见面讨论新产品。",
    "keywords": ["Alice", "Bob", "星巴克", "新产品", "会议"],
    "timestamp": "2025-11-16T14:00:00",
    "location": "星巴克",
    "persons": ["Alice", "Bob"],
    "entities": ["新产品"],
    "topic": "产品讨论会议安排"
  },
  {
    "lossless_restatement": "Bob 同意参加会议并承诺准备相关材料。",
    "keywords": ["Bob", "准备材料", "同意"],
    "timestamp": null,
    "location": null,
    "persons": ["Bob"],
    "entities": [],
    "topic": "会议准备确认"
  }
]
```

现在处理以上对话。只返回 JSON 数组，不要其他解释。

---

### 1.2 MCP Server 版本

**文件:** `MCP/server/core/memory_builder.py`
**行号:** 190-310（system message 在 L192-197，user prompt 在 `_build_extraction_prompt` L264-310）
**温度:** 0.1

#### System Message

```

You are a professional information extraction assistant. Extract atomic, self-contained facts from dialogues. Each fact must be independently understandable without context. Always resolve pronouns to actual names and convert relative times to absolute timestamps.


你是一个专业的信息提取助手。从对话中提取原子化的、自包含的事实。每条事实必须脱离上下文也能独立理解。始终将代词替换为实际名称，将相对时间转换为绝对时间戳。

```

#### User Prompt（原文）

{context_section}## Dialogues to Process:
{dialogue_text}

---

## Extraction Requirements:

1. **Complete Coverage**: Capture ALL valuable information from the dialogues.
2. **Self-Contained Facts**: Each entry must be independently understandable.

   - BAD: "He will meet Bob tomorrow" (Who is "he"? When is "tomorrow"?)
   - GOOD: "Alice will meet Bob at Starbucks on 2025-01-15 at 14:00"
3. **Coreference Resolution**: Replace ALL pronouns with actual names.

   - Replace: he, she, it, they, him, her, them, his, hers, their
   - With: The actual person's name or entity
4. **Temporal Anchoring**: Convert ALL relative times to absolute ISO 8601 format.

   - "tomorrow" → Calculate actual date
   - "next week" → Calculate actual date range
   - "in 2 hours" → Calculate actual time
5. **Information Extraction**: For each entry, extract:

   - `lossless_restatement`: Complete, unambiguous fact
   - `keywords`: Core terms for search (3-7 keywords)
   - `timestamp`: ISO 8601 format if mentioned
   - `location`: Specific location name
   - `persons`: All person names involved
   - `entities`: Companies, products, organizations, etc.
   - `topic`: Brief topic phrase (2-5 words)

## Output Format (JSON only, no other text):

{
"entries": [
{
"lossless_restatement": "Complete self-contained fact...",
"keywords": ["keyword1", "keyword2", ...],
"timestamp": "2025-01-15T14:00:00" or null,
"location": "Starbucks, Downtown" or null,
"persons": ["Alice", "Bob"],
"entities": ["Company XYZ"] or [],
"topic": "Meeting arrangement"
}
]
}

Return ONLY valid JSON. No explanations or other text.

#### User Prompt（中文）

{context_section}## 待处理对话：
{dialogue_text}

---

## 提取要求：

1. **完整覆盖**: 捕获对话中所有有价值的信息。
2. **自包含事实**: 每条记忆必须能独立理解。

   - 错误示例: "他明天要和 Bob 见面"（"他"是谁？"明天"是哪天？）
   - 正确示例: "Alice 将于 2025-01-15 14:00 在星巴克与 Bob 见面"
3. **指代消解**: 将所有代词替换为实际名称。

   - 替换: 他、她、它、他们、这、那
   - 替换为: 实际的人名或实体名称
4. **时间锚定**: 将所有相对时间转换为绝对 ISO 8601 格式。

   - "明天" → 计算实际日期
   - "下周" → 计算实际日期范围
   - "两小时后" → 计算实际时间
5. **信息提取**: 对每条记忆，提取以下字段：

   - `lossless_restatement`: 完整的、无歧义的事实
   - `keywords`: 用于搜索的核心词汇（3-7 个关键词）
   - `timestamp`: ISO 8601 格式（如提及时间）
   - `location`: 具体地点名称
   - `persons`: 涉及的所有人名
   - `entities`: 公司、产品、组织等
   - `topic`: 简短主题短语（2-5 个词）

## 输出格式（仅 JSON，不要其他文字）：

{
"entries": [
{
"lossless_restatement": "完整的自包含事实...",
"keywords": ["关键词1", "关键词2", ...],
"timestamp": "2025-01-15T14:00:00" 或 null,
"location": "星巴克" 或 null,
"persons": ["Alice", "Bob"],
"entities": ["XYZ 公司"] 或 [],
"topic": "会议安排"
}
]
}

只返回有效的 JSON。不要解释或其他文字。

---

## 2. Query 分析（Query Analysis）

### 2.1 Core 版本 — 基础 Query 分析

**文件:** `core/hybrid_retriever.py`
**行号:** 180-207（`_analyze_query` 方法）
**温度:** 0.1

#### System Message

```

You are a query analysis assistant. You must output valid JSON format.

你是一个查询分析助手。你必须输出有效的 JSON 格式。

```

#### User Prompt

Analyze the following query and extract key information:

Query: {query}

Please extract:

1. keywords: List of keywords (names, places, topic words, etc.)
2. persons: Person names mentioned
3. time_expression: Time expression (if any)
4. location: Location (if any)
5. entities: Entities (companies, products, etc.)

Return in JSON format:

```json
{
  "keywords": ["keyword1", "keyword2", ...],
  "persons": ["name1", "name2", ...],
  "time_expression": "time expression or null",
  "location": "location or null",
  "entities": ["entity1", ...]
}
```

Return ONLY JSON, no other content.

---

### 2.2 Core 版本 — 高级信息需求分析

**文件:** `core/hybrid_retriever.py`
**行号:** 655-691（`_analyze_information_requirements` 方法）
**温度:** 0.2

#### System Message（原文）

```
You are an intelligent information requirement analyst. You must output valid JSON format.


你是一个智能信息需求分析师。你必须输出有效的 JSON 格式。

```

#### User Prompt（原文）

Analyze the following question and determine what specific information is required to answer it comprehensively.

Question: {query}

Think step by step:

1. What type of question is this? (factual, temporal, relational, explanatory, etc.)
2. What key entities, events, or concepts need to be identified?
3. What relationships or connections need to be established?
4. What minimal set of information pieces would be sufficient to answer this question?

Return your analysis in JSON format:

```json
{
  "question_type": "type of question",
  "key_entities": ["entity1", "entity2", ...],
  "required_info": [
    {
      "info_type": "what kind of information",
      "description": "specific information needed",
      "priority": "high/medium/low"
    }
  ],
  "relationships": ["relationship1", "relationship2", ...],
  "minimal_queries_needed": 2
}
```

Focus on identifying the minimal essential information needed, not exhaustive details.

Return ONLY the JSON, no other text.

#### User Prompt（中文）

分析以下问题，确定需要哪些具体信息才能全面回答它。

问题: {query}

逐步思考：

1. 这是什么类型的问题？（事实型、时间型、关系型、解释型等）
2. 需要识别哪些关键实体、事件或概念？
3. 需要建立哪些关系或关联？
4. 回答这个问题所需的最小信息集合是什么？

以 JSON 格式返回你的分析：

```json
{
  "question_type": "问题类型",
  "key_entities": ["实体1", "实体2", ...],
  "required_info": [
    {
      "info_type": "需要什么类型的信息",
      "description": "具体需要的信息",
      "priority": "high/medium/low"
    }
  ],
  "relationships": ["关系1", "关系2", ...],
  "minimal_queries_needed": 2
}
```

重点识别所需的最小关键信息集合，而不是穷举所有细节。

只返回 JSON，不要其他文字。

---

### 2.3 MCP Server 版本 — 带复杂度评分的 Query 分析

**文件:** `MCP/server/core/retriever.py`
**行号:** 132-160（`_analyze_information_requirements` 方法）
**温度:** 0.1

#### System Message（原文）

```

You are a query analysis expert.

你是一个查询分析专家。

```

#### User Prompt（原文）

Analyze the following question and determine retrieval requirements.

Question: {query}

Analyze:

1. What type of question is this? (factual, temporal, relational, comparative, etc.)
2. What key entities/events need to be identified?
3. What information types are required? (with priority: high/medium/low)
4. What relationships need to be established?
5. How many minimal search queries are needed? (1-4)
6. Complexity score (0.0-1.0): simple facts=0.2, multi-hop=0.6, complex reasoning=0.8+

Return JSON:
{
"question_type": "type",
"key_entities": ["entity1", "entity2"],
"required_info": [
{"type": "info_type", "priority": "high/medium/low"}
],
"relationships": ["relationship1"],
"minimal_queries_needed": 1-4,
"complexity_score": 0.0-1.0
}

Return ONLY valid JSON.

#### User Prompt（中文）

分析以下问题并确定检索需求。

问题: {query}

分析：

1. 这是什么类型的问题？（事实型、时间型、关系型、比较型等）
2. 需要识别哪些关键实体/事件？
3. 需要哪些信息类型？（标注优先级：high/medium/low）
4. 需要建立哪些关系？
5. 最少需要几条搜索查询？（1-4）
6. 复杂度评分（0.0-1.0）：简单事实=0.2，多跳推理=0.6，复杂推理=0.8+

返回 JSON：
{
"question_type": "类型",
"key_entities": ["实体1", "实体2"],
"required_info": [
{"type": "信息类型", "priority": "high/medium/low"}
],
"relationships": ["关系1"],
"minimal_queries_needed": 1-4,
"complexity_score": 0.0-1.0
}

只返回有效的 JSON。

---

## 3. Query 生成（Query Generation）

### 3.1 Core 版本 — 广撒网式搜索 Query 生成

**文件:** `core/hybrid_retriever.py`
**行号:** 349-381（`_generate_search_queries` 方法）
**温度:** 0.3

#### System Message

```

You are a search query generation assistant. You must output valid JSON format.


你是一个搜索查询生成助手。你必须输出有效的 JSON 格式。

```

#### User Prompt（原文）

You are helping with information retrieval. Given a user question, generate multiple search queries that would help find comprehensive information to answer the question.

Original Question: {query}

Please generate 3-5 different search queries that cover various aspects and angles of this question. Each query should be focused and specific.

Guidelines:

1. Include the original question as one query
2. Break down complex questions into component parts
3. Consider synonyms and alternative phrasings
4. Think about related concepts that might be relevant
5. Consider temporal, spatial, or contextual variations

Return your response in JSON format:

```json
{
  "queries": [
    "search query 1",
    "search query 2",
    "search query 3",
    ...
  ]
}
```

Return ONLY the JSON, no other text.

#### User Prompt（中文）

你正在协助信息检索。给定一个用户问题，生成多条搜索查询来帮助全面获取回答该问题所需的信息。

原始问题: {query}

请生成 3-5 条不同的搜索查询，覆盖这个问题的各个方面和角度。每条查询应聚焦且具体。

指南：

1. 将原始问题作为其中一条查询
2. 将复杂问题拆解为子问题
3. 考虑同义词和替代表述
4. 考虑可能相关的概念
5. 考虑时间、空间或上下文维度的变体

以 JSON 格式返回你的回答：

```json
{
  "queries": [
    "搜索查询 1",
    "搜索查询 2",
    "搜索查询 3",
    ...
  ]
}
```

只返回 JSON，不要其他文字。

---

### 3.2 Core 版本 — 基于需求分析的精确 Query 生成

**文件:** `core/hybrid_retriever.py`
**行号:** 723-762（`_generate_targeted_queries` 方法）
**温度:** 0.3

#### System Message（原文）

```

You are a query generation specialist. You must output valid JSON format.


你是一个查询生成专家。你必须输出有效的 JSON 格式。

```

#### User Prompt（原文）

Based on the information requirements analysis, generate the minimal set of targeted search queries needed to gather the required information.

Original Question: {original_query}

Information Requirements Analysis:

- Question Type: {information_plan.get('question_type', 'general')}
- Key Entities: {information_plan.get('key_entities', [])}
- Required Information: {information_plan.get('required_info', [])}
- Relationships: {information_plan.get('relationships', [])}
- Minimal Queries Needed: {information_plan.get('minimal_queries_needed', 1)}

Generate the minimal set of search queries that would efficiently gather all the required information. Each query should be focused and specific to retrieve distinct types of information.

Guidelines:

1. Always include the original query as one option
2. Generate only the minimal necessary queries (usually 1-3)
3. Each query should target a specific information requirement
4. Avoid redundant or overlapping queries
5. Focus on efficiency - fewer, more targeted queries are better

Return your response in JSON format:

```json
{
  "reasoning": "Brief explanation of the query strategy",
  "queries": [
    "targeted query 1",
    "targeted query 2",
    ...
  ]
}
```

Return ONLY the JSON, no other text.

#### User Prompt（中文）

基于信息需求分析的结果，生成所需的最小精确搜索查询集合。

原始问题: {original_query}

信息需求分析结果：

- 问题类型: {question_type}
- 关键实体: {key_entities}
- 所需信息: {required_info}
- 关系: {relationships}
- 最少查询数: {minimal_queries_needed}

生成最小搜索查询集合，以高效获取所有所需信息。每条查询应聚焦且具体，用于检索不同类型的信息。

指南：

1. 始终将原始查询作为其中一个选项
2. 只生成最少必要的查询（通常 1-3 条）
3. 每条查询应针对一个特定的信息需求
4. 避免冗余或重叠的查询
5. 注重效率——越少越精准的查询越好

以 JSON 格式返回你的回答：

```json
{
  "reasoning": "查询策略的简要说明",
  "queries": [
    "精确查询 1",
    "精确查询 2",
    ...
  ]
}
```

只返回 JSON，不要其他文字。

---

### 3.3 Core 版本 — 反思补漏 Query 生成

**文件:** `core/hybrid_retriever.py`
**行号:** 492-524（`_generate_additional_queries` 方法）
**温度:** 0.3

#### System Message（原文）

```
You are a search strategy assistant. You must output valid JSON format.


你是一个搜索策略助手。你必须输出有效的 JSON 格式。

```

#### User Prompt（原文）

Based on the original question and current available information, generate additional specific search queries that would help find the missing information needed to answer the question completely.

Original Question: {original_query}

Current Available Information:
{context_str}

Analyze what specific information is still missing and generate 2-4 targeted search queries that would help find this missing information.

The queries should be:

1. Specific and focused on the missing information
2. Different from the original question
3. Likely to find complementary information

Return your response in JSON format:

```json
{
  "missing_analysis": "Brief analysis of what's missing",
  "additional_queries": [
    "specific search query 1",
    "specific search query 2",
    ...
  ]
}
```

Return ONLY the JSON, no other text.

#### User Prompt（中文）

基于原始问题和当前已有的信息，生成额外的精确搜索查询，以帮助找到回答问题所缺失的信息。

原始问题: {original_query}

当前已有信息：
{context_str}

分析具体还缺少哪些信息，并生成 2-4 条精确搜索查询来帮助找到这些缺失信息。

查询应满足：

1. 具体且聚焦于缺失信息
2. 与原始问题不同
3. 能找到互补性信息

以 JSON 格式返回你的回答：

```json
{
  "missing_analysis": "缺失信息的简要分析",
  "additional_queries": [
    "具体搜索查询 1",
    "具体搜索查询 2",
    ...
  ]
}
```

只返回 JSON，不要其他文字。

---

### 3.4 Core 版本 — 智能反思补漏 Query 生成

**文件:** `core/hybrid_retriever.py`
**行号:** 914-942（`_generate_missing_info_queries` 方法）
**温度:** 0.3

#### System Message（原文）

```
You are a missing information query generator. You must output valid JSON format.


你是一个缺失信息查询生成器。你必须输出有效的 JSON 格式。

```

#### User Prompt（原文）

Based on the original question, required information types, and currently available information, generate targeted search queries to find the missing information needed to answer the question completely.

Original Question: {original_query}

Required Information Types: {required_info}

Currently Available Information:
{context_str}

Generate 1-3 specific search queries that would help find the missing information. Focus on:

1. Information gaps identified in the current context
2. Specific missing details needed to answer the original question
3. Different search angles that might retrieve the missing information

Return your response in JSON format:

```json
{
  "missing_analysis": "Brief analysis of what specific information is missing",
  "targeted_queries": [
    "specific query 1 for missing info",
    "specific query 2 for missing info",
    ...
  ]
}
```

Return ONLY the JSON, no other text.

#### User Prompt（中文）

基于原始问题、所需的信息类型和当前已有信息，生成精确搜索查询以找到回答问题所缺失的信息。

原始问题: {original_query}

所需信息类型: {required_info}

当前已有信息：
{context_str}

生成 1-3 条具体的搜索查询来帮助找到缺失信息。重点关注：

1. 当前上下文中识别出的信息缺口
2. 回答原始问题所需的具体缺失细节
3. 可能检索到缺失信息的不同搜索角度

以 JSON 格式返回你的回答：

```json
{
  "missing_analysis": "具体缺失信息的简要分析",
  "targeted_queries": [
    "针对缺失信息的具体查询 1",
    "针对缺失信息的具体查询 2",
    ...
  ]
}
```

只返回 JSON，不要其他文字。

---

### 3.5 MCP Server 版本 — 精确 Query 生成

**文件:** `MCP/server/core/retriever.py`
**行号:** 202-228（`_generate_targeted_queries` 方法）
**温度:** 0.1

#### System Message（原文）

```
You are a search query generator.

你是一个搜索查询生成器。

```

#### User Prompt（原文）

Based on the analysis, generate {plan.minimal_queries_needed} targeted search queries.

Original Question: {original_query}

Analysis:

- Question Type: {plan.question_type}
- Key Entities: {plan.key_entities}
- Required Information: {plan.required_info}
- Relationships: {plan.relationships}

Requirements:

1. Generate {plan.minimal_queries_needed} distinct queries
2. Each query should target specific information
3. Together they should cover all required information
4. Keep queries concise and focused

Return JSON:
{
"queries": ["query1", "query2", ...]
}

Return ONLY valid JSON.

#### User Prompt（中文）

基于分析结果，生成 {plan.minimal_queries_needed} 条精确搜索查询。

原始问题: {original_query}

分析结果：

- 问题类型: {plan.question_type}
- 关键实体: {plan.key_entities}
- 所需信息: {plan.required_info}
- 关系: {plan.relationships}

要求：

1. 生成 {plan.minimal_queries_needed} 条不同的查询
2. 每条查询应针对特定信息
3. 所有查询组合起来应覆盖全部所需信息
4. 查询保持简洁且聚焦

返回 JSON：
{
"queries": ["查询1", "查询2", ...]
}

只返回有效的 JSON。

---

### 3.6 MCP Server 版本 — 缺失信息补漏 Query 生成

**文件:** `MCP/server/core/retriever.py`
**行号:** 432-451（`_generate_missing_info_queries` 方法）
**温度:** 0.1

#### System Message（原文）

```
You are a search query generator.


你是一个搜索查询生成器。

```

#### User Prompt（原文）

Generate search queries to find the missing information.

Original Question: {original_query}

Missing Information:
{missing_info}

Generate 1-2 targeted search queries to find this missing information.

Return JSON:
{
"queries": ["query1", "query2"]
}

Return ONLY valid JSON.

#### User Prompt（中文）

生成搜索查询以找到缺失的信息。

原始问题: {original_query}

缺失信息：
{missing_info}

生成 1-2 条精确搜索查询来找到这些缺失信息。

返回 JSON：
{
"queries": ["查询1", "查询2"]
}

只返回有效的 JSON。

---

## 4. 充分性检查（Completeness Check）

### 4.1 Core 版本 — 基础充分性检查

**文件:** `core/hybrid_retriever.py`
**行号:** 434-464（`_check_answer_adequacy` 方法）
**温度:** 0.1

#### System Message

```
You are an information adequacy evaluator. You must output valid JSON format.


你是一个信息充分性评估者。你必须输出有效的 JSON 格式。

```

#### User Prompt（原文）

You are evaluating whether the provided context contains sufficient information to answer a user question.

Question: {query}

Context:
{context_str}

Please evaluate whether the context contains enough information to provide a meaningful, accurate answer to the question.

Consider these criteria:

1. Does the context directly address the question being asked?
2. Are there key details necessary to answer the question?
3. Is the information specific enough to avoid vague responses?

Return your evaluation in JSON format:

```json
{
  "assessment": "sufficient" OR "insufficient",
  "reasoning": "Brief explanation of why the context is or isn't sufficient",
  "missing_info": ["list", "of", "missing", "information"] (only if insufficient)
}
```

Return ONLY the JSON, no other text.

#### User Prompt（中文）

你正在评估所提供的上下文是否包含足够的信息来回答用户的问题。

问题: {query}

上下文：
{context_str}

请评估上下文是否包含足够的信息，以提供一个有意义的、准确的回答。

考虑以下标准：

1. 上下文是否直接回答了所提出的问题？
2. 回答问题所需的关键细节是否齐全？
3. 信息是否足够具体，能避免模糊的回答？

以 JSON 格式返回你的评估：

```json
{
  "assessment": "sufficient" 或 "insufficient",
  "reasoning": "上下文为何充分或不充分的简要说明",
  "missing_info": ["缺失", "的", "信息", "列表"]（仅在不充分时提供）
}
```

只返回 JSON，不要其他文字。

### 4.2 Core 版本 — 智能信息完整性分析

**文件:** `core/hybrid_retriever.py`
**行号:** 851-882（`_analyze_information_completeness` 方法）
**温度:** 0.1

#### System Message

```

You are an information completeness evaluator. You must output valid JSON format.

你是一个信息完整性评估者。你必须输出有效的 JSON 格式。

```

#### User Prompt（原文）

Analyze whether the provided information is sufficient to completely answer the original question, based on the identified information requirements.

Original Question: {query}

Required Information Types: {required_info}

Current Available Information:
{context_str}

Evaluate whether:

1. All required information types are addressed
2. The information is complete enough to provide a comprehensive answer
3. Any critical gaps remain that would prevent a satisfactory answer

Return your evaluation in JSON format:

```json
{
  "assessment": "complete" OR "incomplete",
  "reasoning": "Brief explanation of completeness assessment",
  "missing_info_types": ["list", "of", "missing", "information", "types"],
  "coverage_percentage": 85
}
```

Return ONLY the JSON, no other text.

#### User Prompt（中文）

根据已识别的信息需求，分析所提供的信息是否足以完整回答原始问题。

原始问题: {query}

所需信息类型: {required_info}

当前已有信息：
{context_str}

评估以下方面：

1. 所有所需的信息类型是否都已涵盖
2. 信息是否完整到可以提供全面的回答
3. 是否仍存在会妨碍满意回答的关键缺口

以 JSON 格式返回你的评估：

```json
{
  "assessment": "complete" 或 "incomplete",
  "reasoning": "完整性评估的简要说明",
  "missing_info_types": ["缺失", "的", "信息", "类型", "列表"],
  "coverage_percentage": 85
}
```

只返回 JSON，不要其他文字。

---

### 4.3 MCP Server 版本 — 完整性检查

**文件:** `MCP/server/core/retriever.py`
**行号:** 378-403（`_check_completeness` 方法）
**温度:** 0.1

#### System Message

```
You are an information completeness analyst.

你是一个信息完整性分析师。

```

#### User Prompt（原文）

Analyze if the retrieved information is sufficient to answer the question.

Question: {query}

Required Information:
{[info.get("type", "") for info in plan.required_info]}

Retrieved Information:
{results_text}

Determine:

1. Is the information sufficient to answer the question? (yes/no)
2. If no, what specific information is missing?

Return JSON:
{
"is_complete": true/false,
"missing_info": ["missing1", "missing2"] or []
}

Return ONLY valid JSON.

```

#### User Prompt（中文）

```

分析检索到的信息是否足以回答该问题。

问题: {query}

所需信息：
{required_info_types}

检索到的信息：
{results_text}

判断：

1. 信息是否足以回答该问题？（是/否）
2. 如果不足，具体缺少哪些信息？

返回 JSON：
{
"is_complete": true/false,
"missing_info": ["缺失信息1", "缺失信息2"] 或 []
}

只返回有效的 JSON。

---

## 5. 答案生成（Answer Generation）

### 5.1 Core 版本

**文件:** `core/answer_generator.py`
**行号:** 43-153（system message 在 L45-46，user prompt 在 `_build_answer_prompt` L117-153）
**温度:** 0.1

#### System Message

```
You are a professional Q&A assistant. Extract concise answers from context. You must output valid JSON format.


你是一个专业的问答助手。从上下文中提取简洁的回答。你必须输出有效的 JSON 格式。

```

#### User Prompt（原文）

Answer the user's question based on the provided context.

User Question: {query}

Relevant Context:
{context_str}

Requirements:

1. First, think through the reasoning process
2. Then provide a very CONCISE answer (short phrase about core information)
3. Answer must be based ONLY on the provided context
4. All dates in the response must be formatted as 'DD Month YYYY' but you can output more or less details if needed
5. Return your response in JSON format

Output Format:

```json
{
  "reasoning": "Brief explanation of your thought process",
  "answer": "Concise answer in a short phrase"
}
```

Example:
Question: "When will they meet?"
Context: "Alice suggested meeting Bob at 2025-11-16T14:00:00..."

Output:

```json
{
  "reasoning": "The context explicitly states the meeting time as 2025-11-16T14:00:00",
  "answer": "16 November 2025 at 2:00 PM"
}
```

Now answer the question. Return ONLY the JSON, no other text.

#### User Prompt（中文）

根据提供的上下文回答用户的问题。

用户问题: {query}

相关上下文：
{context_str}

要求：

1. 首先，梳理推理过程
2. 然后提供一个非常简洁的回答（围绕核心信息的短语）
3. 回答必须仅基于提供的上下文
4. 回答中所有日期必须格式化为"YYYY年MM月DD日"，但可以根据需要输出更多或更少细节
5. 以 JSON 格式返回你的回答

输出格式：

```json
{
  "reasoning": "你的思考过程的简要说明",
  "answer": "简洁的短语回答"
}
```

示例：
问题: "他们什么时候见面？"
上下文: "Alice 建议于 2025-11-16T14:00:00 与 Bob 见面……"

输出：

```json
{
  "reasoning": "上下文明确指出会议时间为 2025-11-16T14:00:00",
  "answer": "2025年11月16日下午2:00"
}
```

现在回答问题。只返回 JSON，不要其他文字。

---

### 5.2 MCP Server 版本（带置信度评分）

**文件:** `MCP/server/core/answer_generator.py`
**行号:** 56-156（system message 在 L59-62，user prompt 在 `_build_answer_prompt` L129-156）
**温度:** 0.1

#### System Message

```

You are a helpful assistant that answers questions based on provided context. Always base your answers on the given context. If the context doesn't contain enough information, say so.



你是一个有用的助手，基于提供的上下文回答问题。始终基于给定上下文来回答。如果上下文信息不足，请明确说明。

```

#### User Prompt（原文）

Answer the user's question based on the provided context.

## User Question:

{query}

## Relevant Context:

{context_str}

## Requirements:

1. Think through the reasoning process step by step
2. Base your answer ONLY on the provided context
3. Provide a CONCISE answer (short phrase or 1-2 sentences)
4. Format dates as 'DD Month YYYY' (e.g., "15 January 2025")
5. If context is insufficient, clearly state that

## Confidence Levels:

- "high": Context directly answers the question
- "medium": Context provides partial or indirect information
- "low": Context is insufficient or answer requires inference

## Output Format (JSON only):

{
"reasoning": "Brief explanation of how you derived the answer",
"answer": "Concise answer to the question",
"confidence": "high/medium/low"
}

Return ONLY valid JSON. No other text.

#### User Prompt（中文）

根据提供的上下文回答用户的问题。

## 用户问题：

{query}

## 相关上下文：

{context_str}

## 要求：

1. 逐步思考推理过程
2. 回答必须仅基于提供的上下文
3. 提供简洁的回答（短语或 1-2 句话）
4. 日期格式为"YYYY年MM月DD日"（例如"2025年1月15日"）
5. 如果上下文信息不足，请明确说明

## 置信度等级：

- "high": 上下文直接回答了问题
- "medium": 上下文提供了部分或间接信息
- "low": 上下文不足或回答需要推理

## 输出格式（仅 JSON）：

{
"reasoning": "回答是如何推导出来的简要说明",
"answer": "对问题的简洁回答",
"confidence": "high/medium/low"
}

只返回有效的 JSON。不要其他文字。

---

## 6. 记忆摘要（Memory Summarization）

### 6.1 MCP Server 版本

**文件:** `MCP/server/core/answer_generator.py`
**行号:** 184-195（`generate_summary` 方法）
**温度:** 0.1

#### System Message

```

You are a helpful summarization assistant.

你是一个有用的摘要助手。

```

#### User Prompt（原文）

Summarize the following memories{topic_str}:

{entries_text}

Provide a concise summary (2-4 sentences) that captures the key information.

Return ONLY the summary text, no JSON or formatting.

#### User Prompt（中文）

总结以下记忆{topic_str}：

{entries_text}

提供一个简洁的摘要（2-4 句话），捕获关键信息。

只返回摘要文字，不要 JSON 或格式化。

---

## 附录：参数与设计模式速查


| 阶段               | 温度                    | 重试次数         | 输出格式                               |
| -------------------- | ------------------------- | ------------------ | ---------------------------------------- |
| 记忆提取           | 0.1                     | 3                | JSON array / JSON object with`entries` |
| Query 基础分析     | 0.1                     | 3                | JSON object                            |
| Query 需求分析     | 0.1-0.2                 | 1（有 fallback） | JSON object                            |
| Query 生成（各类） | 0.3（Core）/ 0.1（MCP） | 1（有 fallback） | JSON object with`queries`              |
| 充分性检查         | 0.1                     | 1（有 fallback） | JSON object                            |
| 答案生成           | 0.1                     | 3                | JSON object with`answer`               |
| 记忆摘要           | 0.1                     | 1                | 纯文本                                 |

**核心设计原则：**

- 记忆条目必须 **self-contained**：无代词、绝对时间戳
- Query 生成走 **minimal queries** 策略：通常 1-3 条，最多 4 条
- 反思循环最多 **2 轮**，防止无限检索
- MCP 版增加了 **complexity_score** 用于控制是否启用反思
- 所有 LLM 调用都要求 **JSON-only 输出**
