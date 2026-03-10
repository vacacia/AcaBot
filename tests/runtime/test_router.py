from acabot.runtime import AgentProfile, AgentProfileRegistry, BindingRule, RuntimeRouter
from acabot.types import EventSource, MsgSegment, StandardEvent


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


async def test_runtime_router_routes_private_event() -> None:
    router = RuntimeRouter(default_agent_id="aca")
    decision = await router.route(_event(message_type="private", user_id="10001"))

    assert decision.thread_id == "qq:user:10001"
    assert decision.channel_scope == "qq:user:10001"
    assert decision.actor_id == "qq:user:10001"
    assert decision.agent_id == "aca"
    assert decision.metadata["binding_kind"] == "default"
    assert decision.run_mode == "respond"


async def test_runtime_router_routes_group_event() -> None:
    router = RuntimeRouter(default_agent_id="aca")
    decision = await router.route(
        _event(message_type="group", user_id="10001", group_id="20002")
    )

    assert decision.thread_id == "qq:group:20002"
    assert decision.channel_scope == "qq:group:20002"
    assert decision.actor_id == "qq:user:10001"
    assert decision.agent_id == "aca"


async def test_runtime_router_uses_profile_registry_bindings() -> None:
    registry = AgentProfileRegistry(
        profiles={
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
        },
        default_agent_id="aca",
        rules=[
            BindingRule(
                rule_id="group-default",
                agent_id="group",
                priority=40,
                channel_scope="qq:group:20002",
            )
        ],
    )
    router = RuntimeRouter(
        default_agent_id="aca",
        resolve_agent=registry.resolve_agent,
    )

    decision = await router.route(
        _event(message_type="group", user_id="10001", group_id="20002")
    )

    assert decision.agent_id == "group"
    assert decision.metadata["binding_rule_id"] == "group-default"
    assert decision.metadata["binding_match_keys"] == ["channel_scope"]


async def test_runtime_router_supports_role_based_rules() -> None:
    registry = AgentProfileRegistry(
        profiles={
            "aca": AgentProfile(
                agent_id="aca",
                name="Aca",
                prompt_ref="prompt/aca",
                default_model="model-a",
            ),
            "ops": AgentProfile(
                agent_id="ops",
                name="Ops",
                prompt_ref="prompt/ops",
                default_model="model-o",
            ),
        },
        default_agent_id="aca",
        rules=[
            BindingRule(
                rule_id="admins-in-group",
                agent_id="ops",
                priority=80,
                channel_scope="qq:group:20002",
                sender_roles=["admin", "owner"],
            )
        ],
    )
    router = RuntimeRouter(
        default_agent_id="aca",
        resolve_agent=registry.resolve_agent,
    )

    decision = await router.route(
        _event(
            message_type="group",
            user_id="10001",
            group_id="20002",
            sender_role="admin",
        )
    )

    assert decision.agent_id == "ops"
    assert decision.metadata["binding_rule_id"] == "admins-in-group"
