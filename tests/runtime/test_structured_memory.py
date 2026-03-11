from acabot.runtime import (
    InMemoryMemoryStore,
    MemoryItem,
    StoreBackedMemoryRetriever,
    StructuredMemoryExtractor,
)
from acabot.runtime.memory_broker import MemoryRetrievalRequest, MemoryWriteRequest


def _retrieval_request() -> MemoryRetrievalRequest:
    return MemoryRetrievalRequest(
        run_id="run:1",
        thread_id="qq:group:20002",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:group:20002",
        event_id="evt-1",
        event_type="message",
        event_timestamp=123,
        query_text="你好",
        working_summary="群里最近在讨论机器人",
        requested_scopes=["episodic", "relationship"],
        event_tags=["chat"],
        metadata={},
    )


def _write_request() -> MemoryWriteRequest:
    return MemoryWriteRequest(
        run_id="run:1",
        thread_id="qq:group:20002",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:group:20002",
        event_id="evt-1",
        event_type="message",
        event_timestamp=123,
        run_mode="respond",
        run_status="completed",
        user_content="[acacia/10001] 你好",
        delivered_messages=["你好, 今天继续讨论 agent 架构"],
        requested_scopes=["episodic", "relationship"],
        event_tags=["chat"],
        metadata={
            "extract_to_memory": True,
            "thread_summary": "群里最近在讨论机器人",
            "event_policy_id": "message-memory",
        },
    )


async def test_structured_memory_extractor_persists_draft_episodic_item() -> None:
    store = InMemoryMemoryStore()
    extractor = StructuredMemoryExtractor(store)

    await extractor(_write_request())

    items = await store.find(
        scope="relationship",
        scope_key="qq:user:10001|qq:group:20002",
    )

    assert len(items) == 1
    assert items[0].memory_type == "episodic"
    assert items[0].edit_mode == "draft"
    assert items[0].source_run_id == "run:1"
    assert items[0].source_event_id == "evt-1"
    assert "assistant_1: 你好, 今天继续讨论 agent 架构" in items[0].content


async def test_structured_memory_extractor_skips_when_event_policy_disables_it() -> None:
    store = InMemoryMemoryStore()
    extractor = StructuredMemoryExtractor(store)
    request = _write_request()
    request.metadata["extract_to_memory"] = False

    await extractor(request)

    items = await store.find(
        scope="relationship",
        scope_key="qq:user:10001|qq:group:20002",
    )
    assert items == []


async def test_store_backed_memory_retriever_converts_memory_items_to_blocks() -> None:
    store = InMemoryMemoryStore()
    await store.upsert(
        MemoryItem(
            memory_id="memory:1",
            scope="relationship",
            scope_key="qq:user:10001|qq:group:20002",
            memory_type="episodic",
            content="event_type: message\nuser: [acacia/10001] 你好",
            edit_mode="draft",
            author="extractor",
            confidence=0.6,
            source_run_id="run:1",
            source_event_id="evt-1",
            tags=["episodic", "chat"],
            metadata={"event_type": "message"},
            created_at=123,
            updated_at=123,
        )
    )
    await store.upsert(
        MemoryItem(
            memory_id="memory:2",
            scope="user",
            scope_key="qq:user:10001",
            memory_type="sticky_note",
            content="姓名: acacia",
            edit_mode="readonly",
            author="user",
            confidence=1.0,
            source_run_id=None,
            source_event_id=None,
            tags=["profile"],
            metadata={},
            created_at=100,
            updated_at=100,
        )
    )
    retriever = StoreBackedMemoryRetriever(store)

    blocks = await retriever(_retrieval_request())

    assert len(blocks) == 1
    assert blocks[0].title == "episodic:relationship"
    assert blocks[0].scope == "relationship"
    assert blocks[0].source_ids == ["memory:1"]
    assert blocks[0].metadata["memory_type"] == "episodic"
