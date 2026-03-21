from acabot.runtime import (
    AdmissionDecision,
    AdmissionDomainConfig,
    ComputerPolicyDecision,
    EventFacts,
    MatchSpec,
    RoutingDecision,
    RoutingDomainConfig,
    SessionConfig,
    SurfaceConfig,
)


def test_match_spec_specificity_counts_declared_fields() -> None:
    spec = MatchSpec(scene="group", mentions_self=True, sender_roles=["admin"])

    assert spec.specificity() == 3


def test_match_spec_matches_event_facts() -> None:
    facts = EventFacts(
        platform="qq",
        event_kind="message",
        scene="group",
        actor_id="qq:user:1",
        channel_scope="qq:group:123",
        thread_id="qq:group:123",
        mentions_self=True,
        sender_roles=["admin"],
    )

    assert MatchSpec(scene="group", mentions_self=True).matches(facts)
    assert MatchSpec(sender_roles=["admin"]).matches(facts)
    assert not MatchSpec(sender_roles=["member"]).matches(facts)


def test_surface_config_keeps_domain_defaults_and_cases() -> None:
    session = SessionConfig(
        session_id="qq:group:123",
        template_id="qq_group",
        surfaces={
            "message.mention": SurfaceConfig(
                routing=RoutingDomainConfig(
                    default={"profile": "aca.default"},
                    cases=[],
                ),
                admission=AdmissionDomainConfig(
                    default={"mode": "respond"},
                    cases=[],
                ),
            )
        },
    )

    surface = session.surfaces["message.mention"]

    assert surface.routing is not None
    assert surface.routing.default["profile"] == "aca.default"
    assert surface.admission is not None
    assert surface.admission.default["mode"] == "respond"


def test_decision_objects_keep_reason_and_case_identity() -> None:
    routing = RoutingDecision(
        actor_lane="frontstage",
        profile_id="aca.qq.group.default",
        reason="surface default",
        source_case_id="",
        priority=100,
        specificity=1,
    )
    computer = ComputerPolicyDecision(
        actor_kind="frontstage_agent",
        backend="docker",
        allow_exec=True,
        allow_sessions=True,
        roots={
            "workspace": {"visible": True, "writable": True},
            "skills": {"visible": True, "writable": False},
            "self": {"visible": True, "writable": True},
        },
        visible_skills=["sample_skill"],
        notes=["default surface policy"],
    )
    admission = AdmissionDecision(
        mode="respond",
        reason="surface default",
        source_case_id="reply_messages",
        priority=100,
        specificity=2,
    )

    assert routing.profile_id == "aca.qq.group.default"
    assert computer.roots["skills"]["writable"] is False
    assert admission.source_case_id == "reply_messages"
