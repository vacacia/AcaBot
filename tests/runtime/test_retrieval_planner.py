from acabot.runtime import (
    AgentProfile,
    ContextDecision,
    ExtractionDecision,
    RetrievalPlanner,
    RouteDecision,
    RunContext,
)
from acabot.runtime.contracts import RunRecord, ThreadState
from acabot.types import EventSource, MsgSegment, StandardEvent


def _ctx() -> RunContext:
    event = StandardEvent(
        event_id="evt-1",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        segments=[MsgSegment(type="text", data={"text": "hello"})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role="member",
    )
    return RunContext(
        run=RunRecord(
            run_id="run:1",
            thread_id="qq:group:20002",
            actor_id="qq:user:10001",
            agent_id="aca",
            trigger_event_id="evt-1",
            status="queued",
            started_at=123,
        ),
        event=event,
        decision=RouteDecision(
            thread_id="qq:group:20002",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:group:20002",
        ),
        thread=ThreadState(
            thread_id="qq:group:20002",
            channel_scope="qq:group:20002",
            working_messages=[
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
                {"role": "assistant", "content": "a2"},
                {"role": "user", "content": "u3"},
            ],
            working_summary="",
            last_event_at=123,
        ),
        profile=AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            default_model="test-model",
        ),
    )


def test_retrieval_planner_defaults_keep_requested_scopes_only() -> None:
    planner = RetrievalPlanner()
    plan = planner.prepare(_ctx())

    assert plan.requested_scopes == ["relationship", "user", "channel", "global"]
    assert plan.requested_tags == []


def test_retrieval_planner_prepare_keeps_summary_and_retained_history() -> None:
    planner = RetrievalPlanner()
    ctx = _ctx()
    ctx.metadata["effective_compacted_messages"] = [
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]
    ctx.metadata["effective_working_summary"] = "summary"

    plan = planner.prepare(ctx)

    assert plan.retained_history[-1]["content"] == "u3"
    assert plan.working_summary == "summary"
    assert not hasattr(planner, "assemble")



def test_retrieval_planner_uses_typed_extraction_decision_scopes() -> None:
    planner = RetrievalPlanner()
    ctx = _ctx()
    ctx.extraction_decision = ExtractionDecision(
        extract_to_memory=True,
        memory_scopes=["channel"],
        tags=["project"],
    )
    ctx.decision.metadata.clear()

    plan = planner.prepare(ctx)

    assert plan.requested_scopes == ["channel"]
    assert plan.requested_tags == []


def test_retrieval_planner_does_not_widen_invalid_legacy_scope_values() -> None:
    planner = RetrievalPlanner()
    ctx = _ctx()
    ctx.extraction_decision = ExtractionDecision(
        extract_to_memory=True,
        memory_scopes=["episodic"],
        tags=[],
    )
    ctx.decision.metadata.clear()

    plan = planner.prepare(ctx)

    assert plan.requested_scopes == []


def test_retrieval_planner_keeps_context_labels_in_metadata() -> None:
    planner = RetrievalPlanner()
    ctx = _ctx()
    ctx.context_decision = ContextDecision(
        context_labels=["admin_message", "high_priority"],
    )
    plan = planner.prepare(ctx)

    assert plan.metadata["context_labels"] == ["admin_message", "high_priority"]

def test_retrieval_planner_filters_sticky_note_scopes_from_context() -> None:
    planner = RetrievalPlanner()
    ctx = _ctx()
    ctx.context_decision = ContextDecision(sticky_note_scopes=["user"])
    plan = planner.prepare(ctx)

    assert plan.sticky_note_scopes == ["user"]
