from pathlib import Path

import pytest

from acabot.runtime import ChannelEventRecord, SQLiteChannelEventStore


async def test_sqlite_channel_event_store_round_trip(tmp_path: Path) -> None:
    store = SQLiteChannelEventStore(tmp_path / "runtime.db")
    record = ChannelEventRecord(
        event_uid="evt-1",
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        channel_scope="qq:user:10001",
        platform="qq",
        event_type="poke",
        message_type="private",
        content_text="[poke]",
        payload_json={"notice": "poke"},
        timestamp=123,
        run_id="run:1",
        operator_id="qq:user:10002",
        metadata={"run_mode": "record_only"},
        raw_event={"post_type": "notice"},
    )

    await store.save(record)
    saved = await store.get_thread_events("qq:user:10001")

    assert len(saved) == 1
    assert saved[0].event_uid == "evt-1"
    assert saved[0].event_type == "poke"
    assert saved[0].metadata["run_mode"] == "record_only"
    assert saved[0].raw_event["post_type"] == "notice"


async def test_sqlite_channel_event_store_supports_since_and_limit(tmp_path: Path) -> None:
    store = SQLiteChannelEventStore(tmp_path / "runtime.db")
    for index, event_type in enumerate(["message", "poke", "recall"], start=1):
        await store.save(
            ChannelEventRecord(
                event_uid=f"evt-{index}",
                thread_id="qq:user:10001",
                actor_id="qq:user:10001",
                channel_scope="qq:user:10001",
                platform="qq",
                event_type=event_type,
                message_type="private",
                content_text=f"[{event_type}]",
                payload_json={"event_type": event_type},
                timestamp=index * 100,
            )
        )

    recent = await store.get_thread_events("qq:user:10001", since=100, limit=1)

    assert [event.event_uid for event in recent] == ["evt-3"]


async def test_sqlite_channel_event_store_returns_thread_delta_after_sequence(tmp_path: Path) -> None:
    store = SQLiteChannelEventStore(tmp_path / "runtime.db")
    await store.save(
        ChannelEventRecord(
            event_uid="evt-1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            channel_scope="qq:user:10001",
            platform="qq",
            event_type="message",
            message_type="private",
            content_text="one",
            payload_json={"text": "one"},
            timestamp=100,
        )
    )
    await store.save(
        ChannelEventRecord(
            event_uid="evt-2",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            channel_scope="qq:user:10001",
            platform="qq",
            event_type="message",
            message_type="private",
            content_text="two",
            payload_json={"text": "two"},
            timestamp=200,
        )
    )

    delta = await store.get_thread_events_after_sequence(
        "qq:user:10001",
        after_sequence=1,
    )

    assert [item.sequence_id for item in delta] == [2]
    assert [item.record.event_uid for item in delta] == ["evt-2"]


async def test_sqlite_channel_event_store_treats_empty_event_types_as_empty_result(tmp_path: Path) -> None:
    store = SQLiteChannelEventStore(tmp_path / "runtime.db")
    await store.save(
        ChannelEventRecord(
            event_uid="evt-1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            channel_scope="qq:user:10001",
            platform="qq",
            event_type="message",
            message_type="private",
            content_text="one",
            payload_json={"text": "one"},
            timestamp=100,
        )
    )

    recent = await store.get_thread_events("qq:user:10001", event_types=[])
    delta = await store.get_thread_events_after_sequence("qq:user:10001", after_sequence=None, event_types=[])

    assert recent == []
    assert delta == []


async def test_sqlite_channel_event_store_duplicate_save_is_idempotent(tmp_path: Path) -> None:
    store = SQLiteChannelEventStore(tmp_path / "runtime.db")
    record = ChannelEventRecord(
        event_uid="evt-1",
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        channel_scope="qq:user:10001",
        platform="qq",
        event_type="message",
        message_type="private",
        content_text="one",
        payload_json={"text": "one"},
        timestamp=100,
    )

    await store.save(record)
    await store.save(record)

    delta = await store.get_thread_events_after_sequence("qq:user:10001")

    assert [item.sequence_id for item in delta] == [1]


async def test_sqlite_channel_event_store_rejects_conflicting_duplicate_save(tmp_path: Path) -> None:
    store = SQLiteChannelEventStore(tmp_path / "runtime.db")
    await store.save(
        ChannelEventRecord(
            event_uid="evt-1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            channel_scope="qq:user:10001",
            platform="qq",
            event_type="message",
            message_type="private",
            content_text="one",
            payload_json={"text": "one"},
            timestamp=100,
        )
    )

    with pytest.raises(ValueError, match="evt-1"):
        await store.save(
            ChannelEventRecord(
                event_uid="evt-1",
                thread_id="qq:user:10001",
                actor_id="qq:user:10001",
                channel_scope="qq:user:10001",
                platform="qq",
                event_type="message",
                message_type="private",
                content_text="two",
                payload_json={"text": "two"},
                timestamp=100,
            )
        )
