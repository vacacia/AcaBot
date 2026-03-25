import pytest

from acabot.runtime import InMemoryMessageStore, MessageRecord


async def test_in_memory_message_store_saves_and_filters_by_thread() -> None:
    store = InMemoryMessageStore()

    await store.save(
        MessageRecord(
            message_uid="m1",
            thread_id="thread:1",
            actor_id="qq:user:1",
            platform="qq",
            role="user",
            content_text="hello",
            content_json={"text": "hello"},
            timestamp=100,
        )
    )
    await store.save(
        MessageRecord(
            message_uid="m2",
            thread_id="thread:2",
            actor_id="qq:user:2",
            platform="qq",
            role="user",
            content_text="other",
            content_json={"text": "other"},
            timestamp=200,
        )
    )

    messages = await store.get_thread_messages("thread:1")

    assert len(messages) == 1
    assert messages[0].content_text == "hello"


async def test_in_memory_message_store_supports_since_and_limit() -> None:
    store = InMemoryMessageStore()
    for index in range(3):
        await store.save(
            MessageRecord(
                message_uid=f"m{index}",
                thread_id="thread:1",
                actor_id="qq:user:1",
                platform="qq",
                role="user",
                content_text=f"msg-{index}",
                content_json={"text": f"msg-{index}"},
                timestamp=100 + index,
            )
        )

    messages = await store.get_thread_messages("thread:1", since=100, limit=1)

    assert len(messages) == 1
    assert messages[0].content_text == "msg-2"


async def test_in_memory_message_store_returns_thread_delta_after_sequence() -> None:
    store = InMemoryMessageStore()
    await store.save(
        MessageRecord(
            message_uid="m1",
            thread_id="thread:1",
            actor_id="qq:user:1",
            platform="qq",
            role="user",
            content_text="hello",
            content_json={"text": "hello"},
            timestamp=100,
        )
    )
    await store.save(
        MessageRecord(
            message_uid="m2",
            thread_id="thread:1",
            actor_id="qq:user:1",
            platform="qq",
            role="assistant",
            content_text="world",
            content_json={"text": "world"},
            timestamp=200,
        )
    )

    delta = await store.get_thread_messages_after_sequence("thread:1", after_sequence=1)

    assert [item.sequence_id for item in delta] == [2]
    assert [item.record.message_uid for item in delta] == ["m2"]


async def test_in_memory_message_store_duplicate_save_is_idempotent() -> None:
    store = InMemoryMessageStore()
    record = MessageRecord(
        message_uid="m1",
        thread_id="thread:1",
        actor_id="qq:user:1",
        platform="qq",
        role="assistant",
        content_text="hello",
        content_json={"text": "hello"},
        timestamp=100,
    )

    await store.save(record)
    await store.save(record)

    delta = await store.get_thread_messages_after_sequence("thread:1")

    assert [item.sequence_id for item in delta] == [1]


async def test_in_memory_message_store_rejects_conflicting_duplicate_save() -> None:
    store = InMemoryMessageStore()
    await store.save(
        MessageRecord(
            message_uid="m1",
            thread_id="thread:1",
            actor_id="qq:user:1",
            platform="qq",
            role="assistant",
            content_text="hello",
            content_json={"text": "hello"},
            timestamp=100,
        )
    )

    with pytest.raises(ValueError, match="m1"):
        await store.save(
            MessageRecord(
                message_uid="m1",
                thread_id="thread:1",
                actor_id="qq:user:1",
                platform="qq",
                role="assistant",
                content_text="changed",
                content_json={"text": "changed"},
                timestamp=100,
            )
        )
