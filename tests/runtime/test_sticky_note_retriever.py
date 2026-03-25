"""StickyNoteRetriever 测试."""

from __future__ import annotations

from dataclasses import dataclass, field

from acabot.runtime.memory.file_backed.retrievers import StickyNoteRetriever
from acabot.runtime.memory.file_backed.sticky_notes import StickyNoteFileStore, StickyNoteRecord
from acabot.runtime.memory.memory_broker import MemoryAssemblySpec, SharedMemoryRetrievalRequest
from acabot.runtime.memory.sticky_note_renderer import StickyNoteRenderer


# region helper
def _request(*, sticky_note_targets: list[str]) -> SharedMemoryRetrievalRequest:
    return SharedMemoryRetrievalRequest(
        run_id="run:1",
        thread_id="thread:1",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:group:20002",
        event_id="evt:1",
        event_type="message",
        event_timestamp=1,
        metadata={"sticky_note_targets": list(sticky_note_targets)},
    )


@dataclass(slots=True)
class SpyRenderer(StickyNoteRenderer):
    calls: list[str] = field(default_factory=list)

    def render_combined_text(self, record: StickyNoteRecord) -> str:
        self.calls.append(record.entity_ref)
        return f"rendered:{record.entity_ref}"


# endregion


async def test_sticky_note_retriever_reads_only_requested_targets(tmp_path) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)
    renderer = StickyNoteRenderer()
    store.save_record(StickyNoteRecord(entity_ref="qq:user:10001", readonly="u1"))
    store.save_record(StickyNoteRecord(entity_ref="qq:group:20002", readonly="g1"))
    retriever = StickyNoteRetriever(store=store, renderer=renderer)

    blocks = await retriever(_request(sticky_note_targets=["qq:user:10001"]))

    assert len(blocks) == 1
    assert blocks[0].source == "sticky_notes"
    assert blocks[0].scope == "user"
    assert blocks[0].source_ids == ["sticky_note:qq:user:10001"]
    assert blocks[0].assembly == MemoryAssemblySpec(target_slot="message_prefix", priority=800)
    assert "qq:user:10001" in blocks[0].content


async def test_sticky_note_retriever_skips_missing_target_and_keeps_existing_ones(tmp_path) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)
    renderer = StickyNoteRenderer()
    store.save_record(StickyNoteRecord(entity_ref="qq:group:20002", readonly="g1"))
    retriever = StickyNoteRetriever(store=store, renderer=renderer)

    blocks = await retriever(
        _request(sticky_note_targets=["qq:user:10001", "qq:group:20002"])
    )

    assert [block.metadata["entity_ref"] for block in blocks] == ["qq:group:20002"]


async def test_sticky_note_retriever_uses_renderer_output_as_block_content(tmp_path) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)
    renderer = SpyRenderer()
    store.save_record(StickyNoteRecord(entity_ref="qq:user:10001", readonly="u1"))
    retriever = StickyNoteRetriever(store=store, renderer=renderer)

    blocks = await retriever(_request(sticky_note_targets=["qq:user:10001"]))

    assert renderer.calls == ["qq:user:10001"]
    assert blocks[0].content == "rendered:qq:user:10001"
