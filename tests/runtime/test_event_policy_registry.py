from acabot.runtime import EventPolicy, EventPolicyRegistry
from acabot.types import EventSource, MsgSegment, StandardEvent


def _event(
    *,
    event_type: str = "message",
    message_type: str,
    user_id: str,
    group_id: str | None = None,
    sender_role: str | None = None,
) -> StandardEvent:
    return StandardEvent(
        event_id="evt-1",
        event_type=event_type,
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type=message_type,
            user_id=user_id,
            group_id=group_id,
        ),
        segments=[MsgSegment(type="text", data={"text": "hello"})] if event_type == "message" else [],
        raw_message_id="msg-1" if event_type == "message" else "",
        sender_nickname="acacia",
        sender_role=sender_role,
    )


def test_event_policy_registry_resolves_memory_hints() -> None:
    registry = EventPolicyRegistry(
        [
            EventPolicy(
                policy_id="group-poke",
                priority=80,
                platform="qq",
                event_type="poke",
                channel_scope="qq:group:20002",
                persist_event=True,
                extract_to_memory=True,
                memory_scopes=["episodic", "relationship"],
                tags=["notice", "poke"],
            )
        ]
    )

    decision = registry.resolve(
        event=_event(
            event_type="poke",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        actor_id="qq:user:10001",
        channel_scope="qq:group:20002",
    )

    assert decision.policy_id == "group-poke"
    assert decision.extract_to_memory is True
    assert decision.memory_scopes == ["episodic", "relationship"]
    assert decision.tags == ["notice", "poke"]


def test_event_policy_registry_rejects_ambiguous_policies() -> None:
    registry = EventPolicyRegistry()
    registry.add_policy(
        EventPolicy(
            policy_id="poke-a",
            priority=60,
            platform="qq",
            event_type="poke",
            channel_scope="qq:group:20002",
        )
    )

    try:
        registry.add_policy(
            EventPolicy(
                policy_id="poke-b",
                priority=60,
                platform="qq",
                event_type="poke",
                channel_scope="qq:group:20002",
            )
        )
    except ValueError as exc:
        assert "Ambiguous event policies" in str(exc)
        return

    raise AssertionError("Expected ambiguous event policies to raise ValueError")
