from acabot.runtime import (
    AgentProfile,
    ContextDecision,
    ExtractionDecision,
    MemoryBlock,
    PromptAssemblyConfig,
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


def test_retrieval_planner_defaults_do_not_auto_pull_reference() -> None:
    planner = RetrievalPlanner(PromptAssemblyConfig())
    plan = planner.prepare(_ctx())

    assert "reference" not in plan.requested_memory_types
    assert "sticky_note" in plan.requested_memory_types
    assert plan.requested_scopes == ["relationship", "user", "channel", "global"]


def test_retrieval_planner_assembles_sticky_and_retrieval_slots() -> None:
    planner = RetrievalPlanner(PromptAssemblyConfig())
    ctx = _ctx()
    ctx.retrieval_plan = planner.prepare(ctx)
    ctx.thread.working_summary = "群里最近在讨论实习材料"

    messages = planner.assemble(
        ctx,
        memory_blocks=[
            MemoryBlock(
                title="Sticky",
                content="十个月实习只需要成果鉴定",
                scope="channel",
                metadata={"memory_type": "sticky_note", "edit_mode": "readonly"},
            ),
            MemoryBlock(
                title="Episodic",
                content="用户最近一直在追问流程",
                scope="relationship",
                metadata={"memory_type": "episodic", "edit_mode": "draft"},
            ),
        ],
    )

    assert [slot.slot_type for slot in ctx.prompt_slots] == [
        "sticky_notes",
        "thread_summary",
        "retrieved_memory",
    ]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "十个月实习只需要成果鉴定" in str(messages[0]["content"])
    assert "<summary>" in str(messages[1]["content"])
    assert "群里最近在讨论实习材料" in str(messages[1]["content"])
    assert "Episodic" in str(messages[2]["content"])


def test_retrieval_planner_allows_custom_slot_message_roles() -> None:
    planner = RetrievalPlanner(
        PromptAssemblyConfig(
            sticky_message_role="user",
            summary_message_role="system",
            retrieval_message_role="user",
        )
    )
    ctx = _ctx()
    ctx.retrieval_plan = planner.prepare(ctx)
    ctx.thread.working_summary = "summary"

    messages = planner.assemble(
        ctx,
        memory_blocks=[
            MemoryBlock(
                title="Sticky",
                content="sticky content",
                scope="channel",
                metadata={"memory_type": "sticky_note", "edit_mode": "readonly"},
            ),
            MemoryBlock(
                title="Retrieved",
                content="retrieved content",
                scope="relationship",
                metadata={"memory_type": "episodic", "edit_mode": "draft"},
            ),
        ],
    )

    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "system"
    assert messages[2]["role"] == "user"


def test_retrieval_planner_never_injects_skill_guides() -> None:
    planner = RetrievalPlanner(PromptAssemblyConfig())
    ctx = _ctx()
    ctx.retrieval_plan = planner.prepare(ctx)

    messages = planner.assemble(ctx, memory_blocks=[])

    assert ctx.prompt_slots == []
    assert messages == list(ctx.thread.working_messages)



def test_retrieval_planner_uses_typed_extraction_decision_scopes() -> None:
    planner = RetrievalPlanner(PromptAssemblyConfig())
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



def test_retrieval_planner_applies_context_labels_and_prompt_slots() -> None:
    planner = RetrievalPlanner(PromptAssemblyConfig())
    ctx = _ctx()
    ctx.context_decision = ContextDecision(
        context_labels=["admin_message", "high_priority"],
        prompt_slots=[
            {
                "slot_id": "slot:session-note",
                "slot_type": "session_context",
                "title": "Session Note",
                "content": "请优先给出执行步骤。",
                "position": "system_message",
                "message_role": "system",
                "stable": True,
            }
        ],
    )
    ctx.retrieval_plan = planner.prepare(ctx)

    messages = planner.assemble(ctx, memory_blocks=[])

    assert [slot.slot_type for slot in ctx.prompt_slots] == ["context_labels", "session_context"]
    assert "admin_message" in str(messages[0]["content"])
    assert "请优先给出执行步骤。" in str(messages[1]["content"])



def test_retrieval_planner_filters_sticky_notes_by_context_scope() -> None:
    planner = RetrievalPlanner(PromptAssemblyConfig())
    ctx = _ctx()
    ctx.context_decision = ContextDecision(sticky_note_scopes=["user"])
    ctx.retrieval_plan = planner.prepare(ctx)

    messages = planner.assemble(
        ctx,
        memory_blocks=[
            MemoryBlock(
                title="User Sticky",
                content="用户更喜欢短回答",
                scope="user",
                metadata={"memory_type": "sticky_note", "edit_mode": "readonly"},
            ),
            MemoryBlock(
                title="Channel Sticky",
                content="本群正在讨论项目排期",
                scope="channel",
                metadata={"memory_type": "sticky_note", "edit_mode": "readonly"},
            ),
        ],
    )

    assert ctx.prompt_slots[0].slot_type == "sticky_notes"
    assert "用户更喜欢短回答" in str(messages[0]["content"])
    assert "本群正在讨论项目排期" not in str(messages[0]["content"])
