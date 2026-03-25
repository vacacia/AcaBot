# Long-Term Memory Write Path Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现长期记忆写入线的框架交互层，让 runtime 能在不引入 LTM 内部算法细节的前提下，完成 `ConversationFactReader`、`LongTermMemoryIngestor`、双游标增量读取，以及 `RuntimeApp / Outbox -> mark_dirty(thread_id)` 的 direct-call 接线。

**Architecture:** 保持事实层真相源不变，继续由 `ChannelEventStore` 和 `MessageStore` 保存外部事件与 assistant 送达事实；新增 sequence-aware 增量读取能力，由 `StoreBackedConversationFactReader` 统一吐出 `ConversationDelta`。写侧对象统一收口到 `LongTermMemoryIngestor`，它同步接 `mark_dirty()` 信号，异步消费 `dirty_threads`，在启动时通过 `ThreadManager.list_threads()` 做一次扫库补偿，但默认 bootstrap 仍允许它缺席，等后续接入具体 LTM backend 时再真正启用。

**Tech Stack:** Python 3.12、`asyncio`、`dataclasses`、`pytest`、现有 `acabot.runtime` bootstrap/storage/contracts、SQLite + InMemory 存储实现。

---

## References

- 设计文档：
  - `/home/acacia/AcaBot/docs/17-3-memory-long-term-memory.md`
- 运行时主线文档：
  - `/home/acacia/AcaBot/docs/05-memory-and-context.md`
  - `/home/acacia/AcaBot/docs/00-ai-entry.md`
- 现有代码主入口：
  - `/home/acacia/AcaBot/src/acabot/runtime/app.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/outbox.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/bootstrap/__init__.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/storage/stores.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/storage/sqlite_stores.py`

## Assumptions Locked In

- 这份计划只实现**写入线框架交互层**，不实现 LTM 内部提取、去重、合并、向量库或 retrieval 命中策略。
- 写入线是 `fact-driven + event-driven`，不是 `run-driven`。
- `mark_dirty(thread_id)` 是同步、best-effort 的 direct call；失败不会拖垮前台主线。
- `LongTermMemoryIngestor` 是写入线唯一对 runtime 暴露的业务对象；对外只暴露 `start() / stop() / mark_dirty()`。
- `ConversationFactReader` 公开面只保留 `get_thread_delta(...) -> ConversationDelta`；启动扫库不再新增第二个公开方法，而是通过 `ThreadManager.list_threads()` + 现有 `get_thread_delta(...)` 完成。
- `dirty_threads` 只存在于内存 `Set`；不新增专门的 dirty 表。
- 双游标边界基于每个 store 的单调 sequence，不使用时间戳做边界。
- 现阶段 bootstrap 只需要支持**注入** `LongTermMemoryIngestor`；如果没有具体 LTM backend，默认装配允许该对象为 `None`。

## File Map

**Create**

- `src/acabot/runtime/memory/conversation_facts.py`
  - 定义 `ConversationFact`、`ConversationDelta`、`ConversationFactReader`、`StoreBackedConversationFactReader`。
- `src/acabot/runtime/memory/long_term_ingestor.py`
  - 定义 `ThreadLtmCursor`、`LongTermMemoryWritePort`、`LongTermMemoryIngestor`。
- `tests/runtime/test_conversation_facts.py`
  - 覆盖统一增量事实窗口、排序、`actor_display_name` 映射、游标边界。
- `tests/runtime/test_long_term_ingestor.py`
  - 覆盖 `mark_dirty()`、启动扫库、worker 生命周期、停机 drain 语义。

**Modify**

- `src/acabot/runtime/contracts/records.py`
  - 补充 sequence-aware 的事实包装类型，避免把 sequence 强塞进原始记录本体。
- `src/acabot/runtime/contracts/__init__.py`
  - 导出新的 sequence-aware record wrapper。
- `src/acabot/runtime/storage/stores.py`
  - 给 `ChannelEventStore` / `MessageStore` 增加按 sequence 读取 thread 增量的方法。
- `src/acabot/runtime/storage/event_store.py`
  - InMemory `ChannelEventStore` 增加 sequence 计数和按 sequence 查询。
- `src/acabot/runtime/storage/memory_store.py`
  - InMemory `MessageStore` 增加 sequence 计数和按 sequence 查询。
- `src/acabot/runtime/storage/sqlite_stores.py`
  - SQLite store 用 `rowid` 暴露 sequence 读取，不改动现有 `event_uid / message_uid` 身份键。
- `src/acabot/runtime/app.py`
  - 事件落盘成功后 best-effort 调用 `LongTermMemoryIngestor.mark_dirty(thread_id)`；顺手把 `sender_nickname` 写入 metadata，供 `actor_display_name` 使用。
- `src/acabot/runtime/outbox.py`
  - assistant 消息落盘成功后 best-effort 调用 `LongTermMemoryIngestor.mark_dirty(thread_id)`；把 `agent_id` 作为基础 `actor_display_name` 写入 metadata。
- `src/acabot/runtime/bootstrap/components.py`
  - 给 `RuntimeComponents` 增加可选的 `long_term_memory_ingestor` 字段，放在 dataclass 末尾并给默认值，避免破坏现有手写构造。
- `src/acabot/runtime/bootstrap/__init__.py`
  - 支持可选注入 `long_term_memory_ingestor`，并把它接进 `RuntimeApp` / `Outbox` / `RuntimeComponents`。
- `src/acabot/runtime/__init__.py`
  - 导出新的 conversation facts / ingestor 公共对象。
- `tests/runtime/test_event_store.py`
- `tests/runtime/test_memory_store.py`
- `tests/runtime/test_sqlite_event_store.py`
- `tests/runtime/test_sqlite_message_store.py`
  - 覆盖按 sequence 增量读取。
- `tests/runtime/test_app.py`
  - 覆盖事件落盘后 `mark_dirty()` 调用与失败隔离。
- `tests/runtime/test_outbox.py`
  - 覆盖 assistant 消息落盘后 `mark_dirty()` 调用与失败隔离。
- `tests/runtime/test_bootstrap.py`
  - 覆盖 optional `long_term_memory_ingestor` 接线。
- `docs/17-3-memory-long-term-memory.md`
- `docs/HANDOFF.md`
  - 若实现名或接线路径与现有文档有微差，再做一次最小同步。

---

### Task 1: 给事实存储补 sequence-aware 增量读取

**Files:**
- Modify: `src/acabot/runtime/contracts/records.py`
- Modify: `src/acabot/runtime/contracts/__init__.py`
- Modify: `src/acabot/runtime/storage/stores.py`
- Modify: `src/acabot/runtime/storage/event_store.py`
- Modify: `src/acabot/runtime/storage/memory_store.py`
- Modify: `src/acabot/runtime/storage/sqlite_stores.py`
- Modify: `src/acabot/runtime/__init__.py`
- Test: `tests/runtime/test_event_store.py`
- Test: `tests/runtime/test_memory_store.py`
- Test: `tests/runtime/test_sqlite_event_store.py`
- Test: `tests/runtime/test_sqlite_message_store.py`

- [ ] **Step 1: 先写失败测试，锁定 sequence 语义**

```python
async def test_in_memory_channel_event_store_returns_thread_delta_after_sequence() -> None:
    store = InMemoryChannelEventStore()
    await store.save(_event("evt-1", ts=100))
    await store.save(_event("evt-2", ts=200))

    delta = await store.get_thread_events_after_sequence("qq:user:10001", after_sequence=1)

    assert [item.sequence_id for item in delta] == [2]
    assert [item.record.event_uid for item in delta] == ["evt-2"]
```

```python
async def test_sqlite_message_store_returns_thread_delta_after_sequence(tmp_path: Path) -> None:
    store = SQLiteMessageStore(tmp_path / "runtime.db")
    await store.save(_message("msg:1", ts=100))
    await store.save(_message("msg:2", ts=200))

    delta = await store.get_thread_messages_after_sequence("qq:user:10001", after_sequence=1)

    assert [item.sequence_id for item in delta] == [2]
    assert [item.record.message_uid for item in delta] == ["msg:2"]
```

- [ ] **Step 2: 跑测试确认当前确实没有这些能力**

Run:

```bash
pytest \
  tests/runtime/test_event_store.py \
  tests/runtime/test_memory_store.py \
  tests/runtime/test_sqlite_event_store.py \
  tests/runtime/test_sqlite_message_store.py -q
```

Expected:

- 因为 `get_thread_events_after_sequence()` / `get_thread_messages_after_sequence()` 不存在而失败。

- [ ] **Step 3: 加 sequence-aware wrapper 和 store 新接口**

```python
@dataclass(slots=True)
class SequencedChannelEventRecord:
    sequence_id: int
    record: ChannelEventRecord


@dataclass(slots=True)
class SequencedMessageRecord:
    sequence_id: int
    record: MessageRecord
```

```python
class ChannelEventStore(ABC):
    @abstractmethod
    async def get_thread_events_after_sequence(
        self,
        thread_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
        event_types: list[str] | None = None,
    ) -> list[SequencedChannelEventRecord]:
        ...
```

```python
class MessageStore(ABC):
    @abstractmethod
    async def get_thread_messages_after_sequence(
        self,
        thread_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[SequencedMessageRecord]:
        ...
```

- [ ] **Step 4: 实现 InMemory / SQLite sequence 读取**

```python
class InMemoryChannelEventStore(ChannelEventStore):
    def __init__(self) -> None:
        self._events: list[SequencedChannelEventRecord] = []
        self._next_sequence = 1

    async def save(self, event: ChannelEventRecord) -> None:
        self._events.append(
            SequencedChannelEventRecord(sequence_id=self._next_sequence, record=event)
        )
        self._next_sequence += 1
```

```python
SELECT
    rowid AS sequence_id,
    event_uid,
    thread_id,
    actor_id,
    ...
FROM channel_events
WHERE thread_id = ?
  AND (? IS NULL OR rowid > ?)
ORDER BY rowid ASC
```

Implementation notes:

- 不要改动现有 `get_thread_events()` / `get_thread_messages()`，保留向后兼容。
- SQLite 用隐式 `rowid` 当 sequence，先落地写入线，不强改现有 `TEXT PRIMARY KEY` 设计。
- `event_uid / message_uid` 继续作为身份键；sequence 只服务增量边界。

- [ ] **Step 5: 跑定向测试确认新接口成立**

Run:

```bash
pytest \
  tests/runtime/test_event_store.py \
  tests/runtime/test_memory_store.py \
  tests/runtime/test_sqlite_event_store.py \
  tests/runtime/test_sqlite_message_store.py -q
```

Expected:

- PASS，且旧的 `since/limit` 测试继续通过。

- [ ] **Step 6: Commit**

```bash
git add \
  src/acabot/runtime/contracts/records.py \
  src/acabot/runtime/contracts/__init__.py \
  src/acabot/runtime/storage/stores.py \
  src/acabot/runtime/storage/event_store.py \
  src/acabot/runtime/storage/memory_store.py \
  src/acabot/runtime/storage/sqlite_stores.py \
  src/acabot/runtime/__init__.py \
  tests/runtime/test_event_store.py \
  tests/runtime/test_memory_store.py \
  tests/runtime/test_sqlite_event_store.py \
  tests/runtime/test_sqlite_message_store.py
git commit -m "feat: add sequence-aware fact store reads"
```

---

### Task 2: 实现 `ConversationFactReader` 和统一增量事实窗口

**Files:**
- Create: `src/acabot/runtime/memory/conversation_facts.py`
- Modify: `src/acabot/runtime/__init__.py`
- Test: `tests/runtime/test_conversation_facts.py`

- [ ] **Step 1: 先写失败测试，锁定 delta 形状和排序**

```python
async def test_store_backed_conversation_fact_reader_merges_event_and_message_delta() -> None:
    event_store = InMemoryChannelEventStore()
    message_store = InMemoryMessageStore()
    await event_store.save(_event("evt-1", ts=100, nickname="Acacia"))
    await message_store.save(_assistant("msg:1", ts=100))

    reader = StoreBackedConversationFactReader(
        channel_event_store=event_store,
        message_store=message_store,
    )
    delta = await reader.get_thread_delta("qq:user:10001", None, None)

    assert [fact.source_kind for fact in delta.facts] == ["channel_event", "message"]
    assert delta.max_event_id == 1
    assert delta.max_message_id == 1
    assert delta.facts[0].actor_display_name == "Acacia"
```

- [ ] **Step 2: 跑测试确认 reader 还不存在**

Run:

```bash
pytest tests/runtime/test_conversation_facts.py -q
```

Expected:

- FAIL，报 `ModuleNotFoundError`、导出缺失，或 `StoreBackedConversationFactReader` 不存在。

- [ ] **Step 3: 加 `ConversationFact` / `ConversationDelta` / `ConversationFactReader`**

```python
@dataclass(slots=True)
class ConversationFact:
    thread_id: str
    timestamp: int
    source_kind: str
    source_id: str
    role: str
    text: str
    payload: dict[str, Any]
    actor_id: str
    actor_display_name: str | None
    channel_scope: str
    run_id: str | None


@dataclass(slots=True)
class ConversationDelta:
    facts: list[ConversationFact]
    max_event_id: int | None
    max_message_id: int | None
```

```python
class ConversationFactReader(Protocol):
    async def get_thread_delta(
        self,
        thread_id: str,
        after_event_id: int | None,
        after_message_id: int | None,
    ) -> ConversationDelta:
        ...
```

- [ ] **Step 4: 实现 `StoreBackedConversationFactReader`**

```python
event_rows = await self.channel_event_store.get_thread_events_after_sequence(
    thread_id,
    after_sequence=after_event_id,
)
message_rows = await self.message_store.get_thread_messages_after_sequence(
    thread_id,
    after_sequence=after_message_id,
)

facts = [*map(self._event_to_fact, event_rows), *map(self._message_to_fact, message_rows)]
facts.sort(key=lambda item: (item.timestamp, item.source_kind, item.source_id))
```

Implementation notes:

- `ConversationFact.source_id` 用 `event_uid / message_uid`，不要用 sequence 取代身份键。
- `actor_display_name` 先读 metadata：
  - event：`record.metadata.get("actor_display_name")`
  - message：`record.metadata.get("actor_display_name")`
- assistant 的 `actor_display_name` 允许为空，但第一版会在 `Outbox` 里补一个基础值。

- [ ] **Step 5: 跑 reader 测试确认 unified delta 行为稳定**

Run:

```bash
pytest tests/runtime/test_conversation_facts.py -q
```

Expected:

- PASS，且相同时间戳下排序稳定，`max_event_id / max_message_id` 返回正确。

- [ ] **Step 6: Commit**

```bash
git add \
  src/acabot/runtime/memory/conversation_facts.py \
  src/acabot/runtime/__init__.py \
  tests/runtime/test_conversation_facts.py
git commit -m "feat: add conversation fact reader"
```

---

### Task 3: 实现 `LongTermMemoryIngestor` 写侧编排骨架

**Files:**
- Create: `src/acabot/runtime/memory/long_term_ingestor.py`
- Modify: `src/acabot/runtime/__init__.py`
- Test: `tests/runtime/test_long_term_ingestor.py`

- [ ] **Step 1: 先写失败测试，锁定 worker 语义**

```python
async def test_long_term_memory_ingestor_consumes_thread_marked_before_start() -> None:
    backend = RecordingLongTermMemoryWritePort()
    ingestor = LongTermMemoryIngestor(
        thread_manager=RecordingThreadManager(["thread:1"]),
        fact_reader=FakeConversationFactReader({"thread:1": _delta("evt-1", "msg:1")}),
        write_port=backend,
    )
    ingestor.mark_dirty("thread:1")

    await ingestor.start()
    await backend.wait_until_ingested("thread:1")
    await ingestor.stop()

    assert backend.ingested_threads == ["thread:1"]
```

```python
async def test_long_term_memory_ingestor_stop_drains_inflight_thread_only() -> None:
    backend = BlockingLongTermMemoryWritePort()
    ingestor = LongTermMemoryIngestor(...)
    ingestor.mark_dirty("thread:1")
    ingestor.mark_dirty("thread:2")

    await ingestor.start()
    await backend.wait_until_started("thread:1")
    await ingestor.stop()

    assert backend.completed_threads == ["thread:1"]
    assert "thread:2" not in backend.completed_threads
```

- [ ] **Step 2: 跑测试确认 ingestor 尚未存在**

Run:

```bash
pytest tests/runtime/test_long_term_ingestor.py -q
```

Expected:

- FAIL，报模块或类型不存在。

- [ ] **Step 3: 实现 `ThreadLtmCursor` 和最小 write port**

```python
@dataclass(slots=True)
class ThreadLtmCursor:
    thread_id: str
    last_event_id: int | None = None
    last_message_id: int | None = None
    updated_at: int = 0


class LongTermMemoryWritePort(Protocol):
    async def load_cursor(self, thread_id: str) -> ThreadLtmCursor | None: ...
    async def save_cursor(self, cursor: ThreadLtmCursor) -> None: ...
    async def ingest_thread_delta(self, thread_id: str, delta: ConversationDelta) -> bool: ...
```

- [ ] **Step 4: 实现 `LongTermMemoryIngestor`**

```python
class LongTermMemoryIngestor:
    def __init__(self, *, thread_manager, fact_reader, write_port) -> None:
        self._thread_manager = thread_manager
        self._fact_reader = fact_reader
        self._write_port = write_port
        self._dirty_threads: set[str] = set()
        self._wake_event = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._startup_reconcile_task: asyncio.Task[None] | None = None
        self._started = False
        self._stopping = False

    def mark_dirty(self, thread_id: str) -> None:
        self._dirty_threads.add(thread_id)
        self._wake_event.set()
```

Implementation notes:

- `start()`：
  - 先起 worker task
  - 再起 startup reconcile task
  - 自己立即返回
- startup reconcile：
  - 调 `thread_manager.list_threads()`
  - 对每个 thread 用现有 `get_thread_delta(...)` 判有没有增量
  - 有增量就复用 `mark_dirty(thread_id)`
- `stop()`：
  - 停止继续领取新 thread
  - 当前 in-flight thread 允许跑完
  - 其余 `dirty_threads` 直接放弃，靠下次启动补回
- 成功才推进游标；失败不推进。

- [ ] **Step 5: 跑 ingestor 单测，确认生命周期和游标推进语义**

Run:

```bash
pytest tests/runtime/test_long_term_ingestor.py -q
```

Expected:

- PASS，覆盖 `mark_dirty()` 预启动可调用、启动扫库、失败不推进游标、停机 drain 语义。

- [ ] **Step 6: Commit**

```bash
git add \
  src/acabot/runtime/memory/long_term_ingestor.py \
  src/acabot/runtime/__init__.py \
  tests/runtime/test_long_term_ingestor.py
git commit -m "feat: add long-term memory ingestor skeleton"
```

---

### Task 4: 把 `mark_dirty(thread_id)` 接进 `RuntimeApp / Outbox / bootstrap`

**Files:**
- Modify: `src/acabot/runtime/app.py`
- Modify: `src/acabot/runtime/outbox.py`
- Modify: `src/acabot/runtime/bootstrap/components.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Modify: `src/acabot/runtime/__init__.py`
- Test: `tests/runtime/test_app.py`
- Test: `tests/runtime/test_outbox.py`
- Test: `tests/runtime/test_bootstrap.py`

- [ ] **Step 1: 先写失败测试，锁定 direct-call 和失败隔离**

```python
async def test_runtime_app_marks_ltm_dirty_after_channel_event_persist() -> None:
    ltm = RecordingIngestor()
    app = RuntimeApp(..., long_term_memory_ingestor=ltm)

    app.install()
    await gateway.handler(_event())

    assert ltm.marked_threads == ["qq:user:10001"]
```

```python
async def test_outbox_mark_dirty_failure_does_not_fail_delivery() -> None:
    ltm = ExplodingIngestor()
    outbox = Outbox(gateway=gateway, store=store, long_term_memory_ingestor=ltm)

    report = await outbox.send_items([item])

    assert report.has_failures is False
    assert store.saved[0].content_text == "hello"
```

- [ ] **Step 2: 跑测试确认当前还没有这条接线**

Run:

```bash
pytest \
  tests/runtime/test_app.py \
  tests/runtime/test_outbox.py \
  tests/runtime/test_bootstrap.py -q
```

Expected:

- FAIL，`RuntimeApp` / `Outbox` 构造参数或生命周期行为不匹配。

- [ ] **Step 3: 修改 `RuntimeApp` 接线和生命周期**

```python
class RuntimeApp:
    def __init__(..., long_term_memory_ingestor: LongTermMemoryIngestor | None = None) -> None:
        self.long_term_memory_ingestor = long_term_memory_ingestor
```

```python
if self._should_persist_event(decision):
    await self.channel_event_store.save(...)
    try:
        if self.long_term_memory_ingestor is not None:
            self.long_term_memory_ingestor.mark_dirty(decision.thread_id)
    except Exception:
        logger.exception("Failed to mark LTM dirty after event persist: thread=%s", decision.thread_id)
```

```python
metadata={
    ...
    "actor_display_name": event.sender_nickname or None,
}
```

Also:

- `start()` 时如果注入了 `long_term_memory_ingestor`，先 `await long_term_memory_ingestor.start()`
- `stop()` 时在 gateway/plugin teardown 之外再 `await long_term_memory_ingestor.stop()`

- [ ] **Step 4: 修改 `Outbox` 和 bootstrap 装配**

```python
class Outbox:
    def __init__(
        self,
        *,
        gateway: GatewayProtocol,
        store: MessageStore,
        long_term_memory_ingestor: LongTermMemoryIngestor | None = None,
    ) -> None:
        self.long_term_memory_ingestor = long_term_memory_ingestor
```

```python
await self.store.save(MessageRecord(..., metadata={
    **item.metadata,
    "actor_display_name": item.agent_id,
}))
try:
    if self.long_term_memory_ingestor is not None:
        self.long_term_memory_ingestor.mark_dirty(item.thread_id)
except Exception:
    logger.exception("Failed to mark LTM dirty after message persist: thread=%s", item.thread_id)
```

```python
@dataclass(slots=True)
class RuntimeComponents:
    ...
    long_term_memory_ingestor: LongTermMemoryIngestor | None = None
```

Implementation notes:

- `RuntimeComponents` 新字段放在末尾并给默认值，避免影响大量手写测试构造。
- `build_runtime_components()` 新增可选参数 `long_term_memory_ingestor=None`，只负责透传，不默认构造具体 LTM backend。

- [ ] **Step 5: 跑接线测试，确认主线不被 LTM 故障拖垮**

Run:

```bash
pytest \
  tests/runtime/test_app.py \
  tests/runtime/test_outbox.py \
  tests/runtime/test_bootstrap.py -q
```

Expected:

- PASS，且 `mark_dirty` 爆炸不会让 event/message 持久化测试失败。

- [ ] **Step 6: Commit**

```bash
git add \
  src/acabot/runtime/app.py \
  src/acabot/runtime/outbox.py \
  src/acabot/runtime/bootstrap/components.py \
  src/acabot/runtime/bootstrap/__init__.py \
  src/acabot/runtime/__init__.py \
  tests/runtime/test_app.py \
  tests/runtime/test_outbox.py \
  tests/runtime/test_bootstrap.py
git commit -m "feat: wire ltm dirty notifications into runtime"
```

---

### Task 5: 收尾导出、文档同步和整体验证

**Files:**
- Modify: `src/acabot/runtime/__init__.py`
- Modify: `docs/17-3-memory-long-term-memory.md`
- Modify: `docs/HANDOFF.md`

- [ ] **Step 1: 回读 public surface，确认导出只暴露框架交互层对象**

公开导出应包含：

- `ConversationFact`
- `ConversationDelta`
- `ConversationFactReader`
- `StoreBackedConversationFactReader`
- `ThreadLtmCursor`
- `LongTermMemoryWritePort`
- `LongTermMemoryIngestor`

不要在这一轮把任何 LTM 内部 store / dedup 细节塞进 runtime 公共导出。

- [ ] **Step 2: 同步文档，只修实现带来的命名差异**

这一步只做最小同步：

- 如果代码里实际采用了 `LongTermMemoryWritePort` 之类的新窄接口名，补到 `docs/17-3-memory-long-term-memory.md`
- 在 `docs/HANDOFF.md` 记下：
  - 事实层 sequence-aware delta 已落地
  - `ConversationFactReader` 和 `LongTermMemoryIngestor` 已存在
  - bootstrap 当前只支持可选注入，不默认启用具体 LTM backend

- [ ] **Step 3: 跑整体验证**

Run:

```bash
pytest \
  tests/runtime/test_event_store.py \
  tests/runtime/test_memory_store.py \
  tests/runtime/test_sqlite_event_store.py \
  tests/runtime/test_sqlite_message_store.py \
  tests/runtime/test_conversation_facts.py \
  tests/runtime/test_long_term_ingestor.py \
  tests/runtime/test_app.py \
  tests/runtime/test_outbox.py \
  tests/runtime/test_bootstrap.py -q
```

Expected:

- 全部 PASS。

- [ ] **Step 4: 最终 Commit**

```bash
git add \
  src/acabot/runtime/__init__.py \
  docs/17-3-memory-long-term-memory.md \
  docs/HANDOFF.md
git commit -m "docs: sync long-term memory write path rollout"
```

---

## Implementation Notes

- 如果在实现 `LongTermMemoryIngestor` 时发现 `LongTermMemoryWritePort` 还需要再窄一点，优先把它收成“游标 + ingest delta”最小面，不要把 LTM 的内部 store 抽象整包拖进 runtime。
- 如果 SQLite `rowid` 方案在测试里出现兼容性问题，再退一步显式加 `INTEGER` sequence 列；但默认先用 `rowid`，这是这份计划的首选落法。
- 不要在这轮里动 retrieval 主线，不要给 `MemoryBroker` 塞写入逻辑，也不要重新引入 event bus。
- `actor_display_name` 这一轮先保证 user 事件可用；assistant 侧先给一个基础可读值即可，不要为了“完美昵称”扩大 OutboxItem 契约。

## Done When

- runtime 能通过可选注入方式挂上 `LongTermMemoryIngestor`
- `RuntimeApp` 和 `Outbox` 在事实落盘成功后都会 best-effort 调 `mark_dirty(thread_id)`
- `ConversationFactReader` 能用双 sequence 游标返回稳定排序的 `ConversationDelta`
- `LongTermMemoryIngestor` 能处理预启动 `mark_dirty`、启动扫库、单 worker 消费、成功推进游标、失败保留 dirty、停机 drain 当前 thread
- 所有定向测试通过，文档与 handoff 同步完成
