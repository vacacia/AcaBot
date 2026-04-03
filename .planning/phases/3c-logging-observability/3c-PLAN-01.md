# 3c-PLAN-01: Wave 1 — structlog 基础设施 + Run Context 传播

**Phase:** 3c-logging-observability
**Wave:** 1 of 3
**Covers:** LOG-06 (structlog 集成) + LOG-03 (run context 自动关联)
**Depends on:** 无 (基础设施层, 其他 wave 依赖本 wave)

---

## 目标

为整个 runtime 建立 structlog 基础设施: 包装 stdlib logging, 通过 contextvars 自动传播 run_id/thread_id/agent_id, 扩展 LogEntry 支持结构化字段存储. 完成后, 所有在 pipeline 内产生的日志自动携带 run context 字段.

---

## Task 1: 添加 structlog 依赖

**文件:** `pyproject.toml`

**改动:**
- 在 `dependencies` 列表中添加 `"structlog>=24.1.0"`

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "import structlog; print(structlog.__version__)"
```

---

## Task 2: 创建 structlog 配置模块

**文件:** `src/acabot/runtime/control/log_setup.py` (新建)

**职责:**
- 提供 `configure_structlog()` 函数, 初始化 structlog processor chain
- Wrapper 模式: structlog 包装 stdlib logging, 所有日志最终仍通过 stdlib LogRecord 输出
- 提供 `bind_run_context()` / `clear_run_context()` 便利函数封装 `structlog.contextvars`

**内容骨架:**
```python
"""runtime.control.log_setup 提供 structlog 初始化和 run context 绑定."""

from __future__ import annotations

import structlog


# 需要从 LogRecord.__dict__ 中排除的 stdlib 标准属性名集合
# 用于 InMemoryLogHandler 提取 extra 字段时过滤
STDLIB_LOG_RECORD_ATTRS: frozenset[str] = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "process", "processName", "taskName",
    # logging 内部属性
    "message", "asctime",
    # 自定义已处理属性
    "log_kind",
})


def configure_structlog() -> None:
    """初始化 structlog, 采用 wrapper-over-stdlib 模式.

    调用时机: setup_logging() 之后, 确保 stdlib handler 已就绪.
    """

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def bind_run_context(
    *,
    run_id: str,
    thread_id: str,
    agent_id: str,
) -> None:
    """在当前 async context 中绑定 run 级别字段.

    绑定后, 该 context 内所有 structlog 日志自动携带这些字段.
    stdlib logger 如果通过 structlog ProcessorFormatter 输出, 也会携带.

    Args:
        run_id: 当前 run 的 ID.
        thread_id: 当前 thread 的 ID.
        agent_id: 当前 agent 的 ID.
    """

    structlog.contextvars.bind_contextvars(
        run_id=run_id,
        thread_id=thread_id,
        agent_id=agent_id,
    )


def clear_run_context() -> None:
    """清除当前 async context 中的 run 级别字段.

    在 pipeline 入口处调用, 防止上一个 run 的字段泄露到新 run.
    """

    structlog.contextvars.clear_contextvars()


def extract_extra_fields(record) -> dict:
    """从 LogRecord 中提取结构化 extra 字段.

    排除 stdlib 标准属性和已知自定义属性, 剩余的都算 extra.

    Args:
        record: logging.LogRecord 实例.

    Returns:
        dict: 结构化字段字典, 可能为空.
    """

    extra = {}
    for key, value in record.__dict__.items():
        if key.startswith("_"):
            continue
        if key in STDLIB_LOG_RECORD_ATTRS:
            continue
        extra[key] = value
    return extra
```

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.control.log_setup import configure_structlog, bind_run_context, clear_run_context, STDLIB_LOG_RECORD_ATTRS
print('STDLIB attrs count:', len(STDLIB_LOG_RECORD_ATTRS))
print('OK')
"
```

---

## Task 3: 扩展 LogEntry + InMemoryLogHandler 支持结构化字段

**文件:** `src/acabot/runtime/control/log_buffer.py`

**改动:**
1. `LogEntry` 增加 `extra: dict[str, Any]` 字段, 默认空 dict
2. `InMemoryLogHandler.emit()` 调用 `extract_extra_fields(record)` 提取结构化字段, 写入 `LogEntry.extra`
3. `list_entries()` 的 keyword 过滤扩展: 同时搜索 extra 的 key 和 value

**具体改动点:**

```python
# LogEntry dataclass 新增字段:
from typing import Any
# ...
@dataclass(slots=True)
class LogEntry:
    timestamp: float
    level: str
    logger: str
    message: str
    kind: str = "runtime"
    seq: int = 0
    extra: dict[str, Any] = field(default_factory=dict)  # 新增


# InMemoryLogHandler.emit() 改动:
def emit(self, record: logging.LogRecord) -> None:
    try:
        message = record.getMessage()
    except Exception:
        message = str(record.msg)
    # 新增: 提取 extra 字段
    from .log_setup import extract_extra_fields
    extra = extract_extra_fields(record)
    self.buffer.append(
        LogEntry(
            timestamp=time.time(),
            level=str(record.levelname or "INFO"),
            logger=str(record.name or ""),
            message=message,
            kind=str(getattr(record, "log_kind", "") or "runtime"),
            extra=extra,
        )
    )
```

**向后兼容:** `asdict(LogEntry)` 会自动包含 `extra` 字段; 没有 extra 的日志返回空 dict. HTTP API 无需改动.

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
import logging
from acabot.runtime.control.log_buffer import InMemoryLogBuffer, InMemoryLogHandler, LogEntry
buf = InMemoryLogBuffer(max_entries=10)
handler = InMemoryLogHandler(buf)
logger = logging.getLogger('test.structured')
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)
logger.info('Tool executed', extra={'tool_name': 'bash', 'duration_ms': 42})
result = buf.list_entries()
items = result['items']
assert len(items) == 1
assert items[0]['extra']['tool_name'] == 'bash'
assert items[0]['extra']['duration_ms'] == 42
print('LogEntry extra fields: OK')
"
```

---

## Task 4: 集成 structlog 到启动流程

**文件:** `src/acabot/main.py`

**改动:**
1. 在 `setup_logging()` 末尾调用 `configure_structlog()`
2. 保留 `ColorLogFormatter` + `InMemoryLogHandler` 双 handler 结构不变
3. structlog 通过 stdlib LoggerFactory 桥接, 最终仍走现有 handler

**具体改动:**

```python
# 在 setup_logging() 末尾添加:
from .runtime.control.log_setup import configure_structlog

def setup_logging(config: Config) -> None:
    # ... 现有逻辑不变 ...
    logging.getLogger("websockets.server").addFilter(NoisyWebsocketHandshakeFilter())
    # 新增: 初始化 structlog
    configure_structlog()
```

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
import structlog
from acabot.config import Config
# 模拟 setup_logging
import logging
logging.basicConfig(level=logging.WARNING, force=True)
logging.getLogger('acabot').setLevel(logging.DEBUG)
from acabot.runtime.control.log_setup import configure_structlog
configure_structlog()
log = structlog.get_logger('acabot.test')
log.info('hello', tool_name='bash')
print('structlog integration: OK')
"
```

---

## Task 5: Pipeline 入口绑定 run context

**文件:** `src/acabot/runtime/pipeline.py`

**改动:**
1. 在 `ThreadPipeline.execute()` 入口 (mark_running 之后) 调用 `clear_run_context()` + `bind_run_context()`
2. 在 execute 的 finally 块中调用 `clear_run_context()` 清理

**具体改动:**

```python
from .control.log_setup import bind_run_context, clear_run_context

async def execute(self, ctx: RunContext, *, deliver_actions: bool = True) -> None:
    await self.run_manager.mark_running(ctx.run.run_id)
    # 新增: 绑定 run context 到 structlog contextvars
    clear_run_context()
    bind_run_context(
        run_id=ctx.run.run_id,
        thread_id=ctx.thread.thread_id,
        agent_id=ctx.agent.agent_id,
    )
    logger.debug(
        "Pipeline started: run_id=%s thread=%s agent=%s ...",
        ...
    )
    try:
        # ... 现有逻辑不变 ...
    except Exception as exc:
        logger.exception("ThreadPipeline crashed: run_id=%s", ctx.run.run_id)
        # ... 现有错误处理 ...
    finally:
        # 新增: 清理 run context
        clear_run_context()
```

**效果:** 绑定后, pipeline 内所有组件 (ToolBroker, MemoryBroker, ComputerRuntime 等) 的日志自动携带 run_id/thread_id/agent_id -- 无需修改下游代码.

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -c "
import structlog
from acabot.runtime.control.log_setup import configure_structlog, bind_run_context, clear_run_context
configure_structlog()
bind_run_context(run_id='run-001', thread_id='thread-abc', agent_id='main')
log = structlog.get_logger('acabot.test')
# structlog logger 在 emit 时会自动合并 contextvars
print('context binding: OK')
clear_run_context()
print('context clear: OK')
"
```

---

## Task 6: 单元测试

**文件:** `tests/test_structured_logging.py` (新建)

**测试覆盖:**
1. `LogEntry` 包含 `extra` 字段, `asdict()` 正确序列化
2. `InMemoryLogHandler.emit()` 正确提取 extra 字段
3. `extract_extra_fields()` 正确排除 stdlib 标准属性
4. `bind_run_context()` 绑定后, structlog 日志携带 run_id/thread_id/agent_id
5. `clear_run_context()` 清理后, 字段不再出现
6. `list_entries()` 的 keyword 过滤能搜索到 extra 中的值 (如果实现了扩展搜索)

**验证:**
```bash
cd /data/workspace/agent/AcaBot && python -m pytest tests/test_structured_logging.py -v
```

---

## 执行顺序

```
Task 1 (pyproject.toml)
  |
  v
Task 2 (log_setup.py 新建)
  |
  v
Task 3 (log_buffer.py 扩展)  -- 依赖 Task 2 的 extract_extra_fields
  |
  v
Task 4 (main.py 集成)        -- 依赖 Task 2 + Task 3
  |
  v
Task 5 (pipeline.py 绑定)    -- 依赖 Task 2
  |
  v
Task 6 (测试)                -- 验证全部
```

---

## 完成标准

- [ ] `structlog` 在 pyproject.toml dependencies 中
- [ ] `configure_structlog()` 在启动流程中被调用
- [ ] `LogEntry.extra` 字段存在且默认为空 dict
- [ ] `InMemoryLogHandler.emit()` 从 LogRecord 提取结构化字段到 `extra`
- [ ] `ThreadPipeline.execute()` 入口绑定 run_id/thread_id/agent_id
- [ ] Pipeline 异常/完成时清理 contextvars
- [ ] HTTP API `/api/system/logs` 返回的 LogEntry 包含 `extra` 字段
- [ ] 测试通过

---

## 风险

- **structlog 版本兼容:** `structlog>=24.1.0` 要求 Python 3.8+, 与 3.11 兼容
- **LogRecord extra 提取:** 黑名单策略可能漏排某些 stdlib 内部属性; `STDLIB_LOG_RECORD_ATTRS` 需要覆盖完整. 可以在 Task 3 中用 `logging.LogRecord("", 0, "", 0, "", (), None).__dict__` 动态生成基线属性集
- **asyncio Task context 拷贝:** `asyncio.create_task()` 自动拷贝 context snapshot, 子任务继承 run context -- 这是期望行为. 但 `clear_run_context()` 只清理当前 task, 不影响已拷贝的子任务

---

*Wave 1 of 3 — Phase 3c-logging-observability*
*Created: 2026-04-03*
