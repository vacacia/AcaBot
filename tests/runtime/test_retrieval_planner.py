from dataclasses import asdict

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


def test_retrieval_planner_returns_current_plan_shape() -> None:
    planner = RetrievalPlanner()
    plan = planner.prepare(_ctx())

    assert asdict(plan) == {
        "requested_tags": [],
        "sticky_note_targets": [],
        "retained_history": [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "u3"},
        ],
        "dropped_messages": [],
        "working_summary": "",
        "metadata": {
            "history_before": 5,
            "history_after": 5,
            "dropped_count": 0,
            "summary_present": False,
            "token_stats": {},
            "context_labels": [],
        },
    }


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

def test_extraction_decision_has_current_runtime_shape() -> None:
    decision = ExtractionDecision()

    assert asdict(decision) == {
        "tags": [],
        "reason": "",
        "source_case_id": "",
        "priority": 100,
        "specificity": 0,
    }


def test_retrieval_planner_keeps_context_labels_in_metadata() -> None:
    planner = RetrievalPlanner()
    ctx = _ctx()
    ctx.context_decision = ContextDecision(
        context_labels=["admin_message", "high_priority"],
    )
    plan = planner.prepare(ctx)

    assert plan.metadata["context_labels"] == ["admin_message", "high_priority"]

def test_retrieval_planner_keeps_sticky_note_targets_from_context() -> None:
    planner = RetrievalPlanner()
    ctx = _ctx()
    ctx.context_decision = ContextDecision(
        sticky_note_targets=["qq:user:10001", "qq:group:20002"],
    )
    plan = planner.prepare(ctx)

    assert plan.sticky_note_targets == ["qq:user:10001", "qq:group:20002"]
