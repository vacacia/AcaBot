from acabot.runtime import InMemoryThreadManager


async def test_thread_manager_creates_thread_without_agent_binding() -> None:
    manager = InMemoryThreadManager()

    thread = await manager.get_or_create(
        thread_id="qq:group:20002",
        channel_scope="qq:group:20002",
        last_event_at=123,
    )

    assert thread.thread_id == "qq:group:20002"
    assert thread.channel_scope == "qq:group:20002"
    assert thread.last_event_at == 123
    assert thread.working_messages == []


async def test_thread_manager_updates_existing_thread_metadata() -> None:
    manager = InMemoryThreadManager()

    thread = await manager.get_or_create(
        thread_id="qq:user:10001",
        channel_scope="qq:user:10001",
        last_event_at=100,
    )
    thread.working_summary = "summary"

    updated = await manager.get_or_create(
        thread_id="qq:user:10001",
        channel_scope="qq:user:10001",
        last_event_at=200,
    )

    assert updated is thread
    assert updated.last_event_at == 200
    assert updated.working_summary == "summary"
