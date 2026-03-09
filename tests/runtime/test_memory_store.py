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
