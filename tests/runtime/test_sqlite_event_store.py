from pathlib import Path

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
