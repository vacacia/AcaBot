# Pitfalls Research

**Domain:** AcaBot v1.1 -- 在已有 runtime 上增加 scheduler tool 暴露、WebUI 管理页、群聊过滤修复、AstrBot LTM 迁移
**Researched:** 2026-04-05
**Confidence:** HIGH（基于直接阅读项目源码，pitfall 均从代码结构推导得出）

---

## Critical Pitfalls

### Pitfall 1: Scheduler Tool 的 callback 生命周期与 ToolExecutionContext 脱节

**What goes wrong:**
模型通过 tool 创建一个 one-shot 定时消息，scheduler 在未来某个时间点触发 callback。但 callback 注册时的 `ToolExecutionContext`（包含 run_id、thread_id、target 等）在原始 tool 调用结束后就失效了。如果在 callback 里直接使用当时捕获的 ctx 去发消息，target 信息可能已经过期（比如群成员变动），或者 gateway WebSocket 已经断线重连。

**Why it happens:**
`RuntimeScheduler.register()` 的 callback 类型是 `Callable[[], Awaitable[None]]` -- 一个零参数协程。这意味着 callback 必须在注册时通过闭包捕获所有需要的状态。而 AcaBot 的消息发送链路（Outbox -> Gateway.send -> NapCat）依赖 `EventSource`（target）、`Action`（payload + reply_to）和活跃的 WebSocket 连接。这些都不是 scheduler callback 天然能访问的。

**How to avoid:**
1. scheduler tool handler 不应该直接注册发消息的 callback。应创建一个中间层 `ScheduledMessageDispatcher`，它持有 gateway 和 notification_send_context 的引用。
2. callback 注册时只保存最小必要信息：`conversation_id`、`message_text`、`schedule_type`。触发时由 dispatcher 重新构造 `RunContext`（复用 `prepare_notification_run_context` 的逻辑）和 `Action`。
3. 持久化任务（`persist=True`）恢复时 callback 为 None，需要明确的 callback 重绑定协议。tool 创建的定时消息应该用 owner 标识（如 `tool:scheduler:<task_id>`）让 runtime 启动时能重新绑定。

**Warning signs:**
- scheduler tool 的 handler 函数里出现 `ctx.target`、`ctx.run_id` 等被闭包捕获的变量
- 持久化任务恢复后日志出现 "Skipping task with no callback"
- 定时消息发送成功但发到了错误的会话（conversation_id 硬编码但群号变了）

**Phase to address:**
Phase 2（模型可用 scheduler tool）-- 必须在 tool 实现的第一天就设计 callback 生命周期

---

### Pitfall 2: 群聊 "仅回复 @ 和引用" 过滤回归 -- targets_self 推导链断裂

**What goes wrong:**
群聊中 bot 应该只响应 @ 自己和引用自己消息的情况，但实际表现为全部回复或全部不回复。

**Why it happens:**
过滤决策依赖一条多步推导链：(1) NapCat 发来 OneBot v11 原始 JSON -> (2) `_translate_message()` 提取 `mentioned_user_ids` 和 `reply_reference` -> (3) 与 `self_id` 比对算出 `mentions_self` 和 `reply_targets_self` -> (4) 组合为 `targets_self` -> (5) `build_facts()` 搬运到 `EventFacts.targets_self` -> (6) `MatchSpec.matches()` 用 `targets_self` 做准入判断 -> (7) `_surface_candidates()` 用 `mentions_self` / `reply_targets_self` 选择 surface -> (8) admission domain 的 cases 用这些字段决定 respond/silent_drop。

这条链上任何一个环节出错都会导致 bug：
- `self_id` 未正确获取（NapCat 通过 `X-Self-ID` header 传递，如果 bot 启动时 NapCat 还没连接，`self_id` 为 None，所有 `mentions_self` 和 `reply_targets_self` 判断都失效）
- session config 的 admission domain 里 `message_filter` 配置值（如 `mention_or_reply`）没有正确映射到 `MatchSpec` 的 `targets_self` / `mentions_self` / `reply_targets_self` 字段
- surface candidate 推导中 `_surface_candidates()` 的优先级逻辑（`message.mention` > `message.reply_to_bot` > `message.plain`）可能让 reply_to_bot 场景走了错误的 surface 配置

**How to avoid:**
1. 修复第一步：在 `_handle_connection()` 中确保 `self_id` 被正确设置。检查是否有 race condition -- NapCat 重连后 `self_id` 更新了但旧的 `self_id` 还在内存中被使用。
2. 添加诊断日志：在 `_translate_message()` 结束时 log `mentions_self`、`reply_targets_self`、`targets_self` 的值和推导过程。
3. 为 admission domain 写端到端测试覆盖四种模式：`all`、`mention_only`、`reply_only`、`mention_or_reply`，每种模式都要测 `@bot`、`引用bot消息`、`@别人`、`普通消息` 四种场景。
4. 检查 `session_loader.py` 中 `message_filter` 到 `MatchSpec` 的映射逻辑，确认 `reply_only` 正确设置了 `reply_targets_self=True` 而不是 `targets_self=True`。

**Warning signs:**
- 日志中 `NapCat connected, self_id=None`
- group 消息的 `targets_self` 始终为 False（或始终为 True）
- admission decision 的 reason 显示 "default" 而不是命中的 case_id
- `_surface_candidates()` 返回 `["message.plain"]` 而不是 `["message.mention", "message.plain"]`

**Phase to address:**
Phase 1（修复群聊 bug）-- 这是最优先的 P1 bug，必须第一时间修复

---

### Pitfall 3: WebUI Scheduler 管理页与 asyncio Scheduler 的线程安全问题

**What goes wrong:**
WebUI HTTP server 运行在 `ThreadingHTTPServer` 的独立线程中，而 `RuntimeScheduler` 运行在 asyncio event loop 中。WebUI 的 CRUD 操作（创建/取消/禁用任务）直接调用 scheduler 方法时，会从非 event loop 线程访问 scheduler 的 `_tasks` dict 和 `_heap`。这可能导致：
- 在 HTTP 线程修改 `_tasks` 的同时，worker loop 在 asyncio 线程读取 `_tasks`，dict 迭代器抛出 `RuntimeError: dictionary changed size during iteration`
- `list_tasks()` 返回的数据与实际不一致（读到半更新状态）

**Why it happens:**
`http_api.py` 中已有 `_await()` 方法通过 `run_coroutine_threadsafe` 桥接 HTTP 线程到 asyncio 线程，但仅用于 async 方法。`RuntimeScheduler.list_tasks()` 是同步方法，调用者可能直接调用而不走 `_await()`。更危险的是 `cancel()` 和 `register()` 是 async 方法但操作共享可变状态（`_tasks`、`_heap`），如果有人绕过 `_await()` 直接调用就会出问题。

**How to avoid:**
1. 所有 scheduler 操作（包括 `list_tasks()`）必须通过 `_await()` 桥接到 event loop 线程执行。
2. 或者为 `RuntimeScheduler` 添加一个 `asyncio.Lock`，所有公开方法先获取锁。
3. WebUI 的 list 操作改为直接读 SQLite store（`SQLiteScheduledTaskStore.list_enabled()`）而非内存中的 `_tasks` -- 这样避免与 worker loop 竞争，且能看到持久化的历史任务。
4. 写操作（创建/取消/禁用）走 async dispatch，操作后发一个信号让 scheduler 刷新内存状态。

**Warning signs:**
- WebUI 任务列表偶尔少一个刚创建的任务
- 日志中出现 `RuntimeError: dictionary changed size during iteration`
- WebUI 禁用任务后，任务仍然触发了回调

**Phase to address:**
Phase 3（WebUI scheduler 管理页面）

---

### Pitfall 4: AstrBot 历史数据 Schema 差异导致 LTM 迁移质量灾难

**What goes wrong:**
AstrBot 的聊天历史以 `PlatformMessageHistory`（`platform_id`, `user_id`, `content: dict`）存储，content 是原始消息链 JSON。如果迁移脚本只是简单地把 `content["text"]` 填入 AcaBot LTM 的 `MemoryEntry.lossless_restatement`，会导致：
- `lossless_restatement` 包含消息链格式噪音（如 CQ 码残留）
- `topic` 字段缺失或填充为消息前几个字，失去语义价值
- `keywords`、`persons`、`entities` 全部为空 -- LTM 的多路检索（lexical + structured）完全失效
- `provenance.fact_ids` 为空 -- 违反 MemoryEntry 的非空约束

**Why it happens:**
AstrBot 的消息历史是原始平台消息的持久化，没有经过 LLM 提取。AcaBot 的 LTM 设计假定每条 MemoryEntry 都经过 extractor（LLM 提取）生成，包含结构化的 topic、keywords、persons、entities。两套系统的"记忆"粒度完全不同：AstrBot 是消息级，AcaBot 是事实级。

**How to avoid:**
1. 迁移不能只是数据搬移，必须包含 LLM 提取步骤。复用 AcaBot 现有的 `LtmExtractor` 对 AstrBot 消息进行窗口化提取。
2. 或者如果不想消耗 LLM token，至少做 NLP 预处理：提取消息文本、识别命名实体、生成关键词。
3. `provenance.fact_ids` 是必填字段，迁移时需要为每条历史生成稳定的 fact_id（如基于消息哈希）。
4. `conversation_id` 映射：AstrBot 的 `user_id` + `platform_id` 需要映射到 AcaBot 的 `platform:group:group_id` 或 `platform:user:user_id` 格式。
5. 消息去重：AcaBot LTM 使用 `entry_id` 做主键，迁移时需要幂等性设计（重复运行不产生重复 entry）。

**Warning signs:**
- 迁移后 LTM 检索测试返回空结果（keywords/entities 为空导致结构检索全部 miss）
- `MemoryEntry.__post_init__()` 抛出 `ValueError: provenance.fact_ids is required`
- LanceDB 的 FTS 索引检索质量极差（lossless_restatement 包含 JSON 碎片）
- 迁移脚本运行两遍后 entry 数量翻倍

**Phase to address:**
Phase 6-7（AstrBot 历史迁移）-- 但迁移脚本设计必须在 Phase 2 就开始，因为需要确认 LTM extractor 是否可复用

---

### Pitfall 5: Scheduler Tool 参数校验不足导致模型滥用

**What goes wrong:**
模型可能创建不合理的定时任务：cron 表达式 `"* * * * *"`（每分钟触发）、interval 为 1 秒、one-shot 设为过去时间。虽然 `RuntimeScheduler._validate_schedule()` 会验证格式合法性，但不会校验业务合理性（最小间隔、最大频率、每日上限）。

**Why it happens:**
`_validate_schedule()` 只检查 cron 表达式语法、interval > 0、fire_at > 0。不检查 interval 是否太小、cron 是否太频繁、同一会话是否有太多任务。模型可能被 prompt injection 诱导创建大量高频任务。

**How to avoid:**
1. 在 scheduler tool handler 层（非 scheduler 内核层）增加业务校验：
   - interval 最小值 >= 60 秒
   - 同一 owner 同时存在的任务上限（如 10 个）
   - 同一 conversation_id 的定时消息上限
2. 所有错误通过 tool 返回值告知模型（`ToolResult.llm_content` 包含错误信息），让模型自行修正。
3. 为 `ScheduledTaskInfo.metadata` 增加来源追踪字段（`created_by_tool_call_id`），便于审计和回滚。

**Warning signs:**
- scheduler 日志中出现大量高频触发记录
- 模型创建的任务 `interval_seconds: 1`
- 单个会话有超过 20 个活跃定时任务

**Phase to address:**
Phase 2（模型可用 scheduler tool）

---

### Pitfall 6: MatchSpec 只支持 AND 语义 -- `mention_or_reply` 模式失效

**What goes wrong:**
`MatchSpec.matches()` 的所有条件是 AND 组合的。`mention_or_reply` 过滤模式需要 OR 语义：`mentions_self=True OR reply_targets_self=True`。如果把两个条件都设为 True，则变成了 AND -- 要求同时 @ 和引用才响应。如果只设 `targets_self=True`，则 `targets_self` 的计算中 `mentioned_everyone` 也会让它变成 True，导致 @全体 时也响应。

**Why it happens:**
`session_config.py` 的 `MatchSpec.matches()` 方法逐一检查每个字段，全部通过才返回 True。没有 OR 组合机制。而 `targets_self` 在 `_translate_message()` 中的计算是 `private OR mentioned_everyone OR mentions_self OR reply_targets_self`，它本身就包含了 @全体的语义。

**How to avoid:**
1. 利用 `targets_self` 已经包含 OR 语义的特性：`mention_or_reply` 模式只需在 admission case 中设置 `targets_self=True`。这意味着 @bot、引用bot、@全体 都会触发响应 -- 如果不想响应 @全体，需要在 session config 中用 `mentioned_everyone=False` 排除。
2. 或者不在 MatchSpec 层面做 OR，改为在 admission domain 层面使用多个 case 实现 OR 效果：
   - Case A（priority=200）: `mentions_self=True` -> mode=respond
   - Case B（priority=190）: `reply_targets_self=True` -> mode=respond
   - Default: mode=silent_drop
3. **关键确认步骤：** 检查 `session_loader.py` 中 `message_filter` 的四种值（`all`/`mention_only`/`reply_only`/`mention_or_reply`）分别映射到哪些 MatchSpec 字段，确认映射逻辑与 `targets_self` 的计算语义一致。

**Phase to address:**
Phase 1（群聊 bug 修复）-- 必须在修复过程中理清 `targets_self` 的语义

---

## Moderate Pitfalls

### Pitfall 7: Plugin Scheduler API 缺少生命周期绑定

**What goes wrong:**
插件通过 scheduler API 注册定时任务，但插件卸载（teardown）时忘记清理注册的任务。任务持续触发但 callback 引用了已卸载插件的代码，导致 `AttributeError` 或静默失败。

**Prevention:**
- 插件注册任务时必须使用标准化的 owner 标识：`plugin:<plugin_id>`
- `RuntimePluginContext` 提供 `register_scheduled_task()` 封装方法，自动设置 owner
- Reconciler 在卸载插件时自动调用 `scheduler.unregister_by_owner("plugin:<plugin_id>")`
- 已有 `unregister_by_owner()` 方法可直接使用

**Phase to address:**
Phase 2（插件侧定时任务使用方式）

---

### Pitfall 8: WebUI 可用性优化中的状态保存竞争

**What goes wrong:**
WebUI 的"保存反馈"（如 toast 通知）和"过渡动画"依赖前端状态管理。但如果后端 API 返回的响应时序不确定（HTTP/1.1 持久连接 + ThreadingHTTPServer 可能乱序响应），前端可能显示"保存成功"但实际操作还没执行完。

**Prevention:**
- 前端 toast 只在 API 返回 `{"ok": true}` 后才显示成功
- 使用 `request_id` 追踪每个操作的完整生命周期
- 过渡动画不要依赖 setTimeout，而依赖 API 回调

**Phase to address:**
Phase 3（WebUI 可用性优化）

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| scheduler tool 直接闭包捕获 ctx 发消息 | 快速实现 | callback 触发时 ctx 失效，持久化恢复失败 | Never -- 必须用 dispatcher 中间层 |
| AstrBot 迁移只做字段映射不做 LLM 提取 | 零 API 成本 | LTM 检索质量极差，等于没迁移 | Never -- LTM 的价值在于结构化提取 |
| WebUI scheduler CRUD 直接操作 scheduler 内存 | 实现简单 | 线程安全隐患、请求超时 | 仅限 list/read 操作可走 store；写操作必须走 async dispatch |
| 群聊 bug 修复只改 admission case 配置不改代码 | 快速止血 | 根因不除，同样的问题换个配置又出现 | 仅作为紧急止血，后续必须修代码 |
| 省略 scheduler tool 的 rate limiting | MVP 够用 | 模型可能滥用，消息轰炸 | Never -- 单操作者场景也必须限制 |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Scheduler <-> Gateway | callback 中直接使用注册时的 gateway 状态 | callback 触发时重新获取 gateway 连接状态，处理 WS 断线重连 |
| Scheduler <-> ToolBroker | 在 scheduler tool handler 中同步等待 scheduler.register() | register() 已经是 async，直接 await；但不要在 handler 中注册带 stateful closure 的 callback |
| WebUI HTTP <-> asyncio Scheduler | 在 HTTP handler 线程中直接调用 scheduler 同步方法 | 所有操作通过 `run_coroutine_threadsafe` 提交到 event loop |
| AstrBot DB <-> AcaBot LTM | 直接把 AstrBot content dict 填入 lossless_restatement | 必须经过 LLM 提取或至少 NLP 预处理，生成结构化的 topic/keywords/persons/entities |
| Plugin <-> Scheduler | 插件注册任务时不设 owner，卸载时不清理 | 标准化 owner 为 `plugin:<plugin_id>`，Reconciler 自动清理 |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| LanceDB FTS 索引每次写入后重建 | LTM 写入耗时 >100ms，随 entry 数量增长 | 只在批量操作完成后重建 FTS，不在单条写入时重建 | >500 entries（迁移 AstrBot 历史时必然触发） |
| Semantic search 全表扫描（10k limit） | 搜索延迟 >1s，内存飙升 | AstrBot 迁移前先建 ANN 索引；或至少在向量计算前按 structured fields 预过滤 | >2000 entries |
| Scheduler list_tasks() 遍历内存 dict | WebUI 刷新卡顿（如果任务数多） | WebUI 读 store 而非内存 | >100 个活跃任务时 |
| WebUI JSON 序列化大对象 | API 响应延迟 >500ms | 对 LTM entries 等 API 增加分页，已有 `offset`/`limit` 参数 | 单次返回 >200 entries |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Scheduler tool 允许指定任意 conversation_id 发消息 | 模型被 prompt injection 诱导向非预期会话发消息 | 限制 scheduler tool 只能向创建任务的原始会话发消息 |
| LTM filter injection via `_quote_sql_text()` | 攻击者构造消息内容破坏 SQL-like 过滤器 | 模糊测试转义函数；考虑参数化查询（如果 LanceDB 支持） |
| Scheduler tasks 以完整 plugin 权限运行 | 恶意插件的定时任务获取 computer 访问权限 | 定时任务继承插件的权限范围，不是全局权限 |
| AstrBot 迁移脚本暴露 LLM API key | 如果迁移脚本独立于 AcaBot 运行，API key 管理可能绕过安全配置 | 迁移必须通过 AcaBot runtime 执行，复用其 provider 配置 |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| WebUI scheduler 页面只显示 task_id 和 cron 表达式 | 用户看不懂 `0 9 * * 1-5` 是什么意思 | 显示人类可读的描述："每周一至周五 09:00" |
| 定时消息发送无 UI 反馈 | 用户不知道消息是否已发送 | WebUI 显示最近触发历史（时间、状态、消息预览） |
| 群聊 bug 修复后旧配置不兼容 | 现有 session config 的 message_filter 值不被新逻辑识别 | 保持向后兼容：`reply_only` 继续生效，同时支持新的 `reply_targets_self` 字段 |
| AstrBot 迁移进度不可见 | 用户不知道迁移到哪了、还剩多少 | WebUI 显示迁移进度条和错误计数 |

## "Looks Done But Isn't" Checklist

- [ ] **群聊修复:** 修复后要验证 @bot / 引用bot / @别人 / 普通消息 四种场景的 `targets_self` 和 admission decision -- 不能只测 @bot 能响应就认为修好了
- [ ] **Scheduler Tool:** 持久化任务恢复后 callback 重绑定 -- `callback=None` 的任务在 runtime 重启后是否能正确重新绑定发消息的 callback
- [ ] **Scheduler Tool:** 模型创建的 cron 任务格式合法性 -- 模型可能输出 `"0 9 * * MON-FRI"` 而非 croniter 期望的 `"0 9 * * 1-5"`
- [ ] **WebUI Scheduler 页面:** CRUD 操作后的持久化验证 -- WebUI 创建任务后 runtime 重启，任务是否仍然存在
- [ ] **WebUI Scheduler 页面:** 禁用/启用状态同步 -- WebUI 禁用一个任务后，scheduler 的内存状态和 store 状态是否一致
- [ ] **AstrBot 迁移:** 迁移后 LTM 检索效果验证 -- 不能只验证数据写入成功，要用实际查询验证检索质量
- [ ] **AstrBot 迁移:** 消息去重 -- 同一批历史消息重复迁移不应该产生重复 MemoryEntry
- [ ] **Plugin Scheduler API:** 插件注册的定时任务生命周期绑定 -- 插件卸载时任务是否被正确清理（`unregister_by_owner`）

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Scheduler callback 生命周期失效 | HIGH（需重写 tool 层） | 1. 引入 ScheduledMessageDispatcher 中间层；2. 重写所有 scheduler tool handler 使用 dispatcher；3. 为已持久化的旧任务编写迁移脚本补充 owner 标识 |
| 群聊 targets_self 回归 | MEDIUM | 1. 添加诊断日志确认断裂点；2. 逐层检查 self_id -> mentions_self -> targets_self -> MatchSpec -> admission；3. 添加回归测试 |
| WebUI 线程安全问题 | MEDIUM | 1. Scheduler CRUD 改为 async dispatch 模式；2. list_tasks() 改为读 store 而非内存；3. 操作后发送通知让 scheduler 刷新 |
| AstrBot Schema 不匹配 | HIGH（需 LLM 重新提取） | 1. 删除错误的 LanceDB 数据；2. 重写迁移脚本加入 LLM 提取步骤；3. 重新运行迁移 |
| Scheduler 任务泄漏（插件卸载未清理） | LOW | 调用 `scheduler.unregister_by_owner("plugin:<plugin_id>")` 清理残留任务 |
| LanceDB 并发写入数据丢失 | HIGH | 恢复备份；若无备份则从源 thread 重新提取。预防是唯一策略 |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Scheduler callback 生命周期 | Phase 2 (Scheduler Tool) | 持久化任务创建后重启 runtime，验证消息仍然按时发出 |
| 群聊 targets_self 回归 | Phase 1 (群聊 Bug 修复) | 四种消息类型 x 四种过滤模式 = 16 个端到端测试 |
| WebUI 线程安全 | Phase 3 (WebUI Scheduler 页面) | 并发创建/取消任务压力测试 |
| AstrBot Schema 转换 | Phase 6-7 (历史迁移) | 迁移后对 10 个随机话题做检索质量评估 |
| Scheduler Tool 参数校验 | Phase 2 (Scheduler Tool) | 用 adversarial prompt 测试模型是否能创建非法任务 |
| Plugin 定时任务生命周期 | Phase 2 (Plugin Scheduler) | 插件注册任务后卸载插件，验证任务被清理 |
| MatchSpec OR 语义 | Phase 1 (群聊 Bug 修复) | 验证 `mention_or_reply` 模式在 @或引用 单独命中时都能响应 |
| LanceDB 并发写入 | Phase 6 (迁移前) | 已有 `_write_lock`，确认迁移脚本也通过 lock 保护 |

## Sources

- AcaBot 源码直接分析:
  - `src/acabot/runtime/scheduler/scheduler.py` -- callback 类型定义、validate 逻辑、persist 恢复
  - `src/acabot/runtime/tool_broker/broker.py` -- ToolExecutionContext 结构、handler 注册
  - `src/acabot/gateway/napcat.py` -- `_translate_message()` 中的 targets_self 推导
  - `src/acabot/gateway/onebot_message.py` -- `extract_onebot_message_features()` 的 @/reply 提取
  - `src/acabot/runtime/contracts/session_config.py` -- MatchSpec.matches() 的 AND 语义、EventFacts 字段
  - `src/acabot/runtime/control/session_runtime.py` -- `_surface_candidates()` 优先级逻辑、`build_facts()`
  - `src/acabot/runtime/control/session_loader.py` -- message_filter 到 MatchSpec 的映射
  - `src/acabot/runtime/memory/long_term_memory/contracts.py` -- MemoryEntry 非空约束
  - `src/acabot/runtime/memory/long_term_memory/storage.py` -- LanceDB 整表重写、FTS 索引重建
  - `src/acabot/runtime/control/http_api.py` -- ThreadingHTTPServer + `_await()` 桥接模式
  - `src/acabot/runtime/notification_send_context.py` -- 定时消息可复用的 RunContext 构造逻辑
- AstrBot 源码分析:
  - `ref/AstrBot/astrbot/core/platform_message_history_mgr.py` -- 消息历史存储接口
  - `ref/AstrBot/astrbot/core/provider/entities.py` -- ProviderRequest 结构（contexts 列表）
  - `ref/AstrBot/astrbot/core/platform/astrbot_message.py` -- 消息链结构
- 项目上下文: `.planning/PROJECT.md`
- v2 基础设施研究遗留: LanceDB 并发写入保护（已有 `_write_lock`）、FTS 重建性能陷阱仍然相关

---
*Pitfalls research for: AcaBot v1.1 milestone*
*Researched: 2026-04-05*
