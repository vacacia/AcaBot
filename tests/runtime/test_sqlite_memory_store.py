from acabot.runtime import MemoryItem, SQLiteMemoryStore


async def test_sqlite_memory_store_round_trip(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "runtime.sqlite3")
    item = MemoryItem(
        memory_id="memory:1",
        scope="relationship",
        scope_key="qq:user:10001|qq:group:20002",
        memory_type="episodic",
        content="event_type: message\nuser: [acacia/10001] 你好",
        edit_mode="draft",
        author="extractor",
        confidence=0.5,
        source_run_id="run:1",
        source_event_id="evt-1",
        tags=["episodic", "chat"],
        metadata={"event_type": "message"},
        created_at=123,
        updated_at=123,
    )

    await store.upsert(item)
    rows = await store.find(
        scope="relationship",
        scope_key="qq:user:10001|qq:group:20002",
    )

    assert len(rows) == 1
    assert rows[0].memory_id == "memory:1"
    assert rows[0].metadata["event_type"] == "message"


async def test_sqlite_memory_store_filters_by_memory_type_and_limit(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "runtime.sqlite3")
    await store.upsert(
        MemoryItem(
            memory_id="memory:1",
            scope="relationship",
            scope_key="qq:user:10001|qq:group:20002",
            memory_type="episodic",
            content="旧的 episodic",
            edit_mode="draft",
            author="extractor",
            confidence=0.4,
            source_run_id="run:1",
            source_event_id="evt-1",
            tags=[],
            metadata={},
            created_at=100,
            updated_at=100,
        )
    )
    await store.upsert(
        MemoryItem(
            memory_id="memory:2",
            scope="relationship",
            scope_key="qq:user:10001|qq:group:20002",
            memory_type="sticky_note",
            content="姓名: acacia",
            edit_mode="readonly",
            author="user",
            confidence=1.0,
            source_run_id=None,
            source_event_id=None,
            tags=[],
            metadata={},
            created_at=101,
            updated_at=101,
        )
    )
    await store.upsert(
        MemoryItem(
            memory_id="memory:3",
            scope="relationship",
            scope_key="qq:user:10001|qq:group:20002",
            memory_type="episodic",
            content="新的 episodic",
            edit_mode="draft",
            author="extractor",
            confidence=0.7,
            source_run_id="run:3",
            source_event_id="evt-3",
            tags=[],
            metadata={},
            created_at=102,
            updated_at=102,
        )
    )

    rows = await store.find(
        scope="relationship",
        scope_key="qq:user:10001|qq:group:20002",
        memory_types=["episodic"],
        limit=1,
    )

    assert len(rows) == 1
    assert rows[0].memory_id == "memory:3"


async def test_sqlite_memory_store_can_delete_by_memory_id(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "runtime.sqlite3")
    item = MemoryItem(
        memory_id="memory:delete",
        scope="channel",
        scope_key="qq:group:20002",
        memory_type="sticky_note",
        content="群规: 先看公告",
        edit_mode="readonly",
        author="user",
        confidence=1.0,
        source_run_id=None,
        source_event_id=None,
        tags=["rule"],
        metadata={"note_key": "group_rule"},
        created_at=123,
        updated_at=123,
    )

    await store.upsert(item)
    deleted = await store.delete("memory:delete")
    rows = await store.find(
        scope="channel",
        scope_key="qq:group:20002",
        memory_types=["sticky_note"],
    )

    assert deleted is True
    assert rows == []
