from acabot.runtime import RuntimeRouter
from acabot.types import EventSource, MsgSegment, StandardEvent


def _event(*, message_type: str, user_id: str, group_id: str | None = None) -> StandardEvent:
    return StandardEvent(
        event_id="evt-1",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type=message_type,
            user_id=user_id,
            group_id=group_id,
        ),
        segments=[MsgSegment(type="text", data={"text": "hello"})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role=None,
    )


async def test_runtime_router_routes_private_event() -> None:
    router = RuntimeRouter(default_agent_id="aca")
    decision = await router.route(_event(message_type="private", user_id="10001"))

    assert decision.thread_id == "qq:user:10001"
    assert decision.channel_scope == "qq:user:10001"
    assert decision.actor_id == "qq:user:10001"
    assert decision.agent_id == "aca"
    assert decision.run_mode == "respond"


async def test_runtime_router_routes_group_event() -> None:
    router = RuntimeRouter(default_agent_id="aca")
    decision = await router.route(
        _event(message_type="group", user_id="10001", group_id="20002")
    )

    assert decision.thread_id == "qq:group:20002"
    assert decision.channel_scope == "qq:group:20002"
    assert decision.actor_id == "qq:user:10001"
