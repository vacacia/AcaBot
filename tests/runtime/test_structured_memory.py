from acabot.runtime import (
    InMemoryMemoryStore,
    MemoryItem,
    MemoryAssemblySpec,
    SharedMemoryRetrievalRequest,
    StoreBackedMemoryRetriever,
)


def _retrieval_request() -> SharedMemoryRetrievalRequest:
    return SharedMemoryRetrievalRequest(
        run_id="run:1",
        thread_id="qq:group:20002",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:group:20002",
        event_id="evt-1",
        event_type="message",
        event_timestamp=123,
        event_tags=["chat"],
        query_text="你好",
        working_summary="群里最近在讨论机器人",
        retained_history=[],
        requested_tags=[],
        metadata={"sticky_note_scopes": ["relationship"]},
    )


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
    assert blocks[0].source == "store_memory"
    assert blocks[0].scope == "relationship"
    assert blocks[0].source_ids == ["memory:1"]
    assert blocks[0].assembly == MemoryAssemblySpec(
        target_slot="message_prefix",
        priority=700,
    )
    assert blocks[0].metadata["memory_type"] == "episodic"


async def test_store_backed_memory_retriever_filters_by_requested_tags() -> None:
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
            tags=["episodic", "project"],
            metadata={"event_type": "message"},
            created_at=123,
            updated_at=123,
        )
    )
    await store.upsert(
        MemoryItem(
            memory_id="memory:2",
            scope="relationship",
            scope_key="qq:user:10001|qq:group:20002",
            memory_type="episodic",
            content="event_type: message\nuser: [acacia/10001] 再见",
            edit_mode="draft",
            author="extractor",
            confidence=0.6,
            source_run_id="run:2",
            source_event_id="evt-2",
            tags=["episodic", "chitchat"],
            metadata={"event_type": "message"},
            created_at=124,
            updated_at=124,
        )
    )
    retriever = StoreBackedMemoryRetriever(store)
    request = _retrieval_request()
    request.requested_tags = ["project"]

    blocks = await retriever(request)

    assert [block.source_ids for block in blocks] == [["memory:1"]]


async def test_store_backed_memory_retriever_keeps_sticky_note_semantics() -> None:
    store = InMemoryMemoryStore()
    await store.upsert(
        MemoryItem(
            memory_id="memory:sticky:1",
            scope="relationship",
            scope_key="qq:user:10001|qq:group:20002",
            memory_type="sticky_note",
            content="关系便签: 这个群聊里优先直接给结论",
            edit_mode="readonly",
            author="user",
            confidence=1.0,
            source_run_id=None,
            source_event_id=None,
            tags=["sticky_note"],
            metadata={"note_key": "reply_style"},
            created_at=123,
            updated_at=123,
        )
    )
    retriever = StoreBackedMemoryRetriever(store)

    blocks = await retriever(_retrieval_request())

    assert len(blocks) == 1
    assert blocks[0].source == "sticky_notes"
    assert blocks[0].assembly == MemoryAssemblySpec(
        target_slot="message_prefix",
        priority=800,
    )


async def test_store_backed_memory_retriever_respects_explicit_empty_sticky_note_allowlist() -> None:
    store = InMemoryMemoryStore()
    await store.upsert(
        MemoryItem(
            memory_id="memory:sticky:1",
            scope="relationship",
            scope_key="qq:user:10001|qq:group:20002",
            memory_type="sticky_note",
            content="关系便签: 这个群聊里优先直接给结论",
            edit_mode="readonly",
            author="user",
            confidence=1.0,
            source_run_id=None,
            source_event_id=None,
            tags=["sticky_note"],
            metadata={"note_key": "reply_style"},
            created_at=123,
            updated_at=123,
        )
    )
    retriever = StoreBackedMemoryRetriever(store)
    request = _retrieval_request()
    request.metadata["sticky_note_scopes"] = []

    blocks = await retriever(request)

    assert blocks == []
