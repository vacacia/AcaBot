# Core SimpleMem LanceDB-First Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 AcaBot 的第一版 Core SimpleMem，让长期记忆正式跑在 `LongTermMemoryWritePort + MemorySource` 两条 runtime seam 上，内部采用 `LanceDB-first, storage-layer-contained` 的单实现后端，并把提取、embedding、query planning 都接到统一 `model_target` 模型体系。

**Architecture:** 在 `src/acabot/runtime/memory/long_term_memory/` 下建立一套清晰的 LTM 内部包，分成对象契约、fact/provenance 映射、LanceDB storage/repository、模型调用客户端、写侧 write-port、检索侧 source、ranking 和 renderer。runtime 继续只看到 `LongTermMemoryWritePort` 与 `MemorySource`；Core SimpleMem 内部围绕 LanceDB 落表，但所有 LanceDB 细节都集中在 storage 层，不向 runtime 和提取/检索逻辑泄漏。

**Tech Stack:** Python 3.11、`lancedb`、`pyarrow`、现有 `litellm`、`LongTermMemoryIngestor`、`MemoryBroker`、filesystem-backed model registry、`pytest`。

---

## References

- Spec:
  - `/home/acacia/AcaBot/docs/superpowers/specs/2026-03-27-model-target-registry-and-core-simplemem-design.md`
- LTM docs:
  - `/home/acacia/AcaBot/docs/17-3-memory-long-term-memory.md`
  - `/home/acacia/AcaBot/docs/17-3-memory-retriever-long-term-memory.md`
  - `/home/acacia/AcaBot/docs/LTM/core-simplemem-design.md`
  - `/home/acacia/AcaBot/docs/LTM/core-simplemem-structured.md`
  - `/home/acacia/AcaBot/docs/LTM/simplemem.md`
- Runtime seams:
  - `/home/acacia/AcaBot/src/acabot/runtime/memory/long_term_ingestor.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/memory/conversation_facts.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/memory/memory_broker.py`
  - `/home/acacia/AcaBot/src/acabot/runtime/memory/file_backed/retrievers.py`
- Reference implementation:
  - `/home/acacia/AcaBot/ref/SimpleMem/models/memory_entry.py`
  - `/home/acacia/AcaBot/ref/SimpleMem/database/vector_store.py`
  - `/home/acacia/AcaBot/ref/SimpleMem/core/memory_builder.py`
  - `/home/acacia/AcaBot/ref/SimpleMem/core/hybrid_retriever.py`

## Assumptions Locked In

- 这份计划建立在前一份“model target/binding backend unification”已经完成的前提上。
- Core SimpleMem 第一版只有一个正式存储实现：`LanceDB`。
- 这里的 LanceDB-only 只针对 Core SimpleMem 内部实现，不影响 runtime seam 的数据库透明性。
- Core SimpleMem 内部仍然分层，但不对外承诺通用可插拔数据库后端契约。
- `MemoryEntry` 正式归属范围是 `conversation_id`，不是 `thread_id`。
- `provenance.fact_ids` 是正式身份字段的一部分；`entry_id` 由 `conversation_id + canonical fact_ids` 决定。
- 写侧计量单位按 `fact` 计算，默认 `window_size=50`、`overlap_size=10`。
- 第一版提取、query planning、embedding 都走统一 target：
  - `system:ltm_extract`
  - `system:ltm_query_plan`
  - `system:ltm_embed`
- `system:ltm_answer` 作为保留 target 进入模型系统，但第一版 MemorySource 输出 XML block 时不要求一定启用 answer synthesis。

## File Map

**Create**

- `src/acabot/runtime/memory/long_term_memory/__init__.py`
  - 导出 Core SimpleMem 对外正式对象。
- `src/acabot/runtime/memory/long_term_memory/contracts.py`
  - 定义 `MemoryEntry`、`MemoryProvenance`、`LtmSearchHit`、`FailedWindowRecord`、`ConversationFactAnchorMap` 等正式对象。
- `src/acabot/runtime/memory/long_term_memory/fact_ids.py`
  - 规范化 `e:event_uid / m:message_uid`、本地 `f1/f2/...` 锚点映射、canonical fact set 和 deterministic `entry_id`。
- `src/acabot/runtime/memory/long_term_memory/storage.py`
  - 集中实现 LanceDB 连接、表初始化、entry upsert、FTS、structured filter、cursor/state/failed-window 读写。
- `src/acabot/runtime/memory/long_term_memory/model_clients.py`
  - 提供 `LtmExtractorClient`、`LtmQueryPlannerClient`、`LtmEmbeddingClient`，全部按 `model_target` 调统一模型。
- `src/acabot/runtime/memory/long_term_memory/extractor.py`
  - 构造提取 prompt、解析模型输出、回填 `fact_ids`、做窗口级合法性校验。
- `src/acabot/runtime/memory/long_term_memory/ranking.py`
  - 实现 semantic / lexical / symbolic 合流与位权排序。
- `src/acabot/runtime/memory/long_term_memory/renderer.py`
  - 把 top-k 命中条目渲染成统一 `long_term_memory` XML block。
- `src/acabot/runtime/memory/long_term_memory/write_port.py`
  - 实现 `LongTermMemoryWritePort`，管理滑窗提取、failed window，以及 cursor storage passthrough；cursor 推进时机仍由 `LongTermMemoryIngestor` 控制。
- `src/acabot/runtime/memory/long_term_memory/source.py`
  - 实现 `MemorySource`，执行 query-aware retrieval 并输出一个统一的 `long_term_memory` block。
- `src/acabot/runtime/model/model_embedding_runtime.py`
  - 提供 runtime 统一 embedding 调用 helper，避免 Core SimpleMem 直接碰 `litellm` 细节。
- `tests/runtime/test_long_term_memory_contracts.py`
- `tests/runtime/test_long_term_memory_storage.py`
- `tests/runtime/test_long_term_memory_extractor.py`
- `tests/runtime/test_long_term_memory_write_port.py`
- `tests/runtime/test_long_term_memory_source.py`
- `tests/runtime/test_model_embedding_runtime.py`
  - 覆盖对象契约、LanceDB 存储、提取校验、写侧状态机、source 输出和 embedding target 调用。

**Modify**

- `pyproject.toml`
  - 增加 `lancedb`、`pyarrow` 依赖。
- `src/acabot/runtime/memory/__init__.py`
- `src/acabot/runtime/__init__.py`
  - 导出 Core SimpleMem 对外对象。
- `src/acabot/runtime/bootstrap/builders.py`
  - 增加 Core SimpleMem storage/source/write-port/builders。
- `src/acabot/runtime/bootstrap/__init__.py`
  - 在 config 启用时组装 Core SimpleMem，并接进 `MemoryBroker` 和 `LongTermMemoryIngestor`。
- `src/acabot/runtime/bootstrap/components.py`
  - 如需要，补充 Core SimpleMem 组件字段，便于 control plane 和测试取用。
- `src/acabot/runtime/memory/memory_broker.py`
  - 注册 `long_term_memory` source 时保持统一 `MemorySource` 契约，不发明特权分支。
- `tests/runtime/test_bootstrap.py`
- `tests/runtime/test_long_term_ingestor.py`
- `tests/runtime/test_memory_broker.py`
- `tests/runtime/test_pipeline_runtime.py`
  - 验证 Core SimpleMem 接入 runtime 后的实际装配和 retrieval。
- `docs/17-3-memory-long-term-memory.md`
- `docs/LTM/core-simplemem-design.md`
- `docs/LTM/core-simplemem-structured.md`
- `docs/HANDOFF.md`
  - 同步正式实现边界和存储策略。

---

### Task 1: 先把 Core SimpleMem 正式对象和 fact 身份规则立起来

**Files:**
- Create: `src/acabot/runtime/memory/long_term_memory/contracts.py`
- Create: `src/acabot/runtime/memory/long_term_memory/fact_ids.py`
- Create: `tests/runtime/test_long_term_memory_contracts.py`

- [ ] **Step 1: 先写失败测试，锁定 `MemoryEntry` 和 deterministic identity 规则**

```python
def test_entry_id_is_deterministic_from_conversation_and_fact_set() -> None:
    fact_ids = ["m:msg-2", "e:evt-1", "e:evt-1"]

    entry_id_a = build_memory_entry_id("qq:group:42", fact_ids)
    entry_id_b = build_memory_entry_id("qq:group:42", ["e:evt-1", "m:msg-2"])

    assert entry_id_a == entry_id_b
```

```python
def test_memory_entry_requires_non_empty_topic_and_fact_ids() -> None:
    with pytest.raises(ValueError):
        MemoryEntry(
            entry_id="entry-1",
            conversation_id="qq:group:42",
            topic="",
            lossless_restatement="Alice likes latte.",
            provenance=MemoryProvenance(fact_ids=[]),
        )
```

```python
def test_anchor_map_round_trips_fact_ids() -> None:
    anchors = build_fact_anchor_map(["e:evt-1", "m:msg-1"])

    assert anchors.anchor_for("e:evt-1") == "f1"
    assert anchors.fact_id_for("f2") == "m:msg-1"
```

- [ ] **Step 2: 跑测试确认对象还不存在**

Run:

```bash
pytest tests/runtime/test_long_term_memory_contracts.py -q
```

Expected:

- 因 `long_term_memory` 包和正式对象不存在而失败。

- [ ] **Step 3: 实现正式对象和 fact 身份 helper**

```python
@dataclass(slots=True)
class MemoryProvenance:
    fact_ids: list[str]


@dataclass(slots=True)
class MemoryEntry:
    entry_id: str
    conversation_id: str
    created_at: int
    updated_at: int
    extractor_version: str
    topic: str
    lossless_restatement: str
    keywords: list[str] = field(default_factory=list)
    time_point: str | None = None
    time_interval_start: str | None = None
    time_interval_end: str | None = None
    location: str | None = None
    persons: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    provenance: MemoryProvenance = field(default_factory=lambda: MemoryProvenance(fact_ids=[]))
```

```python
def normalize_fact_ids(fact_ids: list[str]) -> list[str]:
    return sorted({str(item).strip() for item in fact_ids if str(item).strip()})
```

```python
def build_memory_entry_id(conversation_id: str, fact_ids: list[str]) -> str:
    canonical = normalize_fact_ids(fact_ids)
    payload = f"{conversation_id}|{'|'.join(canonical)}"
    return str(uuid.uuid5(LONG_TERM_MEMORY_NAMESPACE, payload))
```

Implementation notes:

- `MemoryEntry.__post_init__()` 要强校验：
  - `topic` 非空
  - `lossless_restatement` 非空
  - `provenance.fact_ids` 至少 1 条
- `fact_ids.py` 里同时提供：
  - `build_fact_id_from_conversation_fact()`
  - `build_fact_anchor_map()`
  - `resolve_anchor_ids()`

- [ ] **Step 4: 跑定向测试确认对象模型稳定**

Run:

```bash
pytest tests/runtime/test_long_term_memory_contracts.py -q
```

Expected:

- PASS。

- [ ] **Step 5: Commit**

```bash
git add \
  src/acabot/runtime/memory/long_term_memory/contracts.py \
  src/acabot/runtime/memory/long_term_memory/fact_ids.py \
  tests/runtime/test_long_term_memory_contracts.py
git commit -m "feat: add core simplemem contracts and fact identity helpers"
```

---

### Task 2: 建立 `LanceDB-first` storage 层，把持久化细节收口

**Files:**
- Create: `src/acabot/runtime/memory/long_term_memory/storage.py`
- Create: `tests/runtime/test_long_term_memory_storage.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: 先写失败测试，锁定 LanceDB 表和基础读写**

```python
def test_lancedb_store_upserts_entry_and_keeps_latest_version(tmp_path: Path) -> None:
    store = LanceDbCoreSimpleMemStore(tmp_path / "lancedb")
    entry = _entry(updated_at=100)
    newer = replace(entry, updated_at=200, keywords=["latte", "coffee"])

    store.upsert_entries([entry])
    store.upsert_entries([newer])

    saved = store.get_entry(entry.entry_id)
    assert saved is not None
    assert saved.updated_at == 200
    assert saved.keywords == ["latte", "coffee"]
```

```python
def test_lancedb_store_supports_symbolic_and_lexical_queries(tmp_path: Path) -> None:
    store = LanceDbCoreSimpleMemStore(tmp_path / "lancedb")
    store.upsert_entries([_entry(topic="咖啡偏好", keywords=["latte"], persons=["Alice"])])

    lexical = store.keyword_search("latte", limit=5)
    symbolic = store.structured_search(persons=["Alice"], entities=[], location=None, time_range=None, limit=5)

    assert len(lexical) == 1
    assert len(symbolic) == 1
```

```python
def test_lancedb_store_persists_cursor_and_failed_window_state(tmp_path: Path) -> None:
    store = LanceDbCoreSimpleMemStore(tmp_path / "lancedb")
    store.save_cursor(ThreadLtmCursor(thread_id="thread:1", last_event_id=10, last_message_id=20))
    store.save_failed_window(FailedWindowRecord(window_id="win:1", conversation_id="qq:group:42", ...))

    assert store.load_cursor("thread:1").last_message_id == 20
    assert store.list_failed_windows("qq:group:42")[0].window_id == "win:1"
```

- [ ] **Step 2: 跑测试确认当前没有 storage 层和依赖**

Run:

```bash
pytest tests/runtime/test_long_term_memory_storage.py -q
```

Expected:

- 因 `lancedb` 依赖和 `storage.py` 不存在而失败。

- [ ] **Step 3: 增加依赖并实现 LanceDB store**

Add to `pyproject.toml`:

```toml
dependencies = [
  "websockets>=12.0",
  "litellm>=1.40.0",
  "aiosqlite>=0.20.0",
  "pyyaml>=6.0",
  "python-dotenv>=1.0.0",
  "lancedb>=0.25.0",
  "pyarrow>=18.0.0",
]
```

Implementation notes:

- `storage.py` 里集中管理：
  - `memory_entries` table
  - `thread_cursors` table
  - `failed_windows` table
- entry table schema 至少包含：

```python
pa.schema([
    pa.field("entry_id", pa.string()),
    pa.field("conversation_id", pa.string()),
    pa.field("created_at", pa.int64()),
    pa.field("updated_at", pa.int64()),
    pa.field("extractor_version", pa.string()),
    pa.field("topic", pa.string()),
    pa.field("lossless_restatement", pa.string()),
    pa.field("keywords", pa.list_(pa.string())),
    pa.field("time_point", pa.string()),
    pa.field("time_interval_start", pa.string()),
    pa.field("time_interval_end", pa.string()),
    pa.field("location", pa.string()),
    pa.field("persons", pa.list_(pa.string())),
    pa.field("entities", pa.list_(pa.string())),
    pa.field("fact_ids", pa.list_(pa.string())),
    pa.field("vector", pa.list_(pa.float32())),
])
```

- FTS 只对 `lossless_restatement` 建索引。
- structured search 直接围绕 LanceDB 的数组/filter 能力写，不额外做通用 SQL 抽象。

- [ ] **Step 4: 跑定向测试确认 LanceDB storage 基本闭环**

Run:

```bash
pytest tests/runtime/test_long_term_memory_storage.py -q
```

Expected:

- PASS。

- [ ] **Step 5: Commit**

```bash
git add \
  pyproject.toml \
  src/acabot/runtime/memory/long_term_memory/storage.py \
  tests/runtime/test_long_term_memory_storage.py
git commit -m "feat: add lancedb-first core simplemem storage"
```

---

### Task 3: 补统一 embedding 调用和提取客户端，别照搬参考版本地 EmbeddingModel

**Files:**
- Create: `src/acabot/runtime/model/model_embedding_runtime.py`
- Create: `src/acabot/runtime/memory/long_term_memory/model_clients.py`
- Create: `src/acabot/runtime/memory/long_term_memory/extractor.py`
- Create: `tests/runtime/test_model_embedding_runtime.py`
- Create: `tests/runtime/test_long_term_memory_extractor.py`

- [ ] **Step 1: 先写失败测试，锁定统一 target 调用**

```python
async def test_model_embedding_runtime_uses_ltm_embed_target(monkeypatch) -> None:
    runtime = ModelEmbeddingRuntime()
    request = RuntimeModelRequest(model="text-embedding-3-large", provider_kind="openai_compatible", ...)

    vectors = await runtime.embed_texts(request, ["Alice likes latte."])

    assert len(vectors) == 1
```

```python
def test_extractor_rejects_window_if_any_entry_lacks_anchor_evidence() -> None:
    response = [
        {
            "topic": "咖啡偏好",
            "lossless_restatement": "Alice 喜欢拿铁。",
            "evidence": [],
        }
    ]

    with pytest.raises(WindowExtractionError):
        parse_extractor_response(...)
```

```python
def test_extractor_maps_local_fact_anchors_back_to_fact_ids() -> None:
    anchors = build_fact_anchor_map(["e:evt-1", "m:msg-1"])
    entries = parse_extractor_response(
        response=[{"topic": "偏好", "lossless_restatement": "Alice 喜欢拿铁。", "evidence": ["f2"]}],
        anchor_map=anchors,
        conversation_id="qq:group:42",
        extractor_version="v1",
        now_ts=123,
    )

    assert entries[0].provenance.fact_ids == ["m:msg-1"]
```

- [ ] **Step 2: 跑测试确认 embedding runtime 和 extractor 都还不存在**

Run:

```bash
pytest \
  tests/runtime/test_model_embedding_runtime.py \
  tests/runtime/test_long_term_memory_extractor.py -q
```

Expected:

- 因统一 embedding helper 和 extractor 不存在而失败。

- [ ] **Step 3: 实现 embedding runtime**

Implementation notes:

- 不复用参考版 SimpleMem 的 `EmbeddingModel`。
- 统一通过 `RuntimeModelRequest` 调 embedding provider。
- `model_embedding_runtime.py` 里集中处理 provider 参数到 `litellm` embedding API 的映射。

```python
class ModelEmbeddingRuntime:
    async def embed_texts(self, request: RuntimeModelRequest, texts: list[str]) -> list[list[float]]:
        kwargs = {"model": request.model, "input": texts, **request.to_request_options()}
        response = await aembedding(**kwargs)
        return [list(item["embedding"]) for item in response["data"]]
```

- [ ] **Step 4: 实现 extractor 客户端和窗口级校验**

Implementation notes:

- `LtmExtractorClient` 用 `system:ltm_extract` target。
- prompt 里显式列出 `f1/f2/...` 锚点和事实文本。
- 输出 schema 至少要求：

```json
{
  "entries": [
    {
      "topic": "string",
      "lossless_restatement": "string",
      "keywords": ["string"],
      "time_point": "string|null",
      "time_interval_start": "string|null",
      "time_interval_end": "string|null",
      "location": "string|null",
      "persons": ["string"],
      "entities": ["string"],
      "evidence": ["f1", "f2"]
    }
  ]
}
```

- 任何一条 entry evidence 为空，都整窗失败。
- extractor 只产出 `MemoryEntry`；去重/upsert 交给 storage。

- [ ] **Step 5: 跑定向测试确认统一模型调用和提取校验成立**

Run:

```bash
pytest \
  tests/runtime/test_model_embedding_runtime.py \
  tests/runtime/test_long_term_memory_extractor.py -q
```

Expected:

- PASS。

- [ ] **Step 6: Commit**

```bash
git add \
  src/acabot/runtime/model/model_embedding_runtime.py \
  src/acabot/runtime/memory/long_term_memory/model_clients.py \
  src/acabot/runtime/memory/long_term_memory/extractor.py \
  tests/runtime/test_model_embedding_runtime.py \
  tests/runtime/test_long_term_memory_extractor.py
git commit -m "feat: add core simplemem model clients and extractor"
```

---

### Task 4: 实现 write-port，把 LongTermMemoryIngestor 接到滑窗提取和 LanceDB 状态机

**Files:**
- Create: `src/acabot/runtime/memory/long_term_memory/write_port.py`
- Create: `tests/runtime/test_long_term_memory_write_port.py`
- Modify: `tests/runtime/test_long_term_ingestor.py`

- [ ] **Step 1: 先写失败测试，锁定写侧窗口、ingestor 推进 cursor 和 failed window 语义**

```python
async def test_long_term_ingestor_advances_cursor_after_write_port_success(tmp_path: Path) -> None:
    port = _write_port(tmp_path)
    ingestor = _ingestor(tmp_path, write_port=port, fact_reader=_reader_with_delta(_delta_with_60_facts()))

    await ingestor._process_thread("thread:1")

    cursor = await port.load_cursor("thread:1")
    assert cursor is not None
    assert cursor.last_event_id == 60
```

```python
async def test_write_port_ingests_delta_in_fact_windows_without_saving_cursor(tmp_path: Path) -> None:
    port = _write_port(tmp_path)
    delta = _delta_with_60_facts()

    ok = await port.ingest_thread_delta("thread:1", delta)

    cursor = await port.load_cursor("thread:1")
    assert ok is True
    assert cursor is None
```

```python
async def test_write_port_records_failed_window_without_advancing_cursor(tmp_path: Path) -> None:
    port = _write_port(tmp_path, extractor=_failing_extractor())
    delta = _delta_with_50_facts()

    ok = await port.ingest_thread_delta("thread:1", delta)

    cursor = await port.load_cursor("thread:1")
    failed = port.store.list_failed_windows("qq:group:42")
    assert ok is False
    assert cursor is None or cursor.last_event_id is None
    assert len(failed) == 1
```

- [ ] **Step 2: 跑测试确认 write-port 不存在**

Run:

```bash
pytest tests/runtime/test_long_term_memory_write_port.py tests/runtime/test_long_term_ingestor.py -q
```

Expected:

- 因 `write_port.py` 和真实 LTM backend 不存在而失败。

- [ ] **Step 3: 实现 `LtmWritePort`**

```python
class LtmWritePort(LongTermMemoryWritePort):
    async def ingest_thread_delta(self, thread_id: str, delta: ConversationDelta) -> bool:
        conversation_id = derive_conversation_id(delta)
        windows = slice_fact_windows(delta.facts, window_size=50, overlap_size=10)
        for window in windows:
            entries = await self.extractor.extract_window(conversation_id=conversation_id, facts=window)
            vectors = await self.embedding_client.embed_entries(entries)
            self.store.upsert_entries(entries, vectors=vectors)
        return True
```

Implementation notes:

- `conversation_id` 来自 `ConversationFact.channel_scope`，不来自 `thread_id`。
- 写侧状态机职责：
  - 先切窗口
  - 每窗提取
  - 每窗 embedding
  - upsert entries
  - 任一窗失败时记录 failed window，并返回 `False`
- `LongTermMemoryIngestor` 继续保持现有 seam 语义：
  - 只有在 `ingest_thread_delta()` 返回 `True` 后，ingestor 才保存新 cursor
  - write-port 只实现 `load_cursor()` / `save_cursor()` 的存储 passthrough，不擅自推进 cursor
- 相同 `entry_id` 再写时只覆盖发生实质变化的字段。

- [ ] **Step 4: 跑定向测试确认 write-port 真能被 ingestor 调用**

Run:

```bash
pytest tests/runtime/test_long_term_memory_write_port.py tests/runtime/test_long_term_ingestor.py -q
```

Expected:

- PASS。
- `tests/runtime/test_long_term_ingestor.py` 负责断言 cursor 推进行为。
- `tests/runtime/test_long_term_memory_write_port.py` 负责断言 failed window、窗口切分和 cursor passthrough。

- [ ] **Step 5: Commit**

```bash
git add \
  src/acabot/runtime/memory/long_term_memory/write_port.py \
  tests/runtime/test_long_term_memory_write_port.py \
  tests/runtime/test_long_term_ingestor.py
git commit -m "feat: connect long-term write port to core simplemem windows"
```

---

### Task 5: 实现 query-aware retrieval、ranking 和 XML renderer，并接成 `MemorySource`

**Files:**
- Create: `src/acabot/runtime/memory/long_term_memory/ranking.py`
- Create: `src/acabot/runtime/memory/long_term_memory/renderer.py`
- Create: `src/acabot/runtime/memory/long_term_memory/source.py`
- Create: `tests/runtime/test_long_term_memory_source.py`
- Modify: `tests/runtime/test_memory_broker.py`
- Modify: `tests/runtime/test_pipeline_runtime.py`

- [ ] **Step 1: 先写失败测试，锁定 source 输出形状**

```python
async def test_long_term_memory_source_returns_single_long_term_memory_block(tmp_path: Path) -> None:
    source = _source_with_hits(tmp_path)
    request = _shared_request(query_text="Alice 喜欢喝什么？")

    blocks = await source(request)

    assert len(blocks) == 1
    assert blocks[0].source == "long_term_memory"
    assert blocks[0].assembly.target_slot == "message_prefix"
```

```python
def test_renderer_outputs_xml_in_rank_order() -> None:
    xml = CoreSimpleMemRenderer().render([_hit(topic="咖啡偏好", rerank_score=150), _hit(topic="工作地点", rerank_score=100)])

    assert xml.startswith("<long_term_memory>")
    assert xml.index("咖啡偏好") < xml.index("工作地点")
```

```python
def test_ranking_prefers_symbolic_semantic_over_lexical_only() -> None:
    scores = score_hits(
        symbolic=True,
        semantic=True,
        lexical=False,
    )
    assert scores.rerank_score == 140
```

- [ ] **Step 2: 跑测试确认 retrieval/source/renderer 还不存在**

Run:

```bash
pytest \
  tests/runtime/test_long_term_memory_source.py \
  tests/runtime/test_memory_broker.py \
  tests/runtime/test_pipeline_runtime.py -q
```

Expected:

- 因 `source.py`、`ranking.py`、`renderer.py` 不存在而失败。

- [ ] **Step 3: 实现 query planning、三路召回和合流排序**

Implementation notes:

- `LtmQueryPlannerClient` 调 `system:ltm_query_plan`，产出：
  - targeted semantic queries
  - lexical keywords
  - symbolic filters
- `storage.py` 提供：
  - `semantic_search(query_vector, limit)`
  - `keyword_search(query_text, limit)`
  - `structured_search(...)`
- `ranking.py` 按 spec 采用位权：

```python
score = 0
if symbolic_hit:
    score += 100
if semantic_hit:
    score += 40
if lexical_hit:
    score += 10
```

- 平手按 `updated_at` 倒序。

- [ ] **Step 4: 实现 XML renderer 和 `CoreSimpleMemMemorySource`**

```python
return [
    MemoryBlock(
        content=renderer.render(top_hits),
        source="long_term_memory",
        scope="conversation",
        source_ids=[item.entry.entry_id for item in top_hits],
        assembly=MemoryAssemblySpec(target_slot="message_prefix", priority=700),
        metadata={"conversation_id": request.channel_scope, "hit_count": len(top_hits)},
    )
]
```

Implementation notes:

- 只返回一个聚合 block，不把每条 entry 拆成多个 `MemoryBlock`。
- 默认 `max_entries = 8`。
- renderer 默认输出轻量 XML：

```xml
<long_term_memory>
  <entry topic="咖啡偏好" time="2025-03-01T09:00:00">Alice 喜欢拿铁。</entry>
</long_term_memory>
```

- [ ] **Step 5: 跑定向测试确认 source 能进 broker 和 pipeline**

Run:

```bash
pytest \
  tests/runtime/test_long_term_memory_source.py \
  tests/runtime/test_memory_broker.py \
  tests/runtime/test_pipeline_runtime.py -q
```

Expected:

- PASS。
- `MemoryBroker` 和 pipeline 不需要给 `long_term_memory` 开特权分支。

- [ ] **Step 6: Commit**

```bash
git add \
  src/acabot/runtime/memory/long_term_memory/ranking.py \
  src/acabot/runtime/memory/long_term_memory/renderer.py \
  src/acabot/runtime/memory/long_term_memory/source.py \
  tests/runtime/test_long_term_memory_source.py \
  tests/runtime/test_memory_broker.py \
  tests/runtime/test_pipeline_runtime.py
git commit -m "feat: add core simplemem retrieval source and xml renderer"
```

---

### Task 6: 接进 bootstrap，形成真正可装配的 runtime 组件

**Files:**
- Modify: `src/acabot/runtime/bootstrap/builders.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Modify: `src/acabot/runtime/bootstrap/components.py`
- Modify: `src/acabot/runtime/memory/__init__.py`
- Modify: `src/acabot/runtime/__init__.py`
- Modify: `tests/runtime/test_bootstrap.py`

- [ ] **Step 1: 先写失败测试，锁定 runtime 装配结果**

```python
async def test_build_runtime_components_registers_long_term_memory_source_and_ingestor(tmp_path: Path) -> None:
    components = build_runtime_components(_config_with_long_term_memory(tmp_path), gateway=FakeGateway(), agent=FakeAgent(...))

    assert components.long_term_memory_ingestor is not None
    assert components.memory_broker.registry.get("long_term_memory") is not None
```

- [ ] **Step 2: 跑测试确认 bootstrap 还没接上真正的 LTM backend**

Run:

```bash
pytest tests/runtime/test_bootstrap.py -q
```

Expected:

- 因当前 bootstrap 只支持 optional 注入，不会自己装配 Core SimpleMem 而失败。

- [ ] **Step 3: 增加 builder 和 config 开关**

Implementation notes:

- `runtime.long_term_memory.enabled` 作为最小开关。
- `builders.py` 增加：
  - `build_long_term_memory_store()`
  - `build_long_term_memory_write_port()`
  - `build_long_term_memory_source()`
- `build_memory_broker()` 在启用时注册 `"long_term_memory"`。
- `build_runtime_components()` 在启用时先解析一个局部实例：

```python
runtime_long_term_memory_ingestor = long_term_memory_ingestor or build_long_term_memory_ingestor(
    config,
    thread_manager=runtime_thread_manager,
    fact_reader=runtime_fact_reader,
    write_port=runtime_long_term_memory_write_port,
)
```

- 后续必须把这个 `runtime_long_term_memory_ingestor` 传给：
  - `Outbox(...)`
  - `RuntimeApp(...)`
  - 返回的 `RuntimeComponents(...)`
- 不要继续把原始函数参数 `long_term_memory_ingestor` 直接透传下去，否则本地 builder 结果会被丢掉。

- [ ] **Step 4: 跑定向测试确认 runtime 真能装上 Core SimpleMem**

Run:

```bash
pytest tests/runtime/test_bootstrap.py -q
```

Expected:

- PASS。

- [ ] **Step 5: Commit**

```bash
git add \
  src/acabot/runtime/bootstrap/builders.py \
  src/acabot/runtime/bootstrap/__init__.py \
  src/acabot/runtime/bootstrap/components.py \
  src/acabot/runtime/memory/__init__.py \
  src/acabot/runtime/__init__.py \
  tests/runtime/test_bootstrap.py
git commit -m "feat: wire core simplemem into runtime bootstrap"
```

---

### Task 7: 文档和整组回归收尾

**Files:**
- Modify: `docs/17-3-memory-long-term-memory.md`
- Modify: `docs/LTM/core-simplemem-design.md`
- Modify: `docs/LTM/core-simplemem-structured.md`
- Modify: `docs/HANDOFF.md`

- [ ] **Step 1: 更新文档里的实现边界**

Implementation notes:

- 明写：
  - runtime 只通过 `LongTermMemoryWritePort + MemorySource` 交接
  - 第一版 Core SimpleMem 只有 LanceDB 实现
  - 以后如果换库，影响面应集中在 storage 层
- 删除任何还把旧 `structured_memory` 当正式主线的表述。

- [ ] **Step 2: 更新 HANDOFF**

Write three sentences only:

```md
Core SimpleMem 已经按 `LanceDB-first, storage-layer-contained` 落地，runtime 只通过 write-port 和 memory source 接它。
提取、query planning 和 embedding 全部走统一 `model_target`，不要再照搬参考版本地 EmbeddingModel。
后续如果扩 LTM 功能，先看 `long_term_memory` 包内部分层，再决定改 extractor、storage 还是 source，不要把 LanceDB 细节泄漏回 runtime。
```

- [ ] **Step 3: 跑整组 Core SimpleMem 回归**

Run:

```bash
pytest \
  tests/runtime/test_long_term_memory_contracts.py \
  tests/runtime/test_long_term_memory_storage.py \
  tests/runtime/test_model_embedding_runtime.py \
  tests/runtime/test_long_term_memory_extractor.py \
  tests/runtime/test_long_term_memory_write_port.py \
  tests/runtime/test_long_term_memory_source.py \
  tests/runtime/test_long_term_ingestor.py \
  tests/runtime/test_memory_broker.py \
  tests/runtime/test_pipeline_runtime.py \
  tests/runtime/test_bootstrap.py -q
```

Expected:

- PASS。
- 没有测试再依赖旧通用长期记忆主线。

- [ ] **Step 4: Commit**

```bash
git add \
  docs/17-3-memory-long-term-memory.md \
  docs/LTM/core-simplemem-design.md \
  docs/LTM/core-simplemem-structured.md \
  docs/HANDOFF.md
git commit -m "docs: describe core simplemem lancedb-first runtime wiring"
```

---

## Exit Criteria

- Core SimpleMem 真正通过 `LongTermMemoryWritePort` 写入，通过 `MemorySource` 检索。
- AcaBot 版 embedding 调用走统一 `model_target`，不再沿用参考版本地 embedding helper。
- LTM 内部所有 LanceDB 细节都集中在 storage 层，不泄漏到 runtime seam。
- `MemoryEntry` 使用 deterministic `entry_id` 和 canonical `fact_ids`。
- retrieval 返回单一 `long_term_memory` XML block，并按正式 ranking 规则排序。
