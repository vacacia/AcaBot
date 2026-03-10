from acabot.runtime import MessageStore, MessageRecord, Outbox, OutboxItem, PlannedAction
from acabot.types import Action, ActionType, EventSource


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
