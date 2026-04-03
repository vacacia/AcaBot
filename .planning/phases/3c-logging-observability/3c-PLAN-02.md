# 3c-PLAN-02: Wave 2 — 结构化日志 Emit Sites

**Phase:** 3c-logging-observability
**Wave:** 2 of 3
**Covers:** LOG-01 (工具调用日志) + LOG-02 (LLM token 用量) + LOG-05 (LTM 日志)
**Depends on:** Wave 1 (structlog 基础设施 + run context 传播)

---

## 目标

在三个关键 emit site 添加结构化日志: 工具调用 (tool_name, duration_ms, result_summary), LLM token 用量 (input/output/total, model, cost), LTM extraction/query (timing, record_count). 所有日志通过 Wave 1 建立的 structlog 基础设施输出, 自动携带 run context.

---

## Task 1: 工具调用结构化日志 (LOG-01)

**文件:** `src/acabot/runtime/tool_broker/broker.py`

**改动:** 在 `ToolBroker.execute()` 方法中添加计时和结构化日志

**具体改动点:**

```python
import time
import structlog

slog = structlog.get_logger("acabot.runtime.tool_broker")

async def execute(self, *, tool_name, arguments, ctx) -> ToolResult:
    audit_record = await self._audit_start(...)
    registered = self._tools.get(tool_name)
    # ... policy check 逻辑不变 ...

    # 新增: 计时开始
    t0 = time.monotonic()
    try:
        raw = registered.handler(arguments, ctx)
        if isawaitable(raw): raw = await raw
    except Exception as exc:
        # 新增: 失败日志
        duration_ms = round((time.monotonic() - t0) * 1000, 1)
        slog.warning(
            "Tool execution failed",
            tool_name=tool_name,
            duration_ms=duration_ms,
            error=str(exc),
            run_id=ctx.run_id,
        )
        return await self._fail(...)

    # 新增: 成功日志
    duration_ms = round((time.monotonic() - t0) * 1000, 1)
    normalized = self._normalize_result(raw)

    # 生成 result_summary: 取 llm_content 前 120 字符
    result_summary = str(normalized.llm_content or "")[:120]

    slog.info(
        "Tool executed",
        tool_name=tool_name,
        duration_ms=duration_ms,
        result_summary=result_summary,
        source=registered.source,
        has_attachments=bool(normalized.attachments),
    )
    # ... 后续逻辑不变 ...
```

**同时修改 `_reject()` 方法:** 添加拒绝日志
```python
async def _reject(self, *, message, audit_record, ctx, tool_name, arguments, **kw) -> ToolResult:
    slog.warning(
        "Tool rejected",
        tool_name=tool_name,
        reason=message,
        run_id=ctx.run_id,
    )
    # ... 现有逻辑 ...
```

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
import logging, time
logging.basicConfig(level=logging.DEBUG, force=True)
logging.getLogger('acabot').setLevel(logging.DEBUG)
from acabot.runtime.control.log_setup import configure_structlog
configure_structlog()
# 验证 structlog logger 可以正常工作
import structlog
log = structlog.get_logger('acabot.runtime.tool_broker')
log.info('Tool executed', tool_name='bash', duration_ms=42.5, result_summary='exit code 0')
print('Tool structured log: OK')
"
```

---

## Task 2: LLM Token 用量结构化日志 (LOG-02)

### Task 2a: Agent 层增强 token 日志

**文件:** `src/acabot/agent/agent.py`

**改动:** 把 `LitellmAgent.run()` 和 `LitellmAgent.complete()` 中已有的 token 纯文本日志改为结构化日志

**具体改动 — `run()` 方法 (约 L146):**

```python
import structlog

slog = structlog.get_logger("acabot.agent")

# 替换现有的 logger.info("LLM run completed: model=%s ...") 为:
slog.info(
    "LLM run completed",
    model=use_model,
    prompt_tokens=total_usage.get("prompt_tokens", 0),
    completion_tokens=total_usage.get("completion_tokens", 0),
    total_tokens=total_usage.get("total_tokens", 0),
    tool_rounds=len(tool_calls_made),
    attachments=len(all_attachments),
)
```

**具体改动 — `complete()` 方法:**

```python
# 替换现有 logger.debug("LLM complete finished: ...") 为:
slog.info(
    "LLM complete finished",
    model=use_model,
    prompt_tokens=getattr(usage, "prompt_tokens", 0),
    completion_tokens=getattr(usage, "completion_tokens", 0),
    total_tokens=getattr(usage, "total_tokens", 0),
)
```

**注意:** 提升 complete 路径日志从 DEBUG 到 INFO, 确保 token 用量始终可见.

### Task 2b: Token 用量写入 RunRecord.metadata

**文件:** `src/acabot/runtime/pipeline.py`

**改动:** 在 `_finish_run()` 中, 将 `ctx.response.usage` 写入 `RunRecord.metadata["token_usage"]`

**具体改动:**

```python
import structlog

slog = structlog.get_logger("acabot.runtime.pipeline")

async def _finish_run(self, ctx: RunContext) -> None:
    response = ctx.response
    if response is None:
        await self.run_manager.mark_failed(ctx.run.run_id, "missing runtime response")
        return

    # 新增: 记录 token 用量到 run metadata
    if response.usage:
        ctx.run.metadata["token_usage"] = dict(response.usage)
        # 记录 model 信息 (从 response.metadata 或 ctx.metadata 获取)
        model_name = str(response.metadata.get("model", "") or ctx.metadata.get("model_used", ""))
        if model_name:
            ctx.run.metadata.setdefault("model", model_name)
        # 结构化日志
        slog.info(
            "Run token usage",
            prompt_tokens=response.usage.get("prompt_tokens", 0),
            completion_tokens=response.usage.get("completion_tokens", 0),
            total_tokens=response.usage.get("total_tokens", 0),
            model=model_name,
        )

    # ... 现有的 status 判断逻辑不变 ...
```

**持久化说明:** `RunRecord.metadata` 是 `dict[str, Any]`, SQLite 存储层通过 JSON 序列化. 无需改 DDL, 无需改 RunRecord dataclass.

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.contracts.records import RunRecord
r = RunRecord(
    run_id='r1', thread_id='t1', actor_id='a1', agent_id='main',
    trigger_event_id='e1', status='completed', started_at=0,
)
r.metadata['token_usage'] = {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}
print('token_usage in metadata:', r.metadata['token_usage'])
print('OK')
"
```

---

## Task 3: LTM 查询侧日志 (LOG-05 — 检索)

**文件:** `src/acabot/runtime/memory/long_term_memory/source.py`

**改动:** 在 `LtmMemorySource.__call__()` 中添加结构化日志, 覆盖 query plan + 三路检索 + ranking 结果

**具体注入点:**

```python
import time
import structlog

slog = structlog.get_logger("acabot.runtime.memory.ltm.source")

# 在 LtmMemorySource.__call__() 中:

async def __call__(self, request: SharedMemoryRetrievalRequest, spec: MemoryAssemblySpec) -> MemoryBlock | None:
    t0 = time.monotonic()

    # 1. query planner 完成后:
    # plan = await self.query_planner.plan_query(...)
    slog.info(
        "LTM query plan generated",
        conversation_id=...,
        semantic_queries=len(plan.semantic_queries),
        lexical_queries=len(plan.lexical_queries),
        has_symbolic=bool(plan.symbolic_filter),
    )

    # 2. 三路检索完成后:
    slog.info(
        "LTM retrieval completed",
        conversation_id=...,
        semantic_hits=len(semantic_results),
        lexical_hits=len(lexical_results),
        symbolic_hits=len(symbolic_results),
        ranked_total=len(ranked),
        duration_ms=round((time.monotonic() - t0) * 1000, 1),
    )
```

**文件:** `src/acabot/runtime/memory/long_term_memory/model_clients.py`

**改动:** 在 `LtmQueryPlannerClient.plan_query()` 和 `LtmEmbeddingClient.embed_texts()` 中添加日志

```python
import time
import structlog

slog = structlog.get_logger("acabot.runtime.memory.ltm.model_clients")

# LtmQueryPlannerClient.plan_query() 完成后:
slog.info(
    "LTM query planner called",
    model=request.model,
    duration_ms=round((time.monotonic() - t0) * 1000, 1),
)

# LtmEmbeddingClient.embed_texts() 完成后:
slog.info(
    "LTM embedding generated",
    text_count=len(texts),
    duration_ms=round((time.monotonic() - t0) * 1000, 1),
)
```

---

## Task 4: LTM 写入侧日志 (LOG-05 — 写入)

**文件:** `src/acabot/runtime/memory/long_term_memory/write_port.py`

**改动:** 在 `LtmWritePort.ingest_thread_delta()` 的每窗口处理完成后添加日志

```python
import time
import structlog

slog = structlog.get_logger("acabot.runtime.memory.ltm.write_port")

# 每窗口完成后:
slog.info(
    "LTM window ingested",
    thread_id=thread_id,
    window_facts=len(window_facts),
    entries_extracted=len(entries),
    duration_ms=round((time.monotonic() - t0) * 1000, 1),
)
```

**文件:** `src/acabot/runtime/memory/long_term_memory/model_clients.py`

**改动:** 在 `LtmExtractorClient.extract_window()` 完成后添加日志

```python
# LtmExtractorClient.extract_window() 完成后:
slog.info(
    "LTM extraction completed",
    conversation_id=conversation_id,
    fact_count=len(facts),
    entries_extracted=len(entries),
    model=request.model,
    duration_ms=round((time.monotonic() - t0) * 1000, 1),
)
```

**文件:** `src/acabot/runtime/memory/long_term_ingestor.py`

**改动:** 增强 `LongTermMemoryIngestor` worker 的日志, 覆盖每次 ingest 的汇总

```python
import structlog

slog = structlog.get_logger("acabot.runtime.memory.long_term_ingestor")

# worker 每次处理一个 thread 后:
slog.info(
    "LTM ingest cycle completed",
    thread_id=thread_id,
    delta_events=len(delta.events),
    delta_messages=len(delta.messages),
    result_advance=result.advance_cursor,
    has_failures=result.has_failures,
    duration_ms=round((time.monotonic() - t0) * 1000, 1),
)
```

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
import structlog
from acabot.runtime.control.log_setup import configure_structlog
configure_structlog()
log = structlog.get_logger('acabot.runtime.memory.ltm.source')
log.info('LTM retrieval completed', semantic_hits=5, lexical_hits=3, ranked_total=7, duration_ms=123.4)
print('LTM structured log: OK')
"
```

---

## Task 5: 单元测试

**文件:** `tests/test_structured_log_emit.py` (新建)

**测试覆盖:**
1. ToolBroker.execute() 成功调用后, InMemoryLogBuffer 中存在 tool_name + duration_ms + result_summary 字段的日志
2. ToolBroker.execute() 失败时, InMemoryLogBuffer 中存在 error 字段的 WARNING 日志
3. Token 用量日志包含 prompt_tokens/completion_tokens/total_tokens/model
4. LTM 日志包含 duration_ms 和计数字段

**测试策略:** 使用 InMemoryLogBuffer + InMemoryLogHandler 捕获日志, 检查 `extra` 字段内容.

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -m pytest tests/test_structured_log_emit.py -v
```

---

## 执行顺序

```
Task 1 (ToolBroker 日志)           -- 独立
Task 2a (Agent token 日志)         -- 独立
Task 2b (Pipeline token 持久化)    -- 依赖 Task 2a (概念上)
Task 3 (LTM 查询侧)               -- 独立
Task 4 (LTM 写入侧)               -- 独立
Task 5 (测试)                      -- 依赖全部
```

Task 1, 2a, 3, 4 可并行执行 (互不依赖). Task 2b 在 Task 2a 之后. Task 5 最后.

---

## 完成标准

- [ ] ToolBroker.execute() 每次调用后有 INFO 日志, extra 包含 `tool_name`, `duration_ms`, `result_summary`
- [ ] LLM run/complete 完成后有 INFO 日志, extra 包含 `prompt_tokens`, `completion_tokens`, `total_tokens`, `model`
- [ ] Token 用量写入 `RunRecord.metadata["token_usage"]`
- [ ] LTM 查询侧: query plan + retrieval 有结构化日志, 包含 timing 和 hit count
- [ ] LTM 写入侧: 每窗口 ingest + extraction 有结构化日志, 包含 timing 和 record count
- [ ] 所有日志自动携带 run_id/thread_id/agent_id (来自 Wave 1 的 contextvars)
- [ ] 测试通过

---

## 风险

- **Agent 日志级别变更:** complete() 路径从 DEBUG 提升到 INFO, 可能增加日志量. 但 token 用量属于关键可观测数据, INFO 级别合理
- **LTM 模块的访问路径:** `source.py` 和 `write_port.py` 的方法签名需要确认具体变量名; 实现时需先读完整文件
- **result_summary 截断:** 工具返回可能含敏感信息, 120 字符截断是合理的安全边界

---

*Wave 2 of 3 — Phase 3c-logging-observability*
*Created: 2026-04-03*
