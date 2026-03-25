from acabot.runtime import MemoryAssemblySpec, SharedMemoryRetrievalRequest, SoulSource
from acabot.runtime.memory.file_backed import SelfFileRetriever, StickyNoteFileStore, StickyNoteRetriever
from acabot.runtime.memory.file_backed.sticky_notes import StickyNoteRecord
from acabot.runtime.memory.sticky_note_renderer import StickyNoteRenderer


def _request(*, sticky_note_targets: list[str] | None = None) -> SharedMemoryRetrievalRequest:
    return SharedMemoryRetrievalRequest(
        run_id="run:1",
        thread_id="qq:group:20002",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:group:20002",
        event_id="evt-1",
        event_type="message",
        event_timestamp=1,
        event_tags=[],
        query_text="hello",
        working_summary="",
        retained_history=[],
        requested_tags=[],
        metadata={"sticky_note_targets": list(sticky_note_targets or [])},
    )


async def test_self_file_retriever_returns_self_memory_block(tmp_path) -> None:
    source = SoulSource(root_dir=tmp_path)
    source.append_today_entry("[qq:group:123 time=1] vi 交代了部署任务")
    retriever = SelfFileRetriever(source)

    blocks = await retriever(_request())

    assert blocks[0].source == "self"
    assert blocks[0].scope == "global"
    assert blocks[0].assembly == MemoryAssemblySpec(
        target_slot="message_prefix",
        priority=900,
    )
    assert "today.md" in blocks[0].content


async def test_sticky_note_retriever_reads_requested_targets(tmp_path) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)
    store.save_record(StickyNoteRecord(entity_ref="qq:user:10001", readonly="回答要更直接"))
    store.save_record(StickyNoteRecord(entity_ref="qq:group:20002", readonly="不要刷屏"))
    retriever = StickyNoteRetriever(store=store, renderer=StickyNoteRenderer())

    blocks = await retriever(_request(sticky_note_targets=["qq:user:10001", "qq:group:20002"]))

    assert [block.scope for block in blocks] == ["user", "conversation"]


async def test_sticky_note_retriever_skips_missing_targets(tmp_path) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)
    store.save_record(StickyNoteRecord(entity_ref="qq:user:10001", readonly="回答要更直接"))
    retriever = StickyNoteRetriever(store=store, renderer=StickyNoteRenderer())

    blocks = await retriever(_request(sticky_note_targets=["qq:user:10001", "qq:group:20002"]))

    assert len(blocks) == 1
    assert blocks[0].metadata["entity_ref"] == "qq:user:10001"
