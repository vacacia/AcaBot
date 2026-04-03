from pathlib import Path

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
from acabot.runtime.render.protocol import RenderResult
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


class FakeRenderService:
    def __init__(self, result: RenderResult) -> None:
        self.result = result
        self.calls: list[dict[str, str | None]] = []

    async def render_markdown_to_image(
        self,
        *,
        markdown_text: str,
        conversation_id: str,
        run_id: str,
        backend_name: str | None = None,
        filename_stem: str = "rendered",
    ) -> RenderResult:
        self.calls.append(
            {
                "markdown_text": markdown_text,
                "conversation_id": conversation_id,
                "run_id": run_id,
                "backend_name": backend_name,
                "filename_stem": filename_stem,
            }
        )
        return self.result


def _send_intent_context(
    *,
    text: str | None = None,
    images: list[str] | None = None,
    render: str | None = None,
    reply_to: str | None = None,
    at_user: str | None = None,
    target: str | None = None,
    thread_content: str | None = None,
) -> RunContext:
    event_source = EventSource(
        platform="qq",
        message_type="private",
        user_id="10001",
        group_id=None,
    )
    destination_conversation_id = target or "qq:user:10001"
    action_target = (
        build_event_source_from_conversation_id(
            destination_conversation_id,
            actor_user_id=event_source.user_id,
        )
        if target is not None
        else event_source
    )
    return RunContext(
        run=RunRecord(
            run_id="run:send-intent",
            thread_id="qq:user:10001",
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
            source=event_source,
            segments=[MsgSegment(type="text", data={"text": "hello"})],
            raw_message_id="raw-msg-1",
            sender_nickname="Acacia",
            sender_role=None,
        ),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
        thread=ThreadState(
            thread_id="qq:user:10001",
            channel_scope="qq:user:10001",
        ),
        agent=ResolvedAgent(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
        ),
        actions=[
            PlannedAction(
                action_id="action:send-intent",
                action=Action(
                    action_type=ActionType.SEND_MESSAGE_INTENT,
                    target=action_target,
                    payload={
                        "text": text,
                        "images": list(images or []),
                        "render": render,
                        "at_user": at_user,
                        "target": destination_conversation_id,
                    },
                    reply_to=reply_to,
                ),
                thread_content=thread_content,
                metadata={
                    "message_action": "send",
                    "suppresses_default_reply": True,
                    "destination_conversation_id": destination_conversation_id,
                },
            )
        ],
    )


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
    scope_kind, scope_value = parse_conversation_id(conversation_id)

    assert scope_kind == conversation_id.split(":", 2)[1]
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


async def test_outbox_materializes_send_intent_text_and_reply_to_into_one_action() -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)
    ctx = _send_intent_context(
        text="hello world",
        reply_to="msg-42",
        thread_content="hello world",
    )

    report = await outbox.dispatch(ctx)

    assert report.has_failures is False
    assert len(gateway.sent) == 1
    sent_action = gateway.sent[0]
    assert sent_action.action_type == ActionType.SEND_SEGMENTS
    assert sent_action.reply_to == "msg-42"
    assert sent_action.payload["segments"] == [
        {"type": "text", "data": {"text": "hello world"}}
    ]


async def test_outbox_builds_at_segment_before_text() -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)
    ctx = _send_intent_context(
        text="大家好",
        at_user="20002",
        thread_content="@20002 大家好",
    )

    report = await outbox.dispatch(ctx)

    assert report.has_failures is False
    sent_action = gateway.sent[0]
    assert sent_action.action_type == ActionType.SEND_SEGMENTS
    assert sent_action.payload["segments"][0] == {"type": "at", "data": {"qq": "20002"}}
    assert sent_action.payload["segments"][1] == {"type": "text", "data": {"text": "大家好"}}


async def test_outbox_materializes_images() -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)
    ctx = _send_intent_context(
        images=["/tmp/cat.png", "https://example.com/cat.jpg"],
        thread_content="[图片][图片]",
    )

    report = await outbox.dispatch(ctx)

    assert report.has_failures is False
    sent_action = gateway.sent[0]
    assert sent_action.action_type == ActionType.SEND_SEGMENTS
    assert sent_action.payload["segments"] == [
        {"type": "image", "data": {"file": "/tmp/cat.png"}},
        {"type": "image", "data": {"file": "https://example.com/cat.jpg"}},
    ]


async def test_outbox_render_falls_back_to_plain_text_segment_without_backend() -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)
    ctx = _send_intent_context(
        render="# Title\n\n$E=mc^2$",
        thread_content="# Title\n\n$E=mc^2$",
    )

    report = await outbox.dispatch(ctx)

    assert report.has_failures is False
    sent_action = gateway.sent[0]
    assert sent_action.action_type == ActionType.SEND_SEGMENTS
    assert sent_action.payload["segments"] == [
        {"type": "text", "data": {"text": "# Title\n\n$E=mc^2$"}}
    ]


async def test_outbox_calls_injected_render_service_in_materialization(
    tmp_path: Path,
) -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    artifact_path = tmp_path / "runtime_data" / "render.png"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    render_service = FakeRenderService(
        RenderResult.ok(
            backend_name="playwright",
            artifact_path=artifact_path,
            html="<p>rendered</p>",
        )
    )
    outbox = Outbox(
        gateway=gateway,
        store=store,
        render_service=render_service,
    )
    ctx = _send_intent_context(
        text="说明文字",
        render="# Title",
        thread_content="说明文字 [图片]",
    )

    report = await outbox.dispatch(ctx)

    assert report.has_failures is False
    assert render_service.calls == [
        {
            "markdown_text": "# Title",
            "conversation_id": "qq:user:10001",
            "run_id": "run:send-intent",
            "backend_name": None,
            "filename_stem": "rendered",
        }
    ]
    sent_action = gateway.sent[0]
    assert sent_action.action_type == ActionType.SEND_SEGMENTS
    assert sent_action.payload["segments"] == [
        {"type": "text", "data": {"text": "说明文字"}},
        {"type": "image", "data": {"file": str(artifact_path)}},
    ]


@pytest.mark.parametrize("status", ["unavailable", "error"])
async def test_outbox_render_falls_back_to_raw_text_when_injected_service_cannot_render(
    status: str,
) -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    if status == "unavailable":
        result = RenderResult.unavailable(error="backend unavailable")
    else:
        result = RenderResult.error_result(
            backend_name="playwright",
            error="render exploded",
        )
    render_service = FakeRenderService(result)
    outbox = Outbox(
        gateway=gateway,
        store=store,
        render_service=render_service,
    )
    ctx = _send_intent_context(
        render="# Title\n\n$E=mc^2$",
        thread_content="# Title\n\n$E=mc^2$",
    )

    report = await outbox.dispatch(ctx)

    assert report.has_failures is False
    assert len(render_service.calls) == 1
    sent_action = gateway.sent[0]
    assert sent_action.action_type == ActionType.SEND_SEGMENTS
    assert sent_action.payload["segments"] == [
        {"type": "text", "data": {"text": "# Title\n\n$E=mc^2$"}}
    ]


async def test_outbox_persists_cross_session_delivery_to_destination() -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    ltm = RecordingIngestor()
    outbox = Outbox(gateway=gateway, store=store, long_term_memory_ingestor=ltm)
    ctx = _send_intent_context(
        text="cross-session hello",
        target="qq:group:20002",
        thread_content="cross-session hello",
    )

    report = await outbox.dispatch(ctx)

    assert report.has_failures is False
    delivered_item = report.delivered_items[0]
    assert delivered_item.origin_thread_id == "qq:user:10001"
    assert delivered_item.destination_thread_id == "qq:group:20002"
    assert delivered_item.destination_conversation_id == "qq:group:20002"
    assert delivered_item.append_to_origin_thread is False
    assert store.saved[0].thread_id == "qq:group:20002"
    assert store.saved[0].metadata["channel_scope"] == "qq:group:20002"
    assert ltm.marked_threads == ["qq:group:20002"]


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
