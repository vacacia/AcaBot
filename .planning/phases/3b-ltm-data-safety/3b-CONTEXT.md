# Phase 3b: LTM Data Safety - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Protect LanceDB data integrity with write serialization, backup capability, startup validation, and graceful degradation. This phase hardens existing LTM infrastructure — no new memory features, no schema changes.

</domain>

<decisions>
## Implementation Decisions

### 写入序列化
- **D-01:** 在 LTM write_port 层添加 `asyncio.Lock`, 序列化所有 LanceDB 写入操作 (upsert_entries, save_cursor 等). 当前 `asyncio.to_thread()` 无锁, 存在并发写入风险

### 备份机制
- **D-02:** 目录副本方式备份 — 直接复制整个 `runtime_data/long_term_memory/lancedb/` 目录到备份位置. 备份期间获取写锁, 确保一致性
- **D-03:** 备份通过 Phase 3a Scheduler 触发 (定期 cron 任务). LTM-01/03/04 可以先于 Scheduler 完成, LTM-02 备份依赖 Scheduler

### 启动校验
- **D-04:** 启动时检查 LanceDB 表完整性 (能否打开, 能否读取). 发现损坏时禁用 LTM + 记录 warning 日志, pipeline 继续运行但无长期记忆

### 降级与通知
- **D-05:** LTM 降级时通过日志警告 + runtime 状态标志双重通知. 状态标志可被 WebUI 读取展示系统健康状态
- **D-06:** Mid-pipeline LTM 失败 (写入/查询报错) 不阻断 agent 响应, 记录 error 继续. 当前 ingestor 已有 FailedWindowRecord 机制, 保持一致

### Claude's Discretion
- 备份目录路径命名规则 (时间戳 / 序号)
- 备份保留策略 (保留最近 N 份)
- 启动校验的具体检查项 (表是否可读, schema 是否匹配)
- 状态标志的具体数据结构和暴露方式

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### LTM 核心代码
- `src/acabot/runtime/memory/long_term_memory/storage.py` — LanceDB 连接和表操作
- `src/acabot/runtime/memory/long_term_memory/write_port.py` — LTM 写入端口, 当前无锁的 asyncio.to_thread() 调用 (需加锁)
- `src/acabot/runtime/memory/long_term_memory/contracts.py` — LTM 数据契约

### LTM 写入流程
- `src/acabot/runtime/memory/long_term_ingestor.py` — Background ingestor, LTM 写入的入口
- `src/acabot/runtime/memory/conversation_facts.py` — ConversationFactReader, 上游数据源

### Bootstrap
- `src/acabot/runtime/bootstrap/__init__.py` — LTM 组件构造, 启动校验应在此处
- `src/acabot/runtime/bootstrap/builders.py` — build_long_term_memory() 函数, LanceDB 路径配置

### 存储路径
- `runtime_data/long_term_memory/lancedb` — LanceDB 数据目录 (备份源)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `FailedWindowRecord` — 现有 LTM 失败记录机制, 写入失败已有重试语义
- `asyncio.Lock` 模式 — sqlite_stores.py 中已广泛使用
- `InMemoryLogBuffer` — 状态标志可参考现有 log buffer 的内存存储模式

### Established Patterns
- `asyncio.to_thread()` 包装阻塞 IO — LanceDB 操作当前模式
- Config path resolution via `config.resolve_path()`
- Graceful degradation: 功能降级但 pipeline 不中断

### Integration Points
- `write_port.py` — 加锁点, 所有写操作经过此处
- `bootstrap/__init__.py` — 启动校验 + 降级标志设置
- `app.py` 或 control plane — 暴露 LTM 健康状态
- Phase 3a Scheduler — 定期备份任务注册

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 3b-ltm-data-safety*
*Context gathered: 2026-04-03*
