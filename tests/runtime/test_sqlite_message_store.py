from pathlib import Path

from acabot.runtime import MessageRecord, SQLiteMessageStore


async def test_sqlite_message_store_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    store = SQLiteMessageStore(db_path)
    message = MessageRecord(
        message_uid="msg:1",
        thread_id="qq:user:10001",
        actor_id="agent:aca",
        platform="qq",
        role="assistant",
        content_text="hello",
        content_json={"text": "hello"},
        timestamp=123,
        run_id="run:1",
        platform_message_id="platform:1",
        metadata={"origin": "outbox"},
    )

    try:
        await store.save(message)
        restored = await store.get_thread_messages("qq:user:10001")
    finally:
        store.close()

    assert len(restored) == 1
    assert restored[0].message_uid == "msg:1"
    assert restored[0].actor_id == "agent:aca"
    assert restored[0].content_json == {"text": "hello"}
    assert restored[0].metadata["origin"] == "outbox"


async def test_sqlite_message_store_supports_since_and_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    store = SQLiteMessageStore(db_path)

    try:
        await store.save(
            MessageRecord(
                message_uid="msg:1",
                thread_id="qq:user:10001",
                actor_id="agent:aca",
                platform="qq",
                role="assistant",
                content_text="one",
                content_json={"text": "one"},
                timestamp=100,
                run_id="run:1",
                platform_message_id="platform:1",
            )
        )
        await store.save(
            MessageRecord(
                message_uid="msg:2",
                thread_id="qq:user:10001",
                actor_id="agent:aca",
                platform="qq",
                role="assistant",
                content_text="two",
                content_json={"text": "two"},
                timestamp=200,
                run_id="run:2",
                platform_message_id="platform:2",
            )
        )
        recent = await store.get_thread_messages("qq:user:10001", since=150)
        limited = await store.get_thread_messages("qq:user:10001", limit=1)
    finally:
        store.close()

    assert [msg.content_text for msg in recent] == ["two"]
    assert [msg.content_text for msg in limited] == ["two"]
