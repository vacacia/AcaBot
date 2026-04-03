# Phase 3c: Logging & Observability - Research

**Researched:** 2026-04-03
**Status:** Complete

---

## 1. 现有日志基础设施

### 1.1 日志初始化 (`src/acabot/main.py`)

```python
# setup_logging() 流程:
# 1. 读取 config.logging.level (默认 INFO)
# 2. 创建 StreamHandler + ColorLogFormatter
# 3. 创建 InMemoryLogHandler(LOG_BUFFER) 镜像到内存 ring buffer
# 4. basicConfig(level=WARNING, handlers=[handler, memory_handler], force=True)
# 5. getLogger("acabot").setLevel(level)  -- 只有 acabot.* 日志受配置控制
# 6. websockets.server 加噪音过滤器
```

**日志格式:** `%(asctime)s [%(name)s] %(levelname)s: %(message)s`
- 纯文本格式, 无结构化字段
- `ColorLogFormatter` 只做 ANSI 着色, 不改变内容

**命名约定:** 各模块使用 `logging.getLogger("acabot.<subsystem>")`, 例如:
- `acabot.agent` (LitellmAgent)
- `acabot.runtime.pipeline` (ThreadPipeline)
- `acabot.runtime.tool_broker` (ToolBroker)
- `acabot.runtime.memory.long_term_ingestor` (LongTermMemoryIngestor)

### 1.2 InMemoryLogBuffer (`src/acabot/runtime/control/log_buffer.py`)

**核心结构:**
```python
@dataclass(slots=True)
class LogEntry:
    timestamp: float
    level: str
    logger: str
    message: str
    kind: str = "runtime"  # 用于区分 napcat_message/napcat_notice/runtime
    seq: int = 0
```

**关键发现:**
- `LogEntry` **没有** `extra` / `fields` / `metadata` 字典字段 -- 结构化字段无处存储
- `InMemoryLogHandler.emit()` 只提取 `record.getMessage()`, `record.levelname`, `record.name`, 和自定义 `record.log_kind`
- **不提取** `record.__dict__` 中的 extra fields
- Ring buffer 容量 2000 条, 线程安全 (`threading.Lock`)
- `list_entries()` 支持 `after_seq`, `level`, `keyword` 过滤, 但 keyword 只搜 message + logger

**改动需求 (LOG-04):** 必须扩展 `LogEntry` 增加 `extra: dict[str, Any]` 字段, 并让 `InMemoryLogHandler.emit()` 从 `LogRecord` 提取结构化字段.

### 1.3 HTTP API 日志端点

- 端点: `GET /api/system/logs?after_seq=&level=&keyword=&limit=`
- 调用 `control_plane.list_recent_logs()` -> `log_buffer.list_entries()`
- 返回 `LogEntry` 的 `asdict()` -- 新增 `extra` 字段会自动透传到 JSON

### 1.4 ContextVar 现状 (`src/acabot/context.py`)

```python
current_event: ContextVar[StandardEvent | None] = ContextVar("current_event", default=None)
```

- 只有一个 ContextVar: `current_event`
- **没有** `run_id`, `thread_id`, `agent_id` 的 ContextVar
- structlog 的 contextvars 绑定需要新增这些变量, 或者使用 structlog 自带的 `structlog.contextvars`

---

## 2. LOG-01: 工具调用结构化日志

### 2.1 工具执行入口 (`src/acabot/runtime/tool_broker/broker.py`)

**核心执行方法:** `ToolBroker.execute()` (L528-L610)

```python
async def execute(self, *, tool_name, arguments, ctx) -> ToolResult:
    audit_record = await self._audit_start(...)
    # ... policy check ...
    try:
        raw = registered.handler(arguments, ctx)
        if isawaitable(raw): raw = await raw
    except Exception as exc:
        return await self._fail(...)
    normalized = self._normalize_result(raw)
    audit_record = await self.audit.complete(audit_record, result=normalized)
    return normalized
```

**当前日志:** **没有任何日志!** `execute()` 方法不记录工具调用的开始/结束/耗时. 只有 `register_tool` 时有 warning 日志.

**Agent 侧工具日志** (`src/acabot/agent/agent.py` L348-L365):
```python
logger.debug("Tool execution requested by LLM: name=%s args=%s", ...)
# ... executor call ...
logger.debug("Tool execution finished: name=%s attachments=%s content_preview=%s", ...)
```
- 在 `LitellmAgent._handle_tool_calls()` 中
- 只是 DEBUG 级别, 无 duration, 无结构化字段

**ToolAuditRecord** (`src/acabot/runtime/tool_broker/contracts.py`):
```python
@dataclass(slots=True)
class ToolAuditRecord:
    tool_call_id: str
    run_id: str
    tool_name: str
    status: Literal["started", "waiting_approval", "completed", "rejected", "failed"]
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```
- 已有审计基础设施, 但 **没有 duration_ms 字段**

**推荐方案:**
- 在 `ToolBroker.execute()` 的 handler 执行前后添加 `time.monotonic()` 计时
- emit 结构化日志: `logger.info("Tool executed", extra={"tool_name": ..., "duration_ms": ..., "result_summary": ..., "run_id": ctx.run_id})`
- 可选: 在 `ToolAuditRecord.metadata` 中也存储 `duration_ms`

### 2.2 执行上下文

`ToolExecutionContext` 已包含:
- `run_id`, `thread_id`, `actor_id`, `agent_id` -- 完备的 run context

---

## 3. LOG-02: LLM Token 用量

### 3.1 Token 数据来源 (`src/acabot/agent/agent.py`)

**LitellmAgent.run()** (L95-L167):
```python
total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
# ... loop ...
usage = response.usage
for key in total_usage:
    total_usage[key] += getattr(usage, key, 0)
# 完成时:
logger.info(
    "LLM run completed: model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s ...",
    use_model, total_usage.get("prompt_tokens", 0), ...
)
return AgentResponse(usage=total_usage, ...)
```

**已有日志:** LLM 完成时有 INFO 日志, 包含 token 数 -- 但只是纯文本 key=value 格式.

**LitellmAgent.complete()** (L172-L233):
```python
logger.debug(
    "LLM complete finished: model=%s prompt_tokens=%s ...",
    use_model, getattr(usage, "prompt_tokens", 0), ...
)
return AgentResponse(usage={...}, ...)
```
- complete 路径只有 DEBUG 级别

### 3.2 Token 传递链

```
LitellmAgent.run() -> AgentResponse(usage=total_usage)
  -> ModelAgentRuntime._to_runtime_result() -> AgentRuntimeResult(usage=dict(...))
    -> ctx.response.usage  (在 ThreadPipeline 中可访问)
```

`AgentRuntimeResult` 已有 `usage: dict[str, int]` 字段 (L74).

### 3.3 持久化现状

`RunRecord` (`src/acabot/runtime/contracts/records.py`):
```python
@dataclass(slots=True)
class RunRecord:
    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    trigger_event_id: str
    status: RunStatus
    started_at: int
    finished_at: int | None = None
    error: str | None = None
    approval_context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
```

- **没有专门的 token/cost 字段**
- `metadata` 字典可以存储, 但需要确认 SQLite 存储层是否正确序列化

**推荐方案:**
- 在 `ThreadPipeline._finish_run()` 或 `ModelAgentRuntime._to_runtime_result()` 阶段 emit 结构化日志: `logger.info("Run token usage", extra={"run_id": ..., "model": ..., "prompt_tokens": ..., "completion_tokens": ..., "total_tokens": ..., "cost": ...})`
- Token 数据写入 `RunRecord.metadata["token_usage"]` -- 利用现有 metadata 字段, 不需要改 DDL
- Cost 计算: litellm 有 `response._hidden_params.get("response_cost")` 可以提取, 或用 `litellm.completion_cost()`

---

## 4. LOG-03: 错误日志自动关联 run context

### 4.1 当前 run context 传播

`RunContext` (`src/acabot/runtime/contracts/context.py` L209-L245):
- 包含 `run: RunRecord`, `thread: ThreadState`, `agent: ResolvedAgent`
- 在 `ThreadPipeline.execute()` 内可用

**问题:** 当 pipeline 内部组件 (如 memory broker, computer runtime, tool handler) 记录错误时, 日志中 **没有 run_id/thread_id/agent_id** -- 只有手动传入的 key=value 字符串.

### 4.2 Pipeline 中的上下文设置点

`ThreadPipeline.execute()` (`src/acabot/runtime/pipeline.py` L101-L263):
```python
async def execute(self, ctx: RunContext, ...) -> None:
    await self.run_manager.mark_running(ctx.run.run_id)
    # ... 这里应该绑定 structlog context ...
```

**ContextVar 使用:** 只有 `current_event` 在 pipeline 入口被 set:
```python
# src/acabot/context.py
current_event: ContextVar[StandardEvent | None] = ContextVar("current_event", default=None)
```

### 4.3 推荐方案

使用 `structlog.contextvars`:
```python
# 在 ThreadPipeline.execute() 入口:
structlog.contextvars.clear_contextvars()
structlog.contextvars.bind_contextvars(
    run_id=ctx.run.run_id,
    thread_id=ctx.thread.thread_id,
    agent_id=ctx.agent.agent_id,
)
```

这样所有在该 async 任务链中的日志自动带上 run context -- 无需修改下游代码.

---

## 5. LOG-04: WebUI 日志查看器结构化字段

### 5.1 前端现状

**LogStreamPanel.vue** (`webui/src/components/LogStreamPanel.vue`):

```typescript
type LogItem = {
  seq: number
  timestamp: number
  level: string
  logger: string
  message: string
  kind?: string
}
```

- **没有** `extra` / `fields` 字段
- 渲染: `<pre class="log-message">{{ item.message }}</pre>` -- 纯文本

**LogsView.vue** (`webui/src/views/LogsView.vue`):
- 薄包装, 只传参数给 `LogStreamPanel`
- 支持紧凑/面板模式切换, 显示条数选择

### 5.2 改动需求

1. **后端:** `LogEntry` 增加 `extra: dict[str, Any]` 字段; `InMemoryLogHandler.emit()` 提取 `record.__dict__` 中的自定义字段
2. **API:** `asdict(LogEntry)` 自动包含 `extra`, 无需改 HTTP API
3. **前端:**
   - `LogItem` type 增加 `extra?: Record<string, unknown>`
   - 渲染: 在 `<pre>` 下方展示 extra 字段为 key-value chips/tags
   - 筛选: 可选按 `run_id`, `tool_name` 等 extra 字段过滤

### 5.3 关键设计选择

**哪些 LogRecord 属性算 "extra"?**
- 排除 stdlib 标准属性 (`name`, `msg`, `args`, `levelname`, `pathname`, `lineno`, `funcName`, `created`, `thread`, `threadName`, `process`, `processName`, `exc_info`, `exc_text`, `stack_info`, `taskName`)
- 排除自定义已处理的 (`log_kind`)
- 剩余的都算 extra structured fields

---

## 6. LOG-05: LTM 提取/查询过程日志

### 6.1 LTM 查询侧 (`src/acabot/runtime/memory/long_term_memory/source.py`)

`LtmMemorySource.__call__()` (L151-L205):
- **没有任何日志!** 完整的三路检索 (query planner -> semantic/lexical/symbolic -> merge) 全程静默
- 无法观测:
  - query planner 返回了什么查询计划
  - 各路检索命中了多少条
  - 最终 ranked 结果数量
  - 总耗时

**推荐注入点:**
```python
# 1. query planner 完成后
logger.info("LTM query plan", extra={"conversation_id": ..., "semantic_count": len(...), "lexical_count": len(...), "has_symbolic": bool(...)})
# 2. 三路检索完成后
logger.info("LTM retrieval", extra={"semantic_hits": len(...), "lexical_hits": len(...), "symbolic_hits": len(...), "ranked_total": len(ranked_hits), "duration_ms": ...})
```

### 6.2 LTM 查询模型客户端 (`model_clients.py`)

`LtmQueryPlannerClient.plan_query()` (L285-L343):
- **没有日志.** 调 LLM 生成查询计划, 完全静默
- 应该记录 model used, token usage, duration

`LtmEmbeddingClient.embed_texts()` (L215-L228):
- **没有日志.** 向量化请求静默

### 6.3 LTM 写入侧

**LongTermMemoryIngestor** (`src/acabot/runtime/memory/long_term_ingestor.py`):
- 有基本日志: exception 和 warning
- **缺少:** 每次 ingest 的 fact 数量, 窗口数量, 提取到的 entry 数量, 总耗时

**LtmWritePort** (`src/acabot/runtime/memory/long_term_memory/write_port.py`):
- L107-L172: `ingest_thread_delta()` 逐窗口执行 提取 → embedding → 存储
- **没有日志!** 每窗口成功/失败完全依赖上层 ingestor 的 exception 处理

**LtmExtractorClient** (`model_clients.py`):
- L92-L142: `extract_window()` 调 LLM 提取 MemoryEntry
- **没有日志.** 调模型完全静默

**推荐注入点:**
```python
# LtmWritePort.ingest_thread_delta 每窗口完成后:
logger.info("LTM window ingested", extra={"thread_id": ..., "window_facts": len(window.facts), "entries_extracted": len(entries), "duration_ms": ...})

# LtmExtractorClient.extract_window 完成后:
logger.info("LTM extraction", extra={"conversation_id": ..., "fact_count": len(facts), "entries_extracted": len(entries), "model": request.model, "duration_ms": ...})
```

---

## 7. LOG-06: structlog 集成

### 7.1 当前依赖

`pyproject.toml` 中 **没有 structlog**. 需要新增.

### 7.2 集成模式: Wrapper over stdlib

根据 D-01 决策, 采用 "structlog 包装 stdlib logging" 模式:

```python
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,      # 合并 contextvars 绑定的字段
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
```

**关键点:**
- 现有 `logging.getLogger("acabot.*")` 代码 **无需修改**
- 新代码可以用 `structlog.get_logger("acabot.xxx")` 获取带结构化字段的 logger
- structlog 的 `merge_contextvars` processor 会自动把 `bind_contextvars()` 绑定的 run_id/thread_id 注入到每条日志
- `ProcessorFormatter` 替代 `ColorLogFormatter`, 输出 key=value 或 JSON 格式

### 7.3 与 InMemoryLogHandler 的兼容性

structlog stdlib 模式下, 最终还是通过 stdlib `LogRecord` emit:
- structlog processors 把结构化字段写进 `LogRecord.__dict__`
- `InMemoryLogHandler.emit()` 需要修改: 从 `LogRecord` 提取 extra fields

**两种提取策略:**
1. **白名单:** structlog 用 `ProcessorFormatter` 把 structured fields 写进 `record.structlog_extra` 自定义属性
2. **黑名单:** 遍历 `record.__dict__`, 排除 stdlib 已知属性, 剩余的都是 extra

推荐策略 1 -- 更可控, 避免意外泄露内部属性.

### 7.4 对 ColorLogFormatter 的影响

当前 `ColorLogFormatter` 继承 `logging.Formatter`, 只做 ANSI 着色.

structlog 集成后:
- **开发环境:** 使用 structlog 的 `ConsoleRenderer` (带颜色 + key=value 后缀), 替代 ColorLogFormatter
- **生产环境:** 使用 `JSONRenderer` 输出纯 JSON (可选, 后续优化)
- `ColorLogFormatter` 保留但降级为 fallback

---

## 8. 集成点汇总

| 改动点 | 文件 | 影响范围 | 风险 |
|--------|------|----------|------|
| 添加 structlog 依赖 | `pyproject.toml` | 构建 | 低 - 纯新增 |
| structlog 配置初始化 | `src/acabot/main.py` | 启动 | 中 - 替换日志格式 |
| 扩展 LogEntry + InMemoryLogHandler | `src/acabot/runtime/control/log_buffer.py` | WebUI 日志 | 低 - 向后兼容 |
| 工具调用计时日志 | `src/acabot/runtime/tool_broker/broker.py` | 工具执行 | 低 - 只增加日志 |
| LLM token 用量结构化日志 | `src/acabot/agent/agent.py` | Agent 调用 | 低 - 增强现有日志 |
| Token 写入 RunRecord.metadata | `src/acabot/runtime/pipeline.py` | Run 收尾 | 低 - metadata 已有 |
| Pipeline 入口绑定 run context | `src/acabot/runtime/pipeline.py` | Run 生命周期 | 低 - 只增加绑定 |
| LTM 查询侧日志 | `src/acabot/runtime/memory/long_term_memory/source.py` | LTM 检索 | 低 - 纯新增 |
| LTM 写入侧日志 | `src/acabot/runtime/memory/long_term_memory/write_port.py` | LTM 写入 | 低 - 纯新增 |
| LTM model client 日志 | `src/acabot/runtime/memory/long_term_memory/model_clients.py` | LTM 模型调用 | 低 - 纯新增 |
| WebUI LogItem 扩展 | `webui/src/components/LogStreamPanel.vue` | 前端 | 中 - UI 变更 |

---

## 9. 风险与注意事项

### 9.1 性能

- structlog 增加每条日志 ~1-5us 的 processor 开销 -- 对 IO-bound bot 可忽略
- InMemoryLogBuffer 增加 extra dict 存储 -- 2000 条 * ~200 bytes/extra ≈ 400KB, 可接受
- 工具调用计时用 `time.monotonic()`, 无系统调用开销

### 9.2 向后兼容

- 现有 `logger.info("key=%s value=%s", ...)` 调用 **不需要修改** -- structlog wrapper 模式完全兼容
- WebUI API 返回的 `LogEntry` 增加 `extra` 字段 -- 前端需要处理, 但旧前端忽略新字段不会报错
- `LogEntry.extra` 默认为空 dict -- 没有 extra 的日志保持原样

### 9.3 structlog contextvars 与 asyncio

- `structlog.contextvars` 基于 Python `contextvars` -- asyncio 原生支持, 每个 Task 独立 context
- `asyncio.create_task()` 会拷贝 context 快照 -- 子任务自动继承 run_id
- 需要在 pipeline 入口 `clear_contextvars()` 防止上一个 run 的字段泄露

### 9.4 与现有 log_kind 机制的共存

NapCat gateway 使用 `record.log_kind` 标记消息类型 (`napcat_message`, `napcat_notice`).
这个机制通过 `setattr(record, "log_kind", ...)` 实现.

structlog wrapper 模式下:
- 新代码用 `structlog.get_logger().info("msg", log_kind="napcat_message")` -- kind 自然成为 extra field
- 旧代码继续用 `setattr` -- InMemoryLogHandler 需要同时处理两种来源

---

## 10. 推荐实现顺序

1. **Step 1 - 基础设施:** 添加 structlog 依赖, 配置初始化, 扩展 LogEntry/InMemoryLogHandler
2. **Step 2 - Run context 绑定:** Pipeline 入口 bind_contextvars, 错误日志自动带 run_id (LOG-03)
3. **Step 3 - 工具调用日志:** ToolBroker.execute() 增加计时和结构化日志 (LOG-01)
4. **Step 4 - Token 用量:** Agent/Pipeline 层增强 token 日志和持久化 (LOG-02)
5. **Step 5 - LTM 日志:** 查询侧和写入侧增加可观测性日志 (LOG-05)
6. **Step 6 - WebUI:** 前端 LogStreamPanel 渲染 extra 字段 (LOG-04)

---

*Phase: 3c-logging-observability*
*Research completed: 2026-04-03*
