from pathlib import Path

from acabot.runtime import SQLiteThreadStore, StoreBackedThreadManager, ThreadRecord


async def test_sqlite_thread_store_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    store = SQLiteThreadStore(db_path)
    record = ThreadRecord(
        thread_id="qq:group:20002",
        channel_scope="qq:group:20002",
        thread_kind="channel",
        working_messages=[
            {"role": "user", "content": "[10001] hello"},
            {"role": "assistant", "content": "hello back"},
        ],
        working_summary="group summary",
        last_event_at=456,
        metadata={"scene": "group"},
    )

    try:
        await store.upsert(record)
        restored = await store.get(record.thread_id)
    finally:
        store.close()

    assert restored is not None
    assert restored.thread_id == record.thread_id
    assert restored.working_messages == record.working_messages
    assert restored.working_summary == "group summary"
    assert restored.metadata["scene"] == "group"


async def test_store_backed_thread_manager_recovers_state_after_restart(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    store1 = SQLiteThreadStore(db_path)
    manager1 = StoreBackedThreadManager(store1)
    thread = await manager1.get_or_create(
        thread_id="qq:user:10001",
        channel_scope="qq:user:10001",
        last_event_at=123,
    )
    thread.working_messages.append({"role": "user", "content": "[10001] hello"})
    thread.working_summary = "private summary"
    thread.metadata["profile"] = "aca"
    await manager1.save(thread)
    store1.close()

    store2 = SQLiteThreadStore(db_path)
    manager2 = StoreBackedThreadManager(store2)
    try:
        restored = await manager2.get("qq:user:10001")
    finally:
        store2.close()

    assert restored is not None
    assert restored.thread_id == "qq:user:10001"
    assert restored.working_messages == [{"role": "user", "content": "[10001] hello"}]
    assert restored.working_summary == "private summary"
    assert restored.metadata["profile"] == "aca"
