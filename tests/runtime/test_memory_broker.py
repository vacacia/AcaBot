from acabot.runtime import MemoryBlock, MemoryBroker, RunContext
from acabot.runtime.models import AgentProfile, RouteDecision, RunRecord, ThreadState
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
    assert request.requested_scopes == ["episodic", "relationship"]
    assert request.event_tags == ["notice", "poke"]
    assert request.metadata["event_policy_id"] == "poke-memory"


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
