from acabot.runtime import (
    AgentProfile,
    AgentProfileRegistry,
    BindingRule,
    EventPolicy,
    EventPolicyRegistry,
    InboundRule,
    InboundRuleRegistry,
    RuntimeRouter,
)
from acabot.types import EventSource, MsgSegment, StandardEvent


def _event(
    *,
    event_type: str = "message",
    message_type: str,
    user_id: str,
    group_id: str | None = None,
    sender_role: str | None = None,
    message_subtype: str | None = None,
    notice_type: str | None = None,
    notice_subtype: str | None = None,
    targets_self: bool = False,
    mentioned_everyone: bool = False,
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
        segments=[MsgSegment(type="text", data={"text": "hello"})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role=sender_role,
        message_subtype=message_subtype,
        notice_type=notice_type,
        notice_subtype=notice_subtype,
        targets_self=targets_self,
        mentioned_everyone=mentioned_everyone,
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


async def test_runtime_router_supports_inbound_run_mode_rules() -> None:
    inbound = InboundRuleRegistry(
        [
            InboundRule(
                rule_id="poke-ignore",
                run_mode="silent_drop",
                priority=90,
                platform="qq",
                event_type="poke",
                channel_scope="qq:group:20002",
            )
        ]
    )
    router = RuntimeRouter(
        default_agent_id="aca",
        decide_run_mode=inbound.resolve,
    )

    decision = await router.route(
        _event(
            event_type="poke",
            message_type="group",
            user_id="10001",
            group_id="20002",
        )
    )

    assert decision.run_mode == "silent_drop"
    assert decision.metadata["inbound_rule_id"] == "poke-ignore"
    assert decision.metadata["inbound_run_mode"] == "silent_drop"


async def test_runtime_router_supports_targets_self_inbound_rules() -> None:
    inbound = InboundRuleRegistry(
        [
            InboundRule(
                rule_id="group-directed-only",
                run_mode="record_only",
                priority=90,
                platform="qq",
                event_type="message",
                channel_scope="qq:group:20002",
                targets_self=True,
            )
        ]
    )
    router = RuntimeRouter(
        default_agent_id="aca",
        decide_run_mode=inbound.resolve,
    )

    decision = await router.route(
        _event(
            event_type="message",
            message_type="group",
            user_id="10001",
            group_id="20002",
            targets_self=True,
        )
    )

    assert decision.run_mode == "record_only"
    assert decision.metadata["inbound_match_keys"] == ["platform", "event_type", "channel_scope", "targets_self"]


async def test_runtime_router_merges_event_policy_metadata() -> None:
    policies = EventPolicyRegistry(
        [
            EventPolicy(
                policy_id="group-poke-memory",
                priority=70,
                platform="qq",
                event_type="poke",
                channel_scope="qq:group:20002",
                extract_to_memory=True,
                memory_scopes=["episodic"],
                tags=["notice"],
            )
        ]
    )
    router = RuntimeRouter(
        default_agent_id="aca",
        resolve_event_policy=policies.resolve,
    )

    decision = await router.route(
        _event(
            event_type="poke",
            message_type="group",
            user_id="10001",
            group_id="20002",
        )
    )

    assert decision.metadata["event_policy_id"] == "group-poke-memory"
    assert decision.metadata["event_extract_to_memory"] is True
    assert decision.metadata["event_memory_scopes"] == ["episodic"]
    assert decision.metadata["event_tags"] == ["notice"]


async def test_runtime_router_supports_notice_subtype_policy_rules() -> None:
    policies = EventPolicyRegistry(
        [
            EventPolicy(
                policy_id="group-join-approve",
                priority=70,
                platform="qq",
                event_type="member_join",
                notice_subtype="approve",
                channel_scope="qq:group:20002",
                extract_to_memory=True,
                memory_scopes=["relationship"],
            )
        ]
    )
    router = RuntimeRouter(
        default_agent_id="aca",
        resolve_event_policy=policies.resolve,
    )

    decision = await router.route(
        _event(
            event_type="member_join",
            message_type="group",
            user_id="10001",
            group_id="20002",
            notice_type="group_increase",
            notice_subtype="approve",
        )
    )

    assert decision.metadata["event_policy_id"] == "group-join-approve"
    assert decision.metadata["event_policy_match_keys"] == [
        "platform",
        "event_type",
        "notice_subtype",
        "channel_scope",
    ]
