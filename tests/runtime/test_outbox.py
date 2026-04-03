import pytest

from acabot.runtime import (
    ResolvedAgent,
    MessageStore,
    MessageRecord,
    Outbox,
    OutboxItem,
    PlannedAction,
    RouteDecision,
    RunContext,
    RunRecord,
    SequencedMessageRecord,
    ThreadState,
)
from acabot.runtime.ids import (
    build_event_source_from_conversation_id,
    build_thread_id_from_conversation_id,
    parse_conversation_id,
)
from acabot.types import Action, ActionType, EventSource, MsgSegment, StandardEvent


class FakeGateway:
    def __init__(self) -> None:
        self.sent: list[Action] = []
        self.handler = None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, action: Action) -> dict[str, object] | None:
        self.sent.append(action)
        return {"message_id": f"msg-{len(self.sent)}", "timestamp": 123}

    def on_event(self, handler) -> None:
        self.handler = handler

    async def call_api(self, action: str, params: dict[str, object]) -> dict[str, object]:
        return {"action": action, "params": params}


class FakeMessageStore(MessageStore):
    def __init__(self) -> None:
        self.saved: list[MessageRecord] = []

    async def save(self, msg: MessageRecord) -> None:
        self.saved.append(msg)

    async def get_thread_messages(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
        since: int | None = None,
    ) -> list[MessageRecord]:
        messages = [msg for msg in self.saved if msg.thread_id == thread_id]
        if since is not None:
            messages = [msg for msg in messages if msg.timestamp > since]
        if limit is not None:
            messages = messages[-limit:]
        return messages

    async def get_thread_messages_after_sequence(
        self,
        thread_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[SequencedMessageRecord]:
        messages = [msg for msg in self.saved if msg.thread_id == thread_id]
        start = 0 if after_sequence is None else after_sequence
        sequenced = [
            SequencedMessageRecord(sequence_id=index, record=msg)
            for index, msg in enumerate(messages, start=1)
            if index > start
        ]
        if limit is not None:
            sequenced = sequenced[:limit]
        return sequenced


class RecordingIngestor:
    def __init__(self) -> None:
        self.marked_threads: list[str] = []
        self.started = 0
        self.stopped = 0

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1

    def mark_dirty(self, thread_id: str) -> None:
        self.marked_threads.append(thread_id)


class ExplodingIngestor(RecordingIngestor):
    def mark_dirty(self, thread_id: str) -> None:
        raise RuntimeError(f"boom:{thread_id}")


@pytest.mark.parametrize(
    ("conversation_id", "actor_user_id", "expected_source"),
    [
        (
            "qq:group:20002",
            "10001",
            EventSource(
                platform="qq",
                message_type="group",
                user_id="10001",
                group_id="20002",
            ),
        ),
        (
            "qq:user:30003",
            "10001",
            EventSource(
                platform="qq",
                message_type="private",
                user_id="30003",
                group_id=None,
            ),
        ),
    ],
)
def test_conversation_id_helpers_build_canonical_destination_event_source(
    conversation_id: str,
    actor_user_id: str,
    expected_source: EventSource,
) -> None:
    platform, scope_value = parse_conversation_id(conversation_id)

    assert platform == "qq"
    assert scope_value == conversation_id.split(":", 2)[2]
    assert (
        build_event_source_from_conversation_id(
            conversation_id,
            actor_user_id=actor_user_id,
        )
        == expected_source
    )
    assert build_thread_id_from_conversation_id(conversation_id) == conversation_id


@pytest.mark.parametrize(
    "invalid_conversation_id",
    [
        "",
        "group:20002",
        "qq:channel:20002",
        "discord:group:20002",
        "qq:group:",
    ],
)
def test_conversation_id_helpers_reject_non_canonical_targets(
    invalid_conversation_id: str,
) -> None:
    with pytest.raises(ValueError):
        parse_conversation_id(invalid_conversation_id)


def test_outbox_item_keeps_origin_and_destination_thread_separate() -> None:
    item = OutboxItem(
        thread_id="qq:user:10001",
        origin_thread_id="qq:user:10001",
        destination_thread_id="qq:group:20002",
        destination_conversation_id="qq:group:20002",
        append_to_origin_thread=False,
        run_id="run:1",
        agent_id="aca",
        plan=PlannedAction(
            action_id="action:1",
            action=Action(
                action_type=ActionType.SEND_TEXT,
                target=EventSource(
                    platform="qq",
                    message_type="group",
                    user_id="10001",
                    group_id="20002",
                ),
                payload={"text": "hello"},
            ),
            thread_content="hello",
        ),
    )

    assert item.thread_id == "qq:user:10001"
    assert item.origin_thread_id == "qq:user:10001"
    assert item.destination_thread_id == "qq:group:20002"
    assert item.destination_conversation_id == "qq:group:20002"
    assert item.append_to_origin_thread is False


async def test_outbox_sends_and_persists_success() -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)

    item = OutboxItem(
        thread_id="qq:user:10001",
        run_id="run:1",
        agent_id="aca",
        plan=PlannedAction(
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
        ),
    )

    report = await outbox.send_items([item])

    assert report.has_failures is False
    assert len(report.delivered_items) == 1
    assert len(gateway.sent) == 1
    assert store.saved[0].content_text == "hello"
    assert store.saved[0].actor_id == "agent:aca"


async def test_outbox_persists_delivered_content_instead_of_thread_content() -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)

    item = OutboxItem(
        thread_id="qq:user:10001",
        run_id="run:1",
        agent_id="aca",
        plan=PlannedAction(
            action_id="action:1",
            action=Action(
                action_type=ActionType.SEND_TEXT,
                target=EventSource(
                    platform="qq",
                    message_type="private",
                    user_id="10001",
                    group_id=None,
                ),
                payload={"text": "delivered text"},
            ),
            thread_content="draft text",
        ),
    )

    report = await outbox.send_items([item])

    assert report.has_failures is False
    assert store.saved[0].content_text == "delivered text"
    assert store.saved[0].content_json == {"text": "delivered text"}
    assert store.saved[0].metadata["thread_content"] == "draft text"


async def test_outbox_extracts_segments_content_for_rich_messages() -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)

    item = OutboxItem(
        thread_id="qq:user:10001",
        run_id="run:1",
        agent_id="aca",
        plan=PlannedAction(
            action_id="action:segments",
            action=Action(
                action_type=ActionType.SEND_SEGMENTS,
                target=EventSource(
                    platform="qq",
                    message_type="private",
                    user_id="10001",
                    group_id=None,
                ),
                payload={
                    "segments": [
                        {"type": "text", "data": {"text": "看这张图 "}},
                        {"type": "image", "data": {"file": "https://example.com/cat.jpg"}},
                    ]
                },
            ),
            thread_content="看这张图 [图片]",
        ),
    )

    report = await outbox.send_items([item])

    assert report.has_failures is False
    assert store.saved[0].content_text == "看这张图 [图片]"
    assert store.saved[0].content_json["segments"][1]["type"] == "image"


async def test_outbox_does_not_persist_non_message_actions() -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)

    item = OutboxItem(
        thread_id="qq:group:20002",
        run_id="run:1",
        agent_id="aca",
        plan=PlannedAction(
            action_id="action:ban",
            action=Action(
                action_type=ActionType.GROUP_BAN,
                target=EventSource(
                    platform="qq",
                    message_type="group",
                    user_id="10001",
                    group_id="20002",
                ),
                payload={"user_id": "999", "duration": 60},
            ),
        ),
    )

    report = await outbox.send_items([item])

    assert report.has_failures is False
    assert len(gateway.sent) == 1
    assert store.saved == []


async def test_outbox_marks_ltm_dirty_after_message_persist() -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    ltm = RecordingIngestor()
    outbox = Outbox(gateway=gateway, store=store, long_term_memory_ingestor=ltm)

    item = OutboxItem(
        thread_id="qq:user:10001",
        run_id="run:1",
        agent_id="aca",
        plan=PlannedAction(
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
        ),
    )

    report = await outbox.send_items([item])

    assert report.has_failures is False
    assert ltm.marked_threads == ["qq:user:10001"]
    assert store.saved[0].metadata["actor_display_name"] == "aca"


async def test_outbox_mark_dirty_failure_does_not_fail_delivery() -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store, long_term_memory_ingestor=ExplodingIngestor())

    item = OutboxItem(
        thread_id="qq:user:10001",
        run_id="run:1",
        agent_id="aca",
        plan=PlannedAction(
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
        ),
    )

    report = await outbox.send_items([item])

    assert report.has_failures is False
    assert store.saved[0].content_text == "hello"


async def test_outbox_dispatch_persists_real_channel_scope_metadata() -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)
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
        agent=ResolvedAgent(
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

    assert report.has_failures is False
    assert store.saved[0].metadata["channel_scope"] == "qq:user:10001"
