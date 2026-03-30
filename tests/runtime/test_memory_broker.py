from acabot.runtime import (
    ContextDecision,
    MemoryAssemblySpec,
    MemoryBlock,
    MemoryBroker,
    MemorySourceFailure,
    MemorySourcePolicy,
    RunContext,
)
from acabot.runtime.memory.long_term_memory.contracts import MemoryEntry, MemoryProvenance
from acabot.runtime.memory.long_term_memory.source import CoreSimpleMemMemorySource
from acabot.runtime.memory.long_term_memory.storage import LanceDbLongTermMemoryStore
from acabot.runtime.contracts import (
    ResolvedAgent,
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
                content="用户喜欢简洁回答",
                source="test_source",
                scope="user",
                source_ids=["memory:1"],
                assembly=MemoryAssemblySpec(
                    target_slot="message_prefix",
                    priority=300,
                ),
            )
        ]


class FlakyRetriever:
    async def __call__(self, request):
        _ = request
        raise RuntimeError("boom")


class MalformedBlockRetriever:
    async def __call__(self, request):
        _ = request
        return [None]


def _registry(*items) -> object:
    from acabot.runtime import MemorySourceRegistry

    registry = MemorySourceRegistry()
    for source_id, source in items:
        registry.register(source_id, source)
    return registry


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
                "event_tags": ["notice", "poke"],
            },
        ),
        thread=ThreadState(
            thread_id="qq:group:20002",
            channel_scope="qq:group:20002",
            working_messages=[{"role": "user", "content": "[acacia/10001] [notice:poke]"}],
            working_summary="群里最近在讨论机器人设定",
            last_event_at=123,
        ),
        agent=ResolvedAgent(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
        ),
        retrieval_plan=RetrievalPlan(
            retained_history=[{"role": "user", "content": "[acacia/10001] [notice:poke]"}],
            working_summary="群里最近在讨论机器人设定",
        ),
    )


async def test_memory_broker_builds_retrieval_request_from_context() -> None:
    retriever = RecordingRetriever()
    broker = MemoryBroker(registry=_registry(("retriever:0", retriever)))
    ctx = _ctx()

    result = await broker.retrieve(ctx)

    assert result.blocks[0].source == "test_source"
    assert result.blocks[0].assembly.target_slot == "message_prefix"
    assert result.failures == []
    request = retriever.calls[0]
    assert request.event_id == "evt-1"
    assert request.event_type == "poke"
    assert request.event_timestamp == 123
    assert request.thread_id == "qq:group:20002"
    assert request.actor_id == "qq:user:10001"
    assert request.channel_scope == "qq:group:20002"
    assert request.working_summary == "群里最近在讨论机器人设定"
    assert request.retained_history == [{"role": "user", "content": "[acacia/10001] [notice:poke]"}]
    assert request.event_tags == ["notice", "poke"]
    assert request.metadata["event_policy_id"] == "poke-memory"
    assert request.metadata["sticky_note_targets"] == []

async def test_memory_broker_passes_context_retrieval_tags() -> None:
    retriever = RecordingRetriever()
    broker = MemoryBroker(registry=_registry(("retriever:0", retriever)))
    ctx = _ctx()
    ctx.retrieval_plan = None
    ctx.context_decision = ContextDecision(retrieval_tags=["urgent", "project"])

    await broker.retrieve(ctx)

    request = retriever.calls[0]
    assert request.requested_tags == ["urgent", "project"]


async def test_memory_broker_collects_source_failures_without_blocking_other_results() -> None:
    broker = MemoryBroker(
        registry=_registry(
            ("retriever:0", RecordingRetriever()),
            ("retriever:1", FlakyRetriever()),
        ),
    )
    ctx = _ctx()

    result = await broker.retrieve(ctx)

    assert [block.source for block in result.blocks] == ["test_source"]
    assert result.failures == [
        MemorySourceFailure(source="retriever:1", error="boom")
    ]


async def test_memory_broker_isolates_malformed_block_output_from_other_sources() -> None:
    broker = MemoryBroker(
        registry=_registry(
            ("retriever:0", RecordingRetriever()),
            ("retriever:1", MalformedBlockRetriever()),
        ),
    )
    ctx = _ctx()

    result = await broker.retrieve(ctx)

    assert [block.source for block in result.blocks] == ["test_source"]
    assert result.failures == [
        MemorySourceFailure(
            source="retriever:1",
            error="source returned non-MemoryBlock item: NoneType",
        )
    ]


async def test_memory_broker_uses_retrieval_plan_fields_as_shared_request_shape() -> None:
    retriever = RecordingRetriever()
    broker = MemoryBroker(registry=_registry(("retriever:0", retriever)))
    ctx = _ctx()
    ctx.thread.working_summary = "thread summary should not leak"
    ctx.metadata["effective_working_summary"] = "effective summary should not leak"
    ctx.metadata["effective_compacted_messages"] = [{"role": "user", "content": "older"}]
    ctx.context_decision = ContextDecision(retrieval_tags=["urgent"])
    ctx.retrieval_plan = RetrievalPlan(
        requested_tags=[],
        sticky_note_targets=[],
        retained_history=[],
        working_summary="",
    )

    await broker.retrieve(ctx)

    request = retriever.calls[0]
    assert request.requested_tags == []
    assert request.retained_history == []
    assert request.working_summary == ""
    assert request.metadata["sticky_note_targets"] == []


async def test_memory_broker_respects_explicit_empty_allowed_target_slots() -> None:
    retriever = RecordingRetriever()
    broker = MemoryBroker(
        registry=_registry(("retriever:0", retriever)),
        policies={"retriever:0": MemorySourcePolicy(allowed_target_slots=[])},
    )
    ctx = _ctx()

    result = await broker.retrieve(ctx)

    assert result.blocks == []
    assert result.failures == [
        MemorySourceFailure(
            source="retriever:0",
            error="invalid target_slot: message_prefix",
        )
    ]


def test_runtime_facade_only_exports_memory_source_contracts() -> None:
    import acabot.runtime as runtime

    assert hasattr(runtime, "MemorySource")
    assert not hasattr(runtime, "MemoryRetriever")
    assert not hasattr(runtime, "NullMemoryRetriever")


async def test_memory_broker_accepts_long_term_memory_source_without_special_case(tmp_path) -> None:
    class StaticPlanner:
        async def plan_query(self, request_payload):
            _ = request_payload
            return {
                "semantic_queries": [],
                "lexical_queries": ["latte"],
                "symbolic_filters": {"persons": ["Alice"]},
            }

    class NullEmbeddingClient:
        async def embed_texts(self, texts):
            _ = texts
            return []

    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    store.upsert_entries(
        [
            MemoryEntry(
                entry_id="entry-1",
                conversation_id="qq:group:20002",
                created_at=100,
                updated_at=100,
                extractor_version="ltm-v1",
                topic="咖啡偏好",
                lossless_restatement="Alice 喜欢拿铁。",
                keywords=["latte"],
                persons=["Alice"],
                provenance=MemoryProvenance(fact_ids=["e:evt-1"]),
            )
        ]
    )
    broker = MemoryBroker(
        registry=_registry(
            (
                "long_term_memory",
                CoreSimpleMemMemorySource(
                    store=store,
                    query_planner=StaticPlanner(),
                    embedding_client=NullEmbeddingClient(),
                ),
            )
        )
    )
    ctx = _ctx()

    result = await broker.retrieve(ctx)

    assert len(result.blocks) == 1
    assert result.blocks[0].source == "long_term_memory"
    assert "咖啡偏好" in result.blocks[0].content
