from pathlib import Path

import pytest

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


async def test_sqlite_message_store_returns_thread_delta_after_sequence(tmp_path: Path) -> None:
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

        delta = await store.get_thread_messages_after_sequence(
            "qq:user:10001",
            after_sequence=1,
        )
    finally:
        store.close()

    assert [item.sequence_id for item in delta] == [2]
    assert [item.record.message_uid for item in delta] == ["msg:2"]


async def test_sqlite_message_store_duplicate_save_is_idempotent(tmp_path: Path) -> None:
    store = SQLiteMessageStore(tmp_path / "runtime.db")
    record = MessageRecord(
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

    try:
        await store.save(record)
        await store.save(record)
        delta = await store.get_thread_messages_after_sequence("qq:user:10001")
    finally:
        store.close()

    assert [item.sequence_id for item in delta] == [1]


async def test_sqlite_message_store_rejects_conflicting_duplicate_save(tmp_path: Path) -> None:
    store = SQLiteMessageStore(tmp_path / "runtime.db")

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

        with pytest.raises(ValueError, match="msg:1"):
            await store.save(
                MessageRecord(
                    message_uid="msg:1",
                    thread_id="qq:user:10001",
                    actor_id="agent:aca",
                    platform="qq",
                    role="assistant",
                    content_text="two",
                    content_json={"text": "two"},
                    timestamp=100,
                    run_id="run:1",
                    platform_message_id="platform:1",
                )
            )
    finally:
        store.close()
