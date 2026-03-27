from acabot.runtime import (
    AgentProfile,
    ChannelEventRecord,
    InMemoryChannelEventStore,
    InMemoryMessageStore,
    MessageRecord,
    Outbox,
    PlannedAction,
    RouteDecision,
    RunContext,
    RunRecord,
    StoreBackedConversationFactReader,
    ThreadState,
)
from acabot.types import Action, ActionType, EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway


async def test_store_backed_conversation_fact_reader_merges_event_and_message_delta() -> None:
    event_store = InMemoryChannelEventStore()
    message_store = InMemoryMessageStore()
    await event_store.save(
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
            metadata={"actor_display_name": "Acacia"},
        )
    )
    await message_store.save(
        MessageRecord(
            message_uid="msg:1",
            thread_id="qq:user:10001",
            actor_id="agent:aca",
            platform="qq",
            role="assistant",
            content_text="world",
            content_json={"text": "world"},
            timestamp=100,
            run_id="run:1",
            metadata={"actor_display_name": "Aca"},
        )
    )

    reader = StoreBackedConversationFactReader(
        channel_event_store=event_store,
        message_store=message_store,
    )
    delta = await reader.get_thread_delta("qq:user:10001", None, None)

    assert [fact.source_kind for fact in delta.facts] == ["channel_event", "message"]
    assert [fact.source_id for fact in delta.facts] == ["evt-1", "msg:1"]
    assert delta.max_event_id == 1
    assert delta.max_message_id == 1
    assert delta.facts[0].actor_display_name == "Acacia"
    assert delta.facts[1].actor_display_name == "Aca"


async def test_store_backed_conversation_fact_reader_respects_sequence_cursors() -> None:
    event_store = InMemoryChannelEventStore()
    message_store = InMemoryMessageStore()
    await event_store.save(
        ChannelEventRecord(
            event_uid="evt-1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            channel_scope="qq:user:10001",
            platform="qq",
            event_type="message",
            message_type="private",
            content_text="old event",
            payload_json={"text": "old event"},
            timestamp=100,
        )
    )
    await event_store.save(
        ChannelEventRecord(
            event_uid="evt-2",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            channel_scope="qq:user:10001",
            platform="qq",
            event_type="message",
            message_type="private",
            content_text="new event",
            payload_json={"text": "new event"},
            timestamp=200,
        )
    )
    await message_store.save(
        MessageRecord(
            message_uid="msg:1",
            thread_id="qq:user:10001",
            actor_id="agent:aca",
            platform="qq",
            role="assistant",
            content_text="old message",
            content_json={"text": "old message"},
            timestamp=150,
            run_id="run:1",
        )
    )
    await message_store.save(
        MessageRecord(
            message_uid="msg:2",
            thread_id="qq:user:10001",
            actor_id="agent:aca",
            platform="qq",
            role="assistant",
            content_text="new message",
            content_json={"text": "new message"},
            timestamp=250,
            run_id="run:2",
        )
    )

    reader = StoreBackedConversationFactReader(
        channel_event_store=event_store,
        message_store=message_store,
    )
    delta = await reader.get_thread_delta(
        "qq:user:10001",
        after_event_id=1,
        after_message_id=1,
    )

    assert [fact.source_id for fact in delta.facts] == ["evt-2", "msg:2"]
    assert delta.max_event_id == 2
    assert delta.max_message_id == 2


async def test_store_backed_conversation_fact_reader_keeps_same_timestamp_source_order_stable() -> None:
    event_store = InMemoryChannelEventStore()
    message_store = InMemoryMessageStore()
    await message_store.save(
        MessageRecord(
            message_uid="msg:2",
            thread_id="qq:user:10001",
            actor_id="agent:aca",
            platform="qq",
            role="assistant",
            content_text="first",
            content_json={"text": "first"},
            timestamp=100,
            run_id="run:1",
        )
    )
    await message_store.save(
        MessageRecord(
            message_uid="msg:1",
            thread_id="qq:user:10001",
            actor_id="agent:aca",
            platform="qq",
            role="assistant",
            content_text="second",
            content_json={"text": "second"},
            timestamp=100,
            run_id="run:2",
        )
    )

    reader = StoreBackedConversationFactReader(
        channel_event_store=event_store,
        message_store=message_store,
    )
    delta = await reader.get_thread_delta("qq:user:10001", None, None)

    assert [fact.source_id for fact in delta.facts] == ["msg:2", "msg:1"]


async def test_store_backed_conversation_fact_reader_prefers_channel_event_before_message_at_same_timestamp() -> None:
    event_store = InMemoryChannelEventStore()
    message_store = InMemoryMessageStore()
    await message_store.save(
        MessageRecord(
            message_uid="msg:1",
            thread_id="qq:user:10001",
            actor_id="agent:aca",
            platform="qq",
            role="assistant",
            content_text="assistant first",
            content_json={"text": "assistant first"},
            timestamp=100,
            run_id="run:1",
        )
    )
    await event_store.save(
        ChannelEventRecord(
            event_uid="evt-1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            channel_scope="qq:user:10001",
            platform="qq",
            event_type="message",
            message_type="private",
            content_text="user second",
            payload_json={"text": "user second"},
            timestamp=100,
        )
    )

    reader = StoreBackedConversationFactReader(
        channel_event_store=event_store,
        message_store=message_store,
    )
    delta = await reader.get_thread_delta("qq:user:10001", None, None)

    assert [fact.source_kind for fact in delta.facts] == ["channel_event", "message"]


async def test_store_backed_conversation_fact_reader_preserves_channel_scope_from_outbox_dispatch() -> None:
    event_store = InMemoryChannelEventStore()
    message_store = InMemoryMessageStore()
    outbox = Outbox(gateway=FakeGateway(), store=message_store)
    ctx = RunContext(
        run=RunRecord(
            run_id="run:1",
            thread_id="thread:custom",
            actor_id="qq:user:10001",
            agent_id="aca",
            trigger_event_id="evt-1",
            status="running",
            started_at=1,
        ),
        event=StandardEvent(
            event_id="evt-1",
            event_type="message",
            platform="qq",
            timestamp=1,
            source=EventSource(
                platform="qq",
                message_type="private",
                user_id="10001",
                group_id=None,
            ),
            segments=[MsgSegment(type="text", data={"text": "hello"})],
            raw_message_id="raw-msg-1",
            sender_nickname="Acacia",
            sender_role=None,
        ),
        decision=RouteDecision(
            thread_id="thread:custom",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
        thread=ThreadState(
            thread_id="thread:custom",
            channel_scope="qq:user:10001",
        ),
        profile=AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
        ),
        actions=[
            PlannedAction(
                action_id="action:1",
                action=Action(
                    action_type=ActionType.SEND_TEXT,
                    target=EventSource(
                        platform="qq",
                        message_type="private",
                        user_id="10001",
                        group_id=None,
                    ),
                    payload={"text": "hello"},
                ),
                thread_content="hello",
            )
        ],
    )

    report = await outbox.dispatch(ctx)
    reader = StoreBackedConversationFactReader(
        channel_event_store=event_store,
        message_store=message_store,
    )
    delta = await reader.get_thread_delta("thread:custom", None, None)

    assert report.has_failures is False
    assert [fact.source_kind for fact in delta.facts] == ["message"]
    assert delta.facts[0].channel_scope == "qq:user:10001"
