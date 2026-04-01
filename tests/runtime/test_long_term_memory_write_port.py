from pathlib import Path

from acabot.runtime.memory.conversation_facts import ConversationDelta, ConversationFact
from acabot.runtime.memory.long_term_memory.contracts import MemoryEntry, MemoryProvenance
from acabot.runtime.memory.long_term_memory.storage import LanceDbLongTermMemoryStore
from acabot.runtime.memory.long_term_memory.write_port import LtmWritePort
from acabot.runtime.memory.long_term_ingestor import ThreadLtmIngestResult


class RecordingExtractor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def extract_window(self, *, conversation_id: str, facts: list[ConversationFact], now_ts: int):
        self.calls.append((conversation_id, len(facts)))
        index = len(self.calls)
        return [
            MemoryEntry(
                entry_id=f"entry-{index}",
                conversation_id=conversation_id,
                created_at=now_ts,
                updated_at=now_ts,
                extractor_version="ltm-v1",
                topic=f"topic-{index}",
                lossless_restatement=f"fact-{index}",
                provenance=MemoryProvenance(
                    fact_ids=[f"{facts[0].source_kind}:{facts[0].source_id}"]
                ),
            )
        ]


class FailingExtractor:
    async def extract_window(self, *, conversation_id: str, facts: list[ConversationFact], now_ts: int):
        _ = conversation_id, facts, now_ts
        raise RuntimeError("extract failed")


class FailingFirstWindowExtractor:
    async def extract_window(self, *, conversation_id: str, facts: list[ConversationFact], now_ts: int):
        if facts and facts[0].source_id == "fact-1":
            raise RuntimeError("extract failed")
        return [
            MemoryEntry(
                entry_id="entry-success",
                conversation_id=conversation_id,
                created_at=now_ts,
                updated_at=now_ts,
                extractor_version="ltm-v1",
                topic="topic-success",
                lossless_restatement="fact-success",
                provenance=MemoryProvenance(
                    fact_ids=[f"{facts[0].source_kind}:{facts[0].source_id}"]
                ),
            )
        ]


class RecordingEmbeddingClient:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def embed_entries(self, entries: list[MemoryEntry]) -> list[list[float]]:
        self.calls.append(len(entries))
        return [[0.1, 0.2, 0.3] for _ in entries]


def _delta(count: int, *, conversation_id: str = "qq:group:42") -> ConversationDelta:
    return ConversationDelta(
        facts=[
            ConversationFact(
                thread_id="thread:1",
                timestamp=index + 1,
                source_kind="channel_event" if index % 2 == 0 else "message",
                source_id=f"fact-{index + 1}",
                role="user" if index % 2 == 0 else "assistant",
                text=f"text-{index + 1}",
                payload={},
                actor_id="qq:user:10001",
                actor_display_name="Acacia",
                channel_scope=conversation_id,
                run_id=None,
            )
            for index in range(count)
        ],
        max_event_id=count,
        max_message_id=count,
    )


async def test_write_port_ingests_delta_in_fact_windows_without_saving_cursor(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    extractor = RecordingExtractor()
    embedding = RecordingEmbeddingClient()
    port = LtmWritePort(
        store=store,
        extractor=extractor,
        embedding_client=embedding,
    )

    result = await port.ingest_thread_delta("thread:1", _delta(60))

    cursor = await port.load_cursor("thread:1")
    assert result == ThreadLtmIngestResult(advance_cursor=True, has_failures=False)
    assert cursor is None
    assert extractor.calls == [("qq:group:42", 50), ("qq:group:42", 20)]
    assert embedding.calls == [1, 1]


async def test_write_port_records_failed_window_without_advancing_cursor(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    port = LtmWritePort(
        store=store,
        extractor=FailingExtractor(),
        embedding_client=RecordingEmbeddingClient(),
    )

    result = await port.ingest_thread_delta("thread:1", _delta(50))

    cursor = await port.load_cursor("thread:1")
    failed = store.list_failed_windows("qq:group:42")
    assert result == ThreadLtmIngestResult(advance_cursor=True, has_failures=True)
    assert cursor is None
    assert len(failed) == 1
    assert failed[0].window_id.startswith("qq:group:42:")


async def test_write_port_continues_after_failed_window_and_records_retry_count(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    extractor = FailingFirstWindowExtractor()
    port = LtmWritePort(
        store=store,
        extractor=extractor,
        embedding_client=RecordingEmbeddingClient(),
    )

    first_result = await port.ingest_thread_delta("thread:1", _delta(60))
    second_result = await port.ingest_thread_delta("thread:1", _delta(60))

    saved_entry = store.get_entry("entry-success")
    failed = store.list_failed_windows("qq:group:42")

    assert first_result == ThreadLtmIngestResult(advance_cursor=True, has_failures=True)
    assert second_result == ThreadLtmIngestResult(advance_cursor=True, has_failures=True)
    assert saved_entry is not None
    assert len(failed) == 1
    assert failed[0].retry_count == 2
    assert failed[0].first_failed_at == 50
    assert failed[0].last_failed_at == 50
