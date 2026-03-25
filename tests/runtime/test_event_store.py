import pytest

from acabot.runtime import ChannelEventRecord, InMemoryChannelEventStore


async def test_in_memory_channel_event_store_filters_by_thread_and_type() -> None:
    store = InMemoryChannelEventStore()
    await store.save(
        ChannelEventRecord(
            event_uid="evt-1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            channel_scope="qq:user:10001",
            platform="qq",
            event_type="message",
            message_type="private",
            content_text="hello",
            payload_json={"text": "hello"},
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
            event_type="poke",
            message_type="private",
            content_text="[poke]",
            payload_json={"notice": "poke"},
            timestamp=200,
        )
    )
    await store.save(
        ChannelEventRecord(
            event_uid="evt-3",
            thread_id="qq:group:20002",
            actor_id="qq:user:10002",
            channel_scope="qq:group:20002",
            platform="qq",
            event_type="message",
            message_type="group",
            content_text="group hello",
            payload_json={"text": "group hello"},
            timestamp=300,
        )
    )

    saved = await store.get_thread_events("qq:user:10001", event_types=["poke"])

    assert [event.event_uid for event in saved] == ["evt-2"]


async def test_in_memory_channel_event_store_returns_thread_delta_after_sequence() -> None:
    store = InMemoryChannelEventStore()
    await store.save(
        ChannelEventRecord(
            event_uid="evt-1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            channel_scope="qq:user:10001",
            platform="qq",
            event_type="message",
            message_type="private",
            content_text="hello",
            payload_json={"text": "hello"},
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
            content_text="world",
            payload_json={"text": "world"},
            timestamp=200,
        )
    )

    delta = await store.get_thread_events_after_sequence(
        "qq:user:10001",
        after_sequence=1,
    )

    assert [item.sequence_id for item in delta] == [2]
    assert [item.record.event_uid for item in delta] == ["evt-2"]


async def test_in_memory_channel_event_store_duplicate_save_is_idempotent() -> None:
    store = InMemoryChannelEventStore()
    record = ChannelEventRecord(
        event_uid="evt-1",
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        channel_scope="qq:user:10001",
        platform="qq",
        event_type="message",
        message_type="private",
        content_text="hello",
        payload_json={"text": "hello"},
        timestamp=100,
    )

    await store.save(record)
    await store.save(record)

    delta = await store.get_thread_events_after_sequence("qq:user:10001")

    assert [item.sequence_id for item in delta] == [1]


async def test_in_memory_channel_event_store_rejects_conflicting_duplicate_save() -> None:
    store = InMemoryChannelEventStore()
    await store.save(
        ChannelEventRecord(
            event_uid="evt-1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            channel_scope="qq:user:10001",
            platform="qq",
            event_type="message",
            message_type="private",
            content_text="hello",
            payload_json={"text": "hello"},
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
                content_text="changed",
                payload_json={"text": "changed"},
                timestamp=100,
            )
        )
