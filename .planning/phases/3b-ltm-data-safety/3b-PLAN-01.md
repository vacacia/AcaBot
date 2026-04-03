# Phase 3b Wave 1: LTM 写锁 + 优雅降级 + 启动校验

**Phase:** 3b-ltm-data-safety
**Wave:** 1 of 2
**Scope:** LTM-01 (write serialization) + LTM-04 (graceful degradation) + LTM-03 (startup validation)
**Depends on:** 无外部依赖
**Estimated tasks:** 7

---

## 执行顺序

```
Task 1 (LTM-01) — threading.Lock 写序列化
Task 2 (LTM-01) — 写锁并发测试
Task 3 (LTM-04) — bootstrap 启动降级
Task 4 (LTM-04) — RuntimeApp.start() ingestor 降级 + LtmMemorySource 内部降级
Task 5 (LTM-03) — LanceDbLongTermMemoryStore.validate() 方法
Task 6 (LTM-03) — bootstrap 中接入 validate + 降级联动
Task 7          — 集成测试: 并发写入 + 启动损坏 + mid-pipeline 失败
```

---

## Task 1: threading.Lock 写序列化

**需求:** LTM-01
**文件:** `src/acabot/runtime/memory/long_term_memory/storage.py`

### 改动

1. 在文件顶部 `import` 区域新增 `import threading` (L19 附近)

2. 新增 `import logging` 和 logger (Task 5 也需要):
   ```python
   logger = logging.getLogger("acabot.runtime.memory.long_term_memory")
   ```

3. 在 `LanceDbLongTermMemoryStore.__init__()` (L404-417) 中, 在 `self.root_dir = Path(root_dir)` 之后新增:
   ```python
   self._write_lock = threading.Lock()
   ```

4. 在以下 6 个写方法的入口处用 `with self._write_lock:` 包裹整个方法体:
   - `upsert_entries()` (L419-448) — 包含 `_normalize_entry_vectors` + `_rewrite_entries_table`
   - `save_cursor()` (L597-614) — 包含读当前行 + `_rewrite_table` + `open_table`
   - `save_failed_window()` (L636-653) — 包含读当前行 + `_rewrite_table` + `open_table`
   - `delete_entry()` (L790-806)
   - `delete_entries_by_conversation()` (L808-824)
   - `update_entry()` (L826-876)

### 设计决策

- 选择 `threading.Lock` 而非 `asyncio.Lock`, 因为所有写操作最终在 `asyncio.to_thread()` 线程池执行
- 锁加在 `LanceDbLongTermMemoryStore` 层而非 `LtmWritePort` 层, 保护 WebUI/ControlPlane 直接调用的 delete/update 路径 (参考 RESEARCH.md L252-254)
- 读操作不加锁, 允许读写并发 (LanceDB 读不会因并发写而 crash, 最多读到旧数据)
- Ingestor 本身是单 worker 串行模型 (RESEARCH.md L249), 竞态主要来自 Ingestor 和 WebUI 并发

### 验证

```bash
cd /data/workspace/agent/AcaBot && python -c "
import threading
from pathlib import Path
from acabot.runtime.memory.long_term_memory.storage import LanceDbLongTermMemoryStore
store = LanceDbLongTermMemoryStore('/tmp/test_ltm_lock')
assert hasattr(store, '_write_lock')
assert isinstance(store._write_lock, threading.Lock)
print('OK: write lock exists')
"
```

---

## Task 2: 写锁并发测试

**需求:** LTM-01 验证
**文件:** `tests/runtime/test_ltm_write_lock.py` (新建)

### 测试用例

1. **test_concurrent_upsert_entries_serialize** — 两个并发 `asyncio.to_thread(store.upsert_entries, ...)` 完成后, 两批 entries 都能读回, 不丢数据
2. **test_concurrent_upsert_and_delete_serialize** — 并发 upsert + delete_entry, 结果一致 (delete 的条目确实消失, upsert 的条目存在)
3. **test_concurrent_save_cursor_serialize** — 两个并发 save_cursor, 后写入的 cursor 生效

### 测试策略

- 使用 `tmp_path` fixture 创建临时 LanceDB 目录
- 使用 `asyncio.gather()` 并发触发两个 `asyncio.to_thread()` 调用
- 构造最小 `MemoryEntry` (需 entry_id, conversation_id, extractor_version, topic, lossless_restatement, provenance.fact_ids) + `ThreadLtmCursor` 测试对象
- 写入后逐条 `get_entry()` / `load_cursor()` 验证数据完整
- 参考现有测试 `tests/runtime/test_long_term_memory_storage.py` 的 entry 构造方式

### 验证

```bash
cd /data/workspace/agent/AcaBot && python -m pytest tests/runtime/test_ltm_write_lock.py -v
cd /data/workspace/agent/AcaBot && python -m pytest tests/runtime/test_long_term_memory_storage.py -v
```

---

## Task 3: bootstrap 启动降级

**需求:** LTM-04
**文件:** `src/acabot/runtime/bootstrap/__init__.py`

### 改动

1. 在文件顶部添加 logger:
   ```python
   import logging
   logger = logging.getLogger("acabot.runtime.bootstrap")
   ```

2. 在 `build_runtime_components()` 函数中, 把 L190-218 整个 LTM 构造块用 try/except 包裹:

   当前代码 (L184-224):
   ```python
   long_term_memory_conf = dict(runtime_conf.get("long_term_memory", {}))
   long_term_memory_enabled = bool(long_term_memory_conf.get("enabled", False))
   runtime_long_term_memory_source = None
   runtime_long_term_memory_ingestor = long_term_memory_ingestor
   runtime_fact_reader = None
   runtime_long_term_memory_store = None
   if long_term_memory_enabled and ...:
       # ... 构造 store, source, write_port, ingestor ...
   ```

   改为:
   ```python
   long_term_memory_conf = dict(runtime_conf.get("long_term_memory", {}))
   long_term_memory_enabled = bool(long_term_memory_conf.get("enabled", False))
   runtime_long_term_memory_source = None
   runtime_long_term_memory_ingestor = long_term_memory_ingestor
   runtime_fact_reader = None
   runtime_long_term_memory_store = None
   try:
       if long_term_memory_enabled and (memory_broker is None or runtime_long_term_memory_ingestor is None):
           runtime_long_term_memory_store = build_long_term_memory_store(config)
       if long_term_memory_enabled and memory_broker is None:
           # ... 原 source 构造逻辑 ...
       if long_term_memory_enabled and runtime_long_term_memory_ingestor is None:
           # ... 原 write_port + ingestor 构造逻辑 ...
   except Exception:
       logger.exception("LTM 初始化失败, 将在无长期记忆模式下运行")
       runtime_long_term_memory_store = None
       runtime_long_term_memory_source = None
       runtime_long_term_memory_ingestor = None
       runtime_fact_reader = None
   ```

### 设计决策

- try/except 范围覆盖所有 LTM 相关组件构造, 一处失败全部降级
- 降级后 memory_broker 中 ltm source 为 None, 不会注册 ltm memory source
- RuntimeApp 收到 `long_term_memory_ingestor=None`, 启动时跳过 ingestor

### 验证

```bash
cd /data/workspace/agent/AcaBot && python -c "
import logging; logging.basicConfig(level=logging.DEBUG)
from acabot.runtime.bootstrap import build_runtime_components
print('OK: bootstrap imports clean')
"
```

---

## Task 4: RuntimeApp.start() ingestor 降级 + LtmMemorySource 内部降级

**需求:** LTM-04
**文件:** `src/acabot/runtime/app.py`, `src/acabot/runtime/memory/long_term_memory/source.py`

### 改动 4a: app.py

修改 `RuntimeApp.start()` (L125-154), 把 ingestor 启动从全局 try/except 中分离:

当前 (L131-154):
```python
try:
    if self.long_term_memory_ingestor is not None:
        await self.long_term_memory_ingestor.start()
    if self.scheduler is not None:
        await self.scheduler.start()
    self.install()
    await self.gateway.start()
except Exception:
    # ... rollback scheduler, ingestor, plugins ...
    raise
```

改为:
```python
if self.long_term_memory_ingestor is not None:
    try:
        await self.long_term_memory_ingestor.start()
    except Exception:
        logger.exception("LTM ingestor 启动失败, 将继续运行但无 LTM 写入能力")
        self.long_term_memory_ingestor = None
try:
    if self.scheduler is not None:
        await self.scheduler.start()
    self.install()
    await self.gateway.start()
except Exception:
    if self.scheduler is not None:
        try:
            await self.scheduler.stop()
        except Exception:
            logger.exception("Failed to stop scheduler after startup failure")
    # 注意: 移除了 ingestor rollback 代码 (L144-148), 因为 ingestor 已独立处理
    if self.plugin_runtime_host is not None:
        try:
            await self.plugin_runtime_host.teardown_all()
        except Exception:
            logger.exception("Failed to teardown runtime plugins after gateway start failure")
    raise
```

### 改动 4b: source.py

在 `LtmMemorySource.__call__()` (L151 起) 外层包裹 try/except, 提供更精确的错误日志:

```python
async def __call__(self, request: SharedMemoryRetrievalRequest) -> list[MemoryBlock]:
    try:
        # ... 原方法体 (query planner -> 三路召回 -> rerank -> render) ...
    except Exception:
        logger.exception("LTM 检索失败 (conversation=%s), 返回空结果",
                         str(request.channel_scope or ""))
        return []
```

需要在文件顶部添加:
```python
logger = logging.getLogger("acabot.runtime.memory.long_term_memory")
```

### 设计决策

- MemoryBroker 已有 source 级 catch (memory_broker.py L162-173), 但 LtmMemorySource 内部 catch 提供更精确的错误上下文
- ingestor 启动失败不影响 scheduler/gateway/plugin 的正常启动

### 验证

```bash
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.app import RuntimeApp
print('OK: app imports clean')
"
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.memory.long_term_memory.source import LtmMemorySource
print('OK: source imports clean')
"
```

---

## Task 5: LanceDbLongTermMemoryStore.validate() 方法

**需求:** LTM-03
**文件:** `src/acabot/runtime/memory/long_term_memory/storage.py`

### 改动

1. 在文件顶部 import 区域添加 `from dataclasses import dataclass, field` (如果尚未存在)

2. 在 `LanceDbLongTermMemoryStore` 类定义之前 (L397 附近) 新增校验结果 dataclass:

```python
@dataclass(slots=True)
class LtmValidationResult:
    """LTM 存储校验结果.

    Attributes:
        ok: 校验是否通过.
        warnings: 非致命问题列表.
        errors: 致命问题列表.
    """

    ok: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
```

3. 在 `LanceDbLongTermMemoryStore` 类上新增 `validate()` 方法 (在 `__init__` 之后):

```python
def validate(self) -> LtmValidationResult:
    """校验 LanceDB 存储完整性.

    检查项:
    1. 每个表能否执行 to_arrow() 读取
    2. memory_entries 表的 column names 是否包含必需字段
    3. thread_cursors 和 failed_windows 表的 column names 是否包含必需字段

    Returns:
        校验结果, 包含状态和告警/错误信息.
    """

    warnings: list[str] = []
    errors: list[str] = []

    # 检查 memory_entries 表
    try:
        table = self._entries.to_arrow()
        expected = {"entry_id", "conversation_id", "topic", "lossless_restatement", "lexical_text"}
        missing = expected - set(table.column_names)
        if missing:
            errors.append(f"memory_entries 表缺少必需列: {missing}")
    except Exception as exc:
        errors.append(f"memory_entries 表读取失败: {exc}")

    # 检查 thread_cursors 表
    try:
        table = self._cursors.to_arrow()
        expected = {"thread_id", "last_event_id", "last_message_id", "updated_at"}
        missing = expected - set(table.column_names)
        if missing:
            errors.append(f"thread_cursors 表缺少必需列: {missing}")
    except Exception as exc:
        errors.append(f"thread_cursors 表读取失败: {exc}")

    # 检查 failed_windows 表
    try:
        table = self._failed_windows.to_arrow()
        expected = {"window_id", "conversation_id", "thread_id", "fact_ids"}
        missing = expected - set(table.column_names)
        if missing:
            errors.append(f"failed_windows 表缺少必需列: {missing}")
    except Exception as exc:
        errors.append(f"failed_windows 表读取失败: {exc}")

    return LtmValidationResult(ok=len(errors) == 0, warnings=warnings, errors=errors)
```

4. 将 `LtmValidationResult` 加入 `__all__`

### 设计决策

- validate() 只检查必需列子集, 不要求精确匹配 — 允许未来新增列而不触发误报
- 使用 `to_arrow()` 作为 "可读性" 检查, 这是最基本的表操作
- `LtmValidationResult` 放在 storage.py 而非 contracts.py, 因为只有 storage 层使用

### 验证

```bash
cd /data/workspace/agent/AcaBot && python -c "
from acabot.runtime.memory.long_term_memory.storage import LanceDbLongTermMemoryStore
store = LanceDbLongTermMemoryStore('/tmp/test_ltm_validate')
result = store.validate()
assert result.ok, f'validation failed: {result.errors}'
print('OK: validate() passes on fresh store')
"
```

---

## Task 6: bootstrap 中接入 validate + 降级联动

**需求:** LTM-03 + LTM-04 联动
**文件:** `src/acabot/runtime/bootstrap/builders.py`

### 改动

1. 在文件顶部添加 logger (如果 Task 3 还未添加):
   ```python
   import logging
   logger = logging.getLogger("acabot.runtime.bootstrap")
   ```

2. 修改 `build_long_term_memory_store()` (L185-208):

当前:
```python
def build_long_term_memory_store(config: Config) -> LanceDbLongTermMemoryStore:
    long_term_memory_conf = _long_term_memory_config(config)
    storage_dir = resolve_runtime_path(config, long_term_memory_conf.get("storage_dir", "long_term_memory/lancedb"))
    try:
        from ..memory.long_term_memory.storage import LanceDbLongTermMemoryStore
    except ModuleNotFoundError as exc:
        missing_module = str(getattr(exc, "name", "") or "lancedb")
        raise RuntimeError(...) from exc
    return LanceDbLongTermMemoryStore(storage_dir)
```

改为:
```python
def build_long_term_memory_store(config: Config) -> LanceDbLongTermMemoryStore:
    """按当前配置构造长期记忆的 LanceDB 存储.

    构造后执行完整性校验, 校验失败时抛 RuntimeError.

    Args:
        config: 当前 runtime 配置.

    Returns:
        已通过完整性校验的 LanceDB 存储对象.

    Raises:
        RuntimeError: LanceDB 依赖缺失或存储校验失败.
    """
    long_term_memory_conf = _long_term_memory_config(config)
    storage_dir = resolve_runtime_path(config, long_term_memory_conf.get("storage_dir", "long_term_memory/lancedb"))
    try:
        from ..memory.long_term_memory.storage import LanceDbLongTermMemoryStore
    except ModuleNotFoundError as exc:
        missing_module = str(getattr(exc, "name", "") or "lancedb")
        raise RuntimeError(
            "runtime.long_term_memory.enabled=true requires LanceDB runtime dependencies; "
            f"missing module: {missing_module}"
        ) from exc
    store = LanceDbLongTermMemoryStore(storage_dir)
    validation = store.validate()
    for warning in validation.warnings:
        logger.warning("LTM 校验警告: %s", warning)
    if not validation.ok:
        for error in validation.errors:
            logger.error("LTM 校验错误: %s", error)
        raise RuntimeError(f"LTM 存储完整性校验失败: {'; '.join(validation.errors)}")
    return store
```

**关键设计:** `build_long_term_memory_store()` 保持抛异常的语义 (不返回 None), 由 Task 3 的 bootstrap try/except 统一捕获并降级. 这样职责分离更清晰:
- `build_long_term_memory_store()` 负责 "构造 + 校验", 失败就抛
- `build_runtime_components()` 负责 "降级", 捕获异常后设 None

### 验证

```bash
cd /data/workspace/agent/AcaBot && python -m pytest tests/runtime/ -k "bootstrap or ltm" -v --no-header 2>&1 | head -40
```

---

## Task 7: 集成测试

**需求:** 全部 4 条 Success Criteria
**文件:** `tests/runtime/test_ltm_data_safety.py` (新建)

### 测试用例

#### SC-1: 并发写入序列化 (与 Task 2 互补, 此处更面向集成)
```python
async def test_concurrent_writes_no_data_loss(tmp_path):
    """两个并发 LTM 写操作序列化, 两批数据都能读回 (SC-1)."""
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    batch_a = [make_entry("a-1"), make_entry("a-2")]
    batch_b = [make_entry("b-1"), make_entry("b-2")]
    await asyncio.gather(
        asyncio.to_thread(store.upsert_entries, batch_a),
        asyncio.to_thread(store.upsert_entries, batch_b),
    )
    for entry_id in ["a-1", "a-2", "b-1", "b-2"]:
        assert store.get_entry(entry_id) is not None
```

#### SC-2: (Wave 2 — 备份, 不在此 wave 测试)

#### SC-3: 启动损坏降级
```python
def test_corrupted_store_degrades_gracefully(tmp_path, caplog):
    """损坏的 LanceDB 目录 -> build_long_term_memory_store 抛异常, bootstrap 降级 (SC-3)."""
    # 方案 A: mock LanceDbLongTermMemoryStore.__init__ 抛异常
    # 方案 B: 构造一个 store 后 mock validate 返回 ok=False
    # 验证: bootstrap 的 try/except 捕获异常, log 中包含 "LTM 初始化失败"
    # 验证: runtime_long_term_memory_ingestor 为 None
```

#### SC-4: mid-pipeline LTM 失败不阻断
```python
async def test_ltm_source_failure_does_not_block_pipeline():
    """LtmMemorySource 抛异常时, MemoryBroker 记录 failure 但返回正常结果 (SC-4)."""
    # 构造一个 __call__ 会抛异常的 mock LtmMemorySource
    # 注册到 MemoryBroker 作为 "long_term_memory" source
    # 调用 broker.retrieve()
    # 验证: 不抛异常, 返回结果中 failures 包含 ltm source 的失败信息
```

#### 附加: validate() 正向测试
```python
def test_validate_healthy_store(tmp_path):
    """正常 store 的 validate() 返回 ok=True."""
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    result = store.validate()
    assert result.ok
    assert not result.errors
```

### 辅助函数

```python
def make_entry(entry_id: str) -> MemoryEntry:
    """构造最小合法 MemoryEntry 测试对象."""
    return MemoryEntry(
        entry_id=entry_id,
        conversation_id="test-conv",
        created_at=1000,
        updated_at=1000,
        extractor_version="test-v1",
        topic=f"topic-{entry_id}",
        lossless_restatement=f"restatement-{entry_id}",
        provenance=MemoryProvenance(fact_ids=[f"fact-{entry_id}"]),
    )
```

### 验证

```bash
cd /data/workspace/agent/AcaBot && python -m pytest tests/runtime/test_ltm_data_safety.py -v
cd /data/workspace/agent/AcaBot && python -m pytest tests/runtime/test_ltm_write_lock.py tests/runtime/test_ltm_data_safety.py -v
```

---

## 全量回归验证

完成所有 7 个 Task 后:

```bash
cd /data/workspace/agent/AcaBot && python -m pytest tests/ -v --timeout=60
```

重点确认现有测试不回归:
```bash
cd /data/workspace/agent/AcaBot && python -m pytest tests/runtime/test_long_term_memory_storage.py tests/runtime/test_long_term_memory_write_port.py tests/runtime/test_long_term_memory_source.py tests/runtime/test_long_term_ingestor.py tests/runtime/test_bootstrap.py tests/runtime/test_app.py -v
```

---

## 文件变更汇总

| 文件 | 操作 | Task |
|------|------|------|
| `src/acabot/runtime/memory/long_term_memory/storage.py` | 修改 (threading.Lock + LtmValidationResult + validate) | 1, 5 |
| `src/acabot/runtime/bootstrap/__init__.py` | 修改 (logger + try/except LTM 降级) | 3 |
| `src/acabot/runtime/bootstrap/builders.py` | 修改 (logger + validate 接入) | 6 |
| `src/acabot/runtime/app.py` | 修改 (ingestor 启动独立 try/except) | 4 |
| `src/acabot/runtime/memory/long_term_memory/source.py` | 修改 (logger + __call__ try/except) | 4 |
| `tests/runtime/test_ltm_write_lock.py` | 新建 | 2 |
| `tests/runtime/test_ltm_data_safety.py` | 新建 | 7 |

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| `threading.Lock` 在线程池中阻塞线程 | LTM 写入频率低 (ingestor 单 worker + 偶发 WebUI), 阻塞时间可接受 |
| schema 迁移导致 validate 误报 | validate 只检查必需列子集, 允许新增列, 宽松匹配 |
| bootstrap try/except 过宽可能吞掉非 LTM 的异常 | try 块严格限定在 `if long_term_memory_enabled:` 内, 只覆盖 LTM 组件构造 |
| `LanceDbLongTermMemoryStore()` 构造函数内部 connect + ensure_table 失败 | 异常自然传播到 bootstrap 的 try/except, 统一降级 |

## Success Criteria 覆盖

| SC | 描述 | Task |
|----|------|------|
| SC-1 | 两个并发 LTM 写操作序列化, 读回验证无数据丢失 | Task 1 + 2 + 7 |
| SC-2 | 定期备份产生可恢复快照 | Wave 2 (3b-PLAN-02) |
| SC-3 | 启动时损坏 LanceDB 表, 记录 warning, LTM 禁用模式继续运行 | Task 3 + 5 + 6 + 7 |
| SC-4 | Mid-pipeline LTM 失败不阻止 agent 完成响应 | Task 4 + 7 (+ 已有 MemoryBroker catch) |
