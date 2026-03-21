from acabot.runtime import ContextDecision, ExtractionDecision, MemoryBlock, MemoryBroker, RunContext
from acabot.runtime.contracts import (
    AgentProfile,
    MemoryCandidate,
    MessageProjection,
    RetrievalPlan,
    RouteDecision,
    RunRecord,
    ThreadState,
)
from acabot.types import EventSource, MsgSegment, StandardEvent


class RecordingRetriever:
    def __init__(self) -> None:
        self.calls = []

    async def __call__(self, request):
        self.calls.append(request)
        return [
            MemoryBlock(
                title="User Profile",
                content="用户喜欢简洁回答",
                scope="user",
                source_ids=["memory:1"],
            )
        ]


class RecordingExtractor:
    def __init__(self) -> None:
        self.calls = []

    async def __call__(self, request) -> None:
        self.calls.append(request)


def _ctx() -> RunContext:
    event = StandardEvent(
        event_id="evt-1",
        event_type="poke",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        segments=[],
        raw_message_id="",
        sender_nickname="acacia",
        sender_role="member",
        operator_id="10001",
    )
    return RunContext(
        run=RunRecord(
            run_id="run:1",
            thread_id="qq:group:20002",
            actor_id="qq:user:10001",
            agent_id="aca",
            trigger_event_id="evt-1",
            status="completed",
            started_at=123,
        ),
        event=event,
        decision=RouteDecision(
            thread_id="qq:group:20002",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:group:20002",
            metadata={
                "event_policy_id": "poke-memory",
                "event_memory_scopes": ["episodic", "relationship"],
                "event_tags": ["notice", "poke"],
                "event_extract_to_memory": True,
            },
        ),
        thread=ThreadState(
            thread_id="qq:group:20002",
            channel_scope="qq:group:20002",
            working_messages=[{"role": "user", "content": "[acacia/10001] [notice:poke]"}],
            working_summary="群里最近在讨论机器人设定",
            last_event_at=123,
        ),
        profile=AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            default_model="test-model",
        ),
        retrieval_plan=RetrievalPlan(
            requested_scopes=["relationship", "user"],
            requested_memory_types=["sticky_note", "episodic"],
            compressed_messages=[{"role": "user", "content": "[acacia/10001] [notice:poke]"}],
        ),
    )


async def test_memory_broker_builds_retrieval_request_from_context() -> None:
    retriever = RecordingRetriever()
    broker = MemoryBroker(retriever=retriever)
    ctx = _ctx()

    blocks = await broker.retrieve(ctx)

    assert blocks[0].title == "User Profile"
    request = retriever.calls[0]
    assert request.event_id == "evt-1"
    assert request.event_type == "poke"
    assert request.event_timestamp == 123
    assert request.requested_scopes == ["relationship", "user"]
    assert request.requested_memory_types == ["sticky_note", "episodic"]
    assert request.event_tags == ["notice", "poke"]
    assert request.metadata["event_policy_id"] == "poke-memory"
    assert request.metadata["prompt_slot_count"] == 0


async def test_memory_broker_builds_write_request_from_context() -> None:
    extractor = RecordingExtractor()
    broker = MemoryBroker(extractor=extractor)
    ctx = _ctx()
    ctx.delivery_report = None

    await broker.extract_after_run(ctx)

    request = extractor.calls[0]
    assert request.event_id == "evt-1"
    assert request.run_status == "completed"
    assert request.event_timestamp == 123
    assert request.user_content == "[acacia/10001] [notice:poke]"
    assert request.requested_scopes == ["episodic", "relationship"]
    assert request.metadata["extract_to_memory"] is True


async def test_memory_broker_prefers_memory_user_content_override() -> None:
    extractor = RecordingExtractor()
    broker = MemoryBroker(extractor=extractor)
    ctx = _ctx()
    ctx.memory_user_content = "[acacia/10001] [notice:poke] [图片说明: 一张群聊截图]"

    await broker.extract_after_run(ctx)

    request = extractor.calls[0]
    assert request.user_content == "[acacia/10001] [notice:poke] [图片说明: 一张群聊截图]"


async def test_memory_broker_passes_context_retrieval_tags() -> None:
    retriever = RecordingRetriever()
    broker = MemoryBroker(retriever=retriever)
    ctx = _ctx()
    ctx.context_decision = ContextDecision(retrieval_tags=["urgent", "project"])

    await broker.retrieve(ctx)

    request = retriever.calls[0]
    assert request.requested_tags == ["urgent", "project"]


async def test_memory_broker_prefers_typed_extraction_decision() -> None:
    extractor = RecordingExtractor()
    broker = MemoryBroker(extractor=extractor)
    ctx = _ctx()
    ctx.decision.metadata.clear()
    ctx.extraction_decision = ExtractionDecision(
        extract_to_memory=True,
        memory_scopes=["channel"],
        tags=["typed", "project"],
    )

    await broker.extract_after_run(ctx)

    request = extractor.calls[0]
    assert request.requested_scopes == ["channel"]
    assert request.event_tags == ["typed", "project"]
    assert request.metadata["extract_to_memory"] is True


async def test_memory_broker_formats_message_projection_candidates() -> None:
    extractor = RecordingExtractor()
    broker = MemoryBroker(extractor=extractor)
    ctx = _ctx()
    ctx.message_projection = MessageProjection(
        history_text="[acacia/10001] 请看图 [系统补充-图片说明: 一只橘猫]",
        model_content="[acacia/10001] 请看图 [系统补充-图片说明: 一只橘猫]",
        memory_candidates=[
            MemoryCandidate(kind="base_text", text="[acacia/10001] 请看图"),
            MemoryCandidate(
                kind="image_caption",
                text="一只橘猫",
                generated=True,
                metadata={"label": "图片说明"},
            ),
        ],
    )

    await broker.extract_after_run(ctx)

    request = extractor.calls[0]
    assert request.user_content == "[acacia/10001] 请看图 [系统补充-图片说明: 一只橘猫]"
