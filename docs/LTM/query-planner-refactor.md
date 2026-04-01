# LTM Query Planner User Message 重构

## 现状问题

`LtmQueryPlannerClient.plan_query()` 发给模型的 user message 是 `json.dumps(request_payload)`, 存在以下问题:

1. **retained_history 全量透传** -- compaction 后可能还有 20-40 条消息, 每条都是 `{"role": "...", "content": "..."}` dict, 全部序列化成 JSON 丢给 query planner 小模型, token 浪费严重
2. **metadata 无关字段** -- `token_stats` / `run_mode` / `sender_role` / `event_policy_id` 对"怎么拆查询"没有帮助
3. **raw JSON dump** -- 模型收到一坨 JSON, 没有结构化提示, 可能直接忽略 retained_history 只看 query_text
4. **没有当前时间** -- prompt 要求输出 ISO 日期的 time_range, 但模型不知道"现在"是什么时候, 无法把"上个月"换算成具体日期
5. **没有发言人身份** -- 模型不知道当前发言人的 actor_id, 第一人称 ("我之前说过什么") 无法解析成精确的人物标识
6. **persons 格式不对齐** -- extraction 写入的是 `"qq:user:10001(小明)"`, query planner 只能输出 `"小明"`, storage 的 `issubset` 精确匹配永远不命中, symbolic 的人名检索静默失效

另外 `working_summary` 是很久之前被压缩掉的消息的摘要, 对 query planning 没有参考价值.

## 目标

- 只取最近 N 条消息 (N 默认 10, 可在 WebUI 配置)
- user message 用人类可读格式: 当前时间 + 发言人身份 + 最近 N 条对话消息
- 最后一条用户消息就是触发检索的 query, 它是对话流的一部分, 不单独拆出来
- 不传 working_summary / metadata 等无用字段
- persons 匹配兼容精确 actor_id 格式和纯显示名两种查询

## Prompt 设计 (已写入 prompts/query_planner_system.txt)

### System Prompt 结构

```
1. 任务说明
2. 输入格式说明 -- 第一行当前时间, 第二行发言人身份, 后续是对话消息
3. 核心原则 -- 群聊消息很碎, 必须结合上下文理解最后一条消息的意图
4. 分析步骤 -- 引导模型先理解再生成
5. 输出格式 -- JSON 固定三字段
6. 三路查询写法说明 -- 每路的用途 + 写法规则
   - time_range: 用当前时间把相对时间换算成 ISO 日期
   - persons: 第一人称用发言人的 actor_id(显示名) 格式, 第三人称用显示名
7. 决策原则 -- 上下文是核心 / 什么时候留空 / 两路互补
8. 示例 -- 覆盖不同场景, 包括第一人称和第三人称
```

### User Message 格式

```
当前时间: 2025-04-01T15:00:00+08:00
发言人: qq:user:10001(小明)
用户: 阿华下周要出差
助手: 去哪里?
用户: 好像是上海, 三天
助手: 注意安全
用户: 他之前说过对什么过敏来着?
```

- **当前时间**: 来自 `request.event_timestamp`, 用于相对时间换算
- **发言人**: 来自 `request.actor_id`, 触发本次检索的用户身份
  - 第一人称 ("我之前说过什么") → planner 可以输出 `qq:user:10001(小明)`, 精确匹配
  - 第三人称 ("阿华对什么过敏") → planner 只能输出 `阿华`, 显示名匹配

对比改前 (raw JSON dump, 没有时间, 没有发言人身份):
```json
{
  "query_text": "他之前说过对什么过敏来着?",
  "conversation_id": "qq:group:67890",
  "working_summary": "最近在聊出差和饮食...",
  "retained_history": [
    {"role": "user", "content": "阿华下周要出差"},
    ...可能20-40条...
  ],
  "metadata": {"token_stats": {...}, "run_mode": "...", ...}
}
```

### 示例覆盖的场景

| 示例 | 场景 | 要点 |
|------|------|------|
| 示例一 | 上下文有补充线索 | 上下文提到拜厄, 补充到 lexical 和 entities |
| 示例二 | 第三人称指代推断 | "他"→上下文里的阿华, persons 只能填显示名 |
| 示例三 | 相对时间换算 | "上个月" + 当前时间 2025-04 → time_range 2025-03 |
| 示例四 | 单条消息看不懂, 必须靠上下文 | "那个东西"无意义, 结合上下文知道和猫猫北京行程有关 |
| 示例五 | 纯闲聊, 无检索价值 | 三路全空 |
| 示例六 | 第一人称, 发言人身份可用 | "我之前说过什么" → persons 填 actor_id(显示名) 格式 |

### 参考 SimpleMem 借鉴的设计

| 技术 | SimpleMem 做法 | AcaBot 采纳情况 |
|------|---------------|----------------|
| 分步思考 | "Think step by step" + question_type/key_entities 结构化 | 采纳: 加了三步分析引导 |
| 多示例 | 每个 prompt 1-2 个示例 | 采纳: 覆盖多种边界场景 |
| 分析和生成分离 | 两次 LLM 调用: 先分析后生成 | 不采纳: 合并成一步, 减少延迟 |
| 充分性检查+补漏 | 检索后判断够不够, 不够再搜 | 不采纳: 第一版跳过, 复杂度太高 |

## 已知待处理问题

### 系统补充 wrapper 文本

runtime 里 `MemoryBroker._user_content()` 可能会把 `memory_candidates` 包装成
`[系统补充-{label}: {text}]` 格式拼到 query_text 里. 这些 wrapper 文本如果直接
出现在对话流中, query planner 可能会把它当成检索关键词.

**当前状态**: 尚未确定 wrapper 的最终格式, 暂不处理.
**后续**: 格式确定后, 在 `_build_plan_request` 里做清洗, 在代码里注释清楚这个问题.

## 代码改动方案

### 1. 加配置字段 `query_context_messages`

**config.example.yaml** -- `runtime.long_term_memory` 块加:
```yaml
query_context_messages: 10  # query planner 读取最近几条消息作为上下文
```

**config_control_plane.py** -- get/upsert 都加上这个字段, 跟 `max_entries` 同样的模式.
注意 0 值边界: `max(1, int(...))` 保底, 因为 Python 切片 `list[-0:]` 返回全部列表.

### 2. 把配置传进 LtmMemorySource

**source.py** -- `LtmMemorySource` dataclass 加字段:
```python
query_context_messages: int = 10
```

**builders.py** -- `build_long_term_memory_source` 读配置传入.

### 3. 重写 `_build_plan_request` -- 核心改动

**source.py** -- `_build_plan_request` 从 `@staticmethod` 改成普通方法.
需要加 `import datetime`.

输入: `SharedMemoryRetrievalRequest`, 其中:
- `retained_history`: compaction 后保留的消息 dict 列表, 每条 `{"role": "...", "content": "..."}`
- `event_timestamp`: 触发事件的 unix 时间戳 (int), 这就是当前时间的来源
- `actor_id`: 触发事件的用户身份标识 (str), 例如 `"qq:user:10001"`

输出: 一段人类可读文本, 直接作为 `plan_query` 的 user message.

```python
def _build_plan_request(self, request: SharedMemoryRetrievalRequest) -> str:
    import datetime

    # 取最后 N 条消息
    n = max(1, self.query_context_messages)
    recent = request.retained_history[-n:]

    # 第一行: 当前时间
    # 来源: SharedMemoryRetrievalRequest.event_timestamp (触发事件的 unix 时间戳)
    # 用途: 让模型把 "上个月" / "去年" 等相对时间换算成 ISO 日期
    # 时区: 固定 +08:00 (CST), 因为 QQ 场景用户全在中国
    cst = datetime.timezone(datetime.timedelta(hours=8))
    now_iso = datetime.datetime.fromtimestamp(request.event_timestamp, tz=cst).isoformat()
    lines = [f"当前时间: {now_iso}"]

    # 第二行: 发言人身份
    # 来源: SharedMemoryRetrievalRequest.actor_id
    # 用途: 让模型在第一人称场景 ("我之前说过什么") 能输出精确的 actor_id 格式
    # 到 symbolic_filters.persons, 和 extraction 写入的 "qq:user:10001(小明)" 格式匹配
    lines.append(f"发言人: {request.actor_id}")

    # 后续行: 最近 N 条对话消息
    # 最后一条用户消息就是触发检索的 query, 不单独拆出来
    #
    # TODO: 当 memory_candidates wrapper 格式确定后,
    # 在这里清洗 content 中的 [系统补充-...] 包装文本,
    # 避免 query planner 把 wrapper 当成检索关键词.
    for msg in recent:
        role = msg.get("role", "")
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        if role not in ("user", "assistant"):
            continue  # 跳过 system/tool 等非对话消息
        label = "用户" if role == "user" else "助手"
        lines.append(f"{label}: {content}")

    return "\n".join(lines)
```

### 4. 修复 persons 格式不对齐 -- storage 层兼容匹配

**问题**: extraction 写入 `"qq:user:10001(小明)"`, query planner 可能输出两种格式:
- 第一人称: `"qq:user:10001(小明)"` (精确, 因为 user message 里带了发言人 actor_id)
- 第三人称: `"小明"` (只有显示名, 因为 planner 不知道第三方的 actor_id)

当前 `structured_search` 用 `issubset` 精确匹配, `"小明"` 永远不等于 `"qq:user:10001(小明)"`.

**修法**: `storage.py` 的 `structured_search` 改 persons 匹配逻辑:

```python
def _person_matches(query_person: str, entry_persons: list[str]) -> bool:
    """判断一个查询人名是否匹配 entry 的 persons 列表.

    支持两种匹配:
    - 精确匹配: "qq:user:10001(小明)" == "qq:user:10001(小明)"
    - 显示名匹配: "小明" 匹配 "qq:user:10001(小明)" 括号里的部分
    """
    for stored in entry_persons:
        if query_person == stored:
            return True
        # 从 "qq:user:10001(小明)" 里提取括号内的显示名
        if "(" in stored and stored.endswith(")"):
            display_name = stored[stored.index("(") + 1 : -1]
            if query_person == display_name:
                return True
    return False
```

然后 `structured_search` 里的 persons 过滤从:
```python
if normalized_persons and not normalized_persons.issubset(set(entry.persons)):
    continue
```
改成:
```python
if normalized_persons and not all(
    _person_matches(p, entry.persons) for p in normalized_persons
):
    continue
```

### 5. 改 `plan_query` 签名

**model_clients.py** -- `plan_query` 参数从 `dict[str, Any]` 改成 `str`, 不再 `json.dumps`:
```python
async def plan_query(self, user_message: str) -> dict[str, Any]:
    # ...
    response = await self.agent.complete(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        # ...
    )
```

**source.py** -- Protocol `QueryPlannerClient` 签名同步修改.

### 6. WebUI 加配置项

**LtmConfigView.vue** -- 加 `query_context_messages` 数字输入框.

### 7. 更新 prompt (query_planner_system.txt)

在现有 prompt 基础上追加:
- 输入格式说明加 "第二行是发言人身份"
- persons 写法说明加: "第一人称用发言人的完整标识, 第三人称用显示名"
- 加第一人称示例

## 涉及文件

| 文件 | 改动 |
|------|------|
| `config.example.yaml` | 加 `query_context_messages: 10` |
| `src/acabot/runtime/control/config_control_plane.py` | get/upsert 加字段 |
| `src/acabot/runtime/bootstrap/builders.py` | 传配置给 LtmMemorySource |
| `src/acabot/runtime/memory/long_term_memory/source.py` | 加字段, 重写 `_build_plan_request`, 改 Protocol 签名 |
| `src/acabot/runtime/memory/long_term_memory/model_clients.py` | `plan_query` 参数从 dict 改 str |
| `src/acabot/runtime/memory/long_term_memory/storage.py` | `structured_search` 的 persons 匹配改成兼容显示名 |
| `src/acabot/runtime/memory/long_term_memory/prompts/query_planner_system.txt` | 加发言人身份说明 + 第一人称示例 |
| `webui/src/views/LtmConfigView.vue` | 加表单项 |

## 数据流 (改后)

```
ThreadPipeline
  -> ContextCompactor 产出 effective_compacted_messages
  -> RetrievalPlanner 包进 RetrievalPlan.retained_history
  -> MemoryBroker 包进 SharedMemoryRetrievalRequest:
       .retained_history  = 消息 dict 列表
       .event_timestamp   = 触发事件的 unix 时间戳
       .actor_id          = 触发事件的用户身份标识
  -> LtmMemorySource._build_plan_request(request)
       格式化成:
         当前时间: 2025-04-01T15:00:00+08:00    ← request.event_timestamp (CST)
         发言人: qq:user:10001(小明)             ← request.actor_id
         用户: ...                               ← retained_history 最后 N 条
         助手: ...
         用户: ...                               ← 最后一条用户消息就是 query
  -> LtmQueryPlannerClient.plan_query(user_message: str)
       直接作为 user message 发给模型
  -> plan 里的 symbolic_filters.persons 可能是:
       ["qq:user:10001(小明)"]  (第一人称, 精确匹配)
       ["阿华"]                 (第三人称, 显示名匹配)
  -> storage.structured_search 兼容两种格式
```
