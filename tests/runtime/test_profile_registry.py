from acabot.runtime import AgentProfile, AgentProfileRegistry, BindingRule, RouteDecision
from acabot.types import EventSource, MsgSegment, StandardEvent


def _profiles() -> dict[str, AgentProfile]:
    return {
        "aca": AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/aca",
            default_model="model-a",
        ),
        "group": AgentProfile(
            agent_id="group",
            name="Group",
            prompt_ref="prompt/group",
            default_model="model-g",
        ),
        "ops": AgentProfile(
            agent_id="ops",
            name="Ops",
            prompt_ref="prompt/ops",
            default_model="model-o",
        ),
        "vip": AgentProfile(
            agent_id="vip",
            name="Vip",
            prompt_ref="prompt/vip",
            default_model="model-v",
        ),
    }


def _event(
    *,
    message_type: str,
    user_id: str,
    group_id: str | None = None,
    sender_role: str | None = None,
) -> StandardEvent:
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
        sender_role=sender_role,
    )


def test_registry_uses_highest_priority_rule() -> None:
    registry = AgentProfileRegistry(
        profiles=_profiles(),
        default_agent_id="aca",
        rules=[
            BindingRule(
                rule_id="group-default",
                agent_id="group",
                priority=40,
                channel_scope="qq:group:20002",
            ),
            BindingRule(
                rule_id="vip-user",
                agent_id="vip",
                priority=60,
                actor_id="qq:user:10001",
            ),
            BindingRule(
                rule_id="vip-in-group",
                agent_id="ops",
                priority=80,
                actor_id="qq:user:10001",
                channel_scope="qq:group:20002",
            ),
        ],
    )

    agent_id, metadata = registry.resolve_agent(
        event=_event(message_type="group", user_id="10001", group_id="20002"),
        thread_id="qq:group:20002",
        actor_id="qq:user:10001",
        channel_scope="qq:group:20002",
    )

    assert agent_id == "ops"
    assert metadata["binding_kind"] == "rule"
    assert metadata["binding_rule_id"] == "vip-in-group"


def test_registry_uses_specificity_to_break_priority_ties() -> None:
    registry = AgentProfileRegistry(
        profiles=_profiles(),
        default_agent_id="aca",
        rules=[
            BindingRule(
                rule_id="vip-user",
                agent_id="vip",
                priority=60,
                actor_id="qq:user:10001",
            ),
            BindingRule(
                rule_id="vip-user-in-group",
                agent_id="ops",
                priority=60,
                actor_id="qq:user:10001",
                channel_scope="qq:group:20002",
            ),
        ],
    )

    agent_id, metadata = registry.resolve_agent(
        event=_event(message_type="group", user_id="10001", group_id="20002"),
        thread_id="qq:group:20002",
        actor_id="qq:user:10001",
        channel_scope="qq:group:20002",
    )

    assert agent_id == "ops"
    assert metadata["binding_match_keys"] == ["actor_id", "channel_scope"]


def test_registry_supports_sender_role_rules() -> None:
    registry = AgentProfileRegistry(
        profiles=_profiles(),
        default_agent_id="aca",
        rules=[
            BindingRule(
                rule_id="group-default",
                agent_id="group",
                priority=40,
                channel_scope="qq:group:20002",
            ),
            BindingRule(
                rule_id="group-admins",
                agent_id="ops",
                priority=70,
                channel_scope="qq:group:20002",
                sender_roles=["admin", "owner"],
            ),
        ],
    )

    agent_id, metadata = registry.resolve_agent(
        event=_event(
            message_type="group",
            user_id="10001",
            group_id="20002",
            sender_role="admin",
        ),
        thread_id="qq:group:20002",
        actor_id="qq:user:10001",
        channel_scope="qq:group:20002",
    )

    assert agent_id == "ops"
    assert metadata["binding_rule_id"] == "group-admins"


def test_registry_falls_back_to_default_agent() -> None:
    registry = AgentProfileRegistry(
        profiles=_profiles(),
        default_agent_id="aca",
    )

    agent_id, metadata = registry.resolve_agent(
        event=_event(message_type="group", user_id="88888", group_id="99999"),
        thread_id="qq:group:99999",
        actor_id="qq:user:88888",
        channel_scope="qq:group:99999",
    )

    assert agent_id == "aca"
    assert metadata["binding_kind"] == "default"


def test_registry_loads_profile_from_route_decision() -> None:
    registry = AgentProfileRegistry(
        profiles=_profiles(),
        default_agent_id="aca",
    )
    decision = RouteDecision(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="vip",
        channel_scope="qq:user:10001",
    )

    profile = registry.load(decision)

    assert profile.agent_id == "vip"
