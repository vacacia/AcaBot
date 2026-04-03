# Phase 3c: Logging & Observability - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Enrich logging with structured fields at key emit sites, integrate structlog as a wrapper over stdlib logging for async-safe context propagation, record LLM token usage with persistence, and render structured logs in WebUI. This phase makes the runtime observable — what tools ran, how many tokens were spent, which run produced an error.

</domain>

<decisions>
## Implementation Decisions

### structlog 集成
- **D-01:** Wrapper 模式 — structlog 包装 stdlib logging, 使用 contextvars 传播 run_id/thread_id/agent_id. 现有 `logger.info()` 调用不变, 新代码使用 `structlog.get_logger()`. 渐进迁移, 不一次性替换所有调用
- **D-02:** 添加 `structlog` 到 pyproject.toml 依赖

### Token 用量记录
- **D-03:** Per-run 日志 + 持久化 — 每次 agent run 完成后 emit 结构化日志 (input/output/total tokens, model, cost), 同时写入 SQLite (或扩展现有 RunRecord) 支持历史查询
- **D-04:** Token 数据来源: 从 LLM response 的 usage dict 提取 (现有 ModelAgentRuntime 已有提取逻辑)

### 结构化日志字段
- **D-05:** 工具调用日志增加 tool_name, duration_ms, result_summary 字段 (LOG-01)
- **D-06:** 错误日志自动关联 run context — 通过 structlog contextvars 绑定 run_id/thread_id/agent_id (LOG-03)
- **D-07:** LTM extraction/query 过程日志增加 timing 和 record_count 字段 (LOG-05)

### WebUI 日志查看器
- **D-08:** 增强现有 LogsView.vue — 结构化字段渲染为 key-value 标签/芯片, 支持按 run_id/tool_name 筛选. 不重写页面, 在现有基础上增强

### Claude's Discretion
- structlog processor chain 配置 (开发 vs 生产)
- InMemoryLogBuffer 如何存储结构化字段 (LogRecord.extra dict)
- Token 持久化的具体存储位置 (扩展 runs 表 or 独立 token_usage 表)
- WebUI 筛选器的具体交互设计

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 现有日志基础设施
- `src/acabot/runtime/control/log_buffer.py` — InMemoryLogBuffer + InMemoryLogHandler, 2000 条 ring buffer
- `src/acabot/runtime/control/log_setup.py` 或日志初始化代码 — ColorLogFormatter, 日志格式配置

### 工具调用日志
- `src/acabot/runtime/tool_broker/broker.py` — ToolBroker, 工具执行入口. 需要在此处 emit 结构化日志
- `src/acabot/runtime/tool_broker/contracts.py` — ToolExecutionContext, 包含 tool_name 等信息

### Token 用量
- `src/acabot/runtime/model/model_agent_runtime.py` — ModelAgentRuntime, LLM 响应后提取 token usage
- `src/acabot/agent/agent.py` — LitellmAgent, litellm acompletion 调用和响应处理

### LTM 日志
- `src/acabot/runtime/memory/long_term_memory/` — LTM extraction/query 流程
- `src/acabot/runtime/memory/long_term_ingestor.py` — Ingestor 处理流程

### WebUI
- `webui/src/views/LogsView.vue` — 现有日志查看器页面
- `webui/src/api.ts` — API client, 日志相关接口

### Run 存储
- `src/acabot/runtime/storage/stores.py` — RunStore, 可扩展存储 token usage
- `src/acabot/runtime/contracts/records.py` — RunRecord dataclass

### Phase 2 context
- `src/acabot/runtime/plugins/plugin_protocol.py` — plugin_id 可作为 structlog context field

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `InMemoryLogBuffer` — Ring buffer, 已有 handler 注入 stdlib logging. structlog 可以通过 stdlib 桥接自动进入 buffer
- `LogsView.vue` — 现有日志页面, filters + pagination + 800ms polling
- `RunRecord` — 可扩展, 添加 token_usage 字段
- `ToolRuntimeState.tool_audit` — 已有审计基础设施

### Established Patterns
- `logging.getLogger("acabot.<subsystem>")` per module
- `ContextVar` 已在 `src/acabot/context.py` 使用 (current_event)
- Log format: `%(asctime)s [%(name)s] %(levelname)s: %(message)s`

### Integration Points
- `log_buffer.py` — InMemoryLogHandler 需要理解结构化字段 (LogRecord.extra)
- `model_agent_runtime.py` — Token usage emit point
- `tool_broker/broker.py` — Tool call duration + result emit point
- `http_api.py` — 日志 API 端点可能需要扩展 (返回结构化字段)
- `LogsView.vue` — 渲染结构化字段

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

- LOG-V2-01: 完整 run trace 视图 (WebUI) — v2 需求
- LOG-V2-02: Memory 操作追踪 — v2 需求
- LOG-V2-03: Token budget 可视化 — v2 需求
- LOG-V2-04: OpenTelemetry 导出 — v2 需求

</deferred>

---

*Phase: 3c-logging-observability*
*Context gathered: 2026-04-03*
