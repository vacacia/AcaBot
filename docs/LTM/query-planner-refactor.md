# LTM Query Planner User Message 重构

## 现状问题

`LtmQueryPlannerClient.plan_query()` 发给模型的 user message 是 `json.dumps(request_payload)`, 存在以下问题:

1. **retained_history 全量透传** -- compaction 后可能还有 20-40 条消息, 每条都是 `{"role": "...", "content": "..."}` dict, 全部序列化成 JSON 丢给 query planner 小模型, token 浪费严重
2. **metadata 无关字段** -- `token_stats` / `run_mode` / `sender_role` / `event_policy_id` 对"怎么拆查询"没有帮助
3. **raw JSON dump** -- 模型收到一坨 JSON, 没有结构化提示, 可能直接忽略 retained_history 只看 query_text
4. **没有当前时间** -- prompt 要求输出 ISO 日期的 time_range, 但模型不知道"现在"是什么时候, 无法把"上个月"换算成具体日期
5. **没有发言人身份** -- 模型不知道当前发言人是谁, 第一人称 ("我之前说过什么") 无法解析成精确的人物标识
6. **persons 格式不对齐** -- extraction 写入的是 `"qq:user:10001(小明)"`, query planner 只能输出 `"小明"`, storage 的 `issubset` 精确匹配永远不命中, symbolic 的人名检索静默失效

另外 `working_summary` 是很久之前被压缩掉的消息的摘要, 对 query planning 没有参考价值.

## 目标

- 只取最近 N 条消息 (N 默认 10, 可在 WebUI 配置)
- user message 用人类可读格式: 当前时间 + 发言人身份 + 最近 N 条对话消息
- 最后一条用户消息就是触发检索的 query, 它是对话流的一部分, 不单独拆出来
- 不传 working_summary / metadata 等无用字段
- persons 匹配兼容精确格式、actor_id 前缀、纯显示名三种查询

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
   - persons: 第一人称用发言人行给出的完整标识, 第三人称用显示名
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

- **当前时间**: 来自 `request.event_timestamp`, 转 CST (+08:00)
- **发言人**: 来自 `request.actor_id` + `request.actor_display_name`, 拼成 `qq:user:10001(小明)` 格式
  - 第一人称 ("我之前说过什么") → planner 输出 `qq:user:10001(小明)`, 精确匹配
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
| 示例六 | 第一人称, 用发言人完整标识 | "我之前说过什么" → persons 填发言人行的完整标识 |

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

### entities 范围跨 prompt 不对齐

extraction prompt 只提取"公司、产品、组织、作品、具体事物", 但 query planner 示例一
在 entities 里放了"钢琴"(通用名词). 两侧对 entities 的范围理解不一致, 会导致
symbolic 路的 entities 过滤命中率偏低. 后续统一两侧定义.

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

### 3. 补全 actor_display_name 数据流

**问题**: `SharedMemoryRetrievalRequest` 只有 `actor_id` ("qq:user:10001"),
没有显示名. 但显示名在 `RunContext` 里是可用的:

```
RunContext.event.sender_nickname = "小明"    ← StandardEvent 里, gateway 层采集的
RunContext.decision.actor_id = "qq:user:10001"
```

`MemoryBroker._build_retrieval_request(ctx)` 构造 SharedMemoryRetrievalRequest 时
只取了 `ctx.decision.actor_id`, 没取 `ctx.event.sender_nickname`.

**修法**: 最小改动, 只在 memory 层补字段, 不动 EventFacts / RouteDecision 等核心契约.

**(a) `SharedMemoryRetrievalRequest` 加字段** (`memory_broker.py`):
```python
actor_display_name: str = ""
```

**(b) `_build_retrieval_request` 取值** (`memory_broker.py`):
```python
actor_display_name=str(ctx.event.sender_nickname or ""),
```

数据来源链路:
```
QQ 事件 sender.nickname: "小明"
  → StandardEvent.sender_nickname: "小明"    (gateway/napcat.py)
  → RunContext.event.sender_nickname: "小明"  (contracts/context.py)
  → SharedMemoryRetrievalRequest.actor_display_name: "小明"  (memory_broker.py)
```

### 4. 重写 `_build_plan_request` -- 核心改动

**source.py** -- `_build_plan_request` 从 `@staticmethod` 改成普通方法.
需要加 `import datetime`.

输入: `SharedMemoryRetrievalRequest`, 其中:
- `retained_history`: compaction 后保留的消息 dict 列表
- `event_timestamp`: 触发事件的 unix 时间戳 (int)
- `actor_id`: 触发事件的用户身份标识 (str), 例如 `"qq:user:10001"`
- `actor_display_name`: 触发事件的用户显示名 (str), 例如 `"小明"`

输出: 一段人类可读文本, 直接作为 `plan_query` 的 user message.

```python
def _build_plan_request(self, request: SharedMemoryRetrievalRequest) -> str:
    import datetime

    # 取最后 N 条消息
    n = max(1, self.query_context_messages)
    recent = request.retained_history[-n:]

    # 第一行: 当前时间
    # 来源: request.event_timestamp (触发事件的 unix 时间戳)
    # 用途: 让模型把 "上个月" / "去年" 等相对时间换算成 ISO 日期
    # 时区: 固定 +08:00 (CST), 因为 QQ 场景用户全在中国
    cst = datetime.timezone(datetime.timedelta(hours=8))
    now_iso = datetime.datetime.fromtimestamp(request.event_timestamp, tz=cst).isoformat()
    lines = [f"当前时间: {now_iso}"]

    # 第二行: 发言人身份
    # 来源: request.actor_id + request.actor_display_name
    # 用途: 第一人称场景 ("我之前说过什么") 模型能输出精确的 persons 标识
    # 格式: "qq:user:10001(小明)" -- 和 extraction 写入的 persons 格式一致
    actor_id = str(request.actor_id or "").strip()
    display_name = str(request.actor_display_name or "").strip()
    if display_name:
        lines.append(f"发言人: {actor_id}({display_name})")
    else:
        lines.append(f"发言人: {actor_id}")

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

### 5. 修复 persons 格式不对齐 -- storage 层兼容三种匹配

**问题**: extraction 写入 `"qq:user:10001(小明)"`, query planner 可能输出三种格式:
- `"qq:user:10001(小明)"` -- 第一人称, 精确匹配
- `"qq:user:10001"` -- 第一人称但模型只输出了 actor_id 部分
- `"小明"` / `"阿华"` -- 第三人称, 只有显示名

当前 `structured_search` 用 `issubset` 精确匹配, 后两种都不命中.

**修法**: `storage.py` 加 `_person_matches` 函数, 支持三种匹配:

```python
def _person_matches(query_person: str, entry_persons: list[str]) -> bool:
    """判断一个查询人名是否匹配 entry 的 persons 列表.

    支持三种匹配 (存储格式为 "qq:user:10001(小明)"):
    - 精确匹配: "qq:user:10001(小明)" == "qq:user:10001(小明)"
    - actor_id 前缀匹配: "qq:user:10001" 匹配 "qq:user:10001(小明)" 括号前的部分
    - 显示名匹配: "小明" 匹配 "qq:user:10001(小明)" 括号里的部分
    """
    for stored in entry_persons:
        # 精确匹配
        if query_person == stored:
            return True
        # 存储值带括号格式时, 拆出 actor_id 前缀和显示名
        if "(" in stored and stored.endswith(")"):
            paren_idx = stored.index("(")
            actor_id_part = stored[:paren_idx]
            display_name = stored[paren_idx + 1 : -1]
            # actor_id 前缀匹配
            if query_person == actor_id_part:
                return True
            # 显示名匹配
            if query_person == display_name:
                return True
    return False
```

`structured_search` 里的 persons 过滤从:
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

### 6. 改 `plan_query` 签名

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

### 7. WebUI 加配置项

**LtmConfigView.vue** -- 加 `query_context_messages` 数字输入框.

### 8. 更新 prompt (query_planner_system.txt)

在现有 prompt 基础上:
- 输入格式说明加 "第二行是发言人身份, 格式为 actor_id(显示名)"
- persons 写法说明加: "第一人称用发言人行给出的完整标识, 第三人称用显示名"
- 加第一人称示例 (示例六)
- 修正示例四: `用户(猫猫):` 格式改成纯 `用户:` (代码只生成这种格式)

## 涉及文件

| 文件 | 改动 |
|------|------|
| `config.example.yaml` | 加 `query_context_messages: 10` |
| `src/acabot/runtime/control/config_control_plane.py` | get/upsert 加字段 |
| `src/acabot/runtime/bootstrap/builders.py` | 传配置给 LtmMemorySource |
| `src/acabot/runtime/memory/memory_broker.py` | SharedMemoryRetrievalRequest 加 `actor_display_name` 字段, _build_retrieval_request 取值 |
| `src/acabot/runtime/memory/long_term_memory/source.py` | 加字段, 重写 `_build_plan_request`, 改 Protocol 签名 |
| `src/acabot/runtime/memory/long_term_memory/model_clients.py` | `plan_query` 参数从 dict 改 str |
| `src/acabot/runtime/memory/long_term_memory/storage.py` | 加 `_person_matches`, `structured_search` 的 persons 匹配兼容三种格式 |
| `src/acabot/runtime/memory/long_term_memory/prompts/query_planner_system.txt` | 加发言人说明 + 第一人称示例 + 修示例四格式 |
| `webui/src/views/LtmConfigView.vue` | 加表单项 |

## 数据流 (改后)

```
QQ 事件
│ user_id: "10001", sender.nickname: "小明"
↓
StandardEvent (gateway/napcat.py)
│ source.user_id: "10001"
│ sender_nickname: "小明"
↓
RunContext (contracts/context.py)
│ event.sender_nickname: "小明"
│ decision.actor_id: "qq:user:10001"
↓
MemoryBroker._build_retrieval_request(ctx) (memory_broker.py)
│ actor_id = ctx.decision.actor_id               → "qq:user:10001"
│ actor_display_name = ctx.event.sender_nickname  → "小明"        ← 新增
↓
SharedMemoryRetrievalRequest
│ actor_id: "qq:user:10001"
│ actor_display_name: "小明"                                      ← 新增
│ event_timestamp: 1743494400
│ retained_history: [{role, content}, ...]
↓
LtmMemorySource._build_plan_request(request)
│ 格式化成 user message:
│   当前时间: 2025-04-01T15:00:00+08:00           ← event_timestamp (CST)
│   发言人: qq:user:10001(小明)                    ← actor_id + actor_display_name
│   用户: 阿华下周要出差                           ← retained_history 最后 N 条
│   助手: 去哪里?
│   ...
│   用户: 他之前说过对什么过敏来着?                 ← 最后一条就是 query
↓
LtmQueryPlannerClient.plan_query(user_message: str)
│ 直接作为 user message 发给模型
↓
模型返回 plan, symbolic_filters.persons 可能是:
│ ["qq:user:10001(小明)"]   -- 第一人称, 完整标识
│ ["qq:user:10001"]         -- 第一人称, 只有 actor_id
│ ["阿华"]                  -- 第三人称, 只有显示名
↓
storage.structured_search → _person_matches 兼容三种格式
│ "qq:user:10001(小明)" == "qq:user:10001(小明)"  → 精确匹配 ✓
│ "qq:user:10001" == "qq:user:10001(小明)"[:括号前] → actor_id 前缀匹配 ✓
│ "阿华" == "qq:user:20001(阿华)"[括号内]          → 显示名匹配 ✓
```
