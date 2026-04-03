import asyncio
from dataclasses import replace
from pathlib import Path

from acabot.runtime.memory.long_term_ingestor import ThreadLtmCursor
from acabot.runtime.memory.long_term_memory.contracts import MemoryEntry, MemoryProvenance
from acabot.runtime.memory.long_term_memory.storage import LanceDbLongTermMemoryStore


def _entry(
    *,
    entry_id: str,
    conversation_id: str = "qq:group:42",
    updated_at: int = 100,
    topic: str = "咖啡偏好",
) -> MemoryEntry:
    return MemoryEntry(
        entry_id=entry_id,
        conversation_id=conversation_id,
        created_at=10,
        updated_at=updated_at,
        extractor_version="ltm-v1",
        topic=topic,
        lossless_restatement=f"{entry_id} restatement",
        keywords=["latte"],
        persons=["Alice"],
        provenance=MemoryProvenance(fact_ids=[f"fact:{entry_id}"]),
    )


async def test_concurrent_upsert_entries_serialize(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    batch_a = [_entry(entry_id="a-1"), _entry(entry_id="a-2")]
    batch_b = [_entry(entry_id="b-1"), _entry(entry_id="b-2")]

    await asyncio.gather(
        asyncio.to_thread(store.upsert_entries, batch_a),
        asyncio.to_thread(store.upsert_entries, batch_b),
    )

    for entry_id in ["a-1", "a-2", "b-1", "b-2"]:
        assert store.get_entry(entry_id) is not None


async def test_concurrent_upsert_and_delete_serialize(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    existing = _entry(entry_id="existing")
    store.upsert_entries([existing])

    created = _entry(entry_id="new-entry", updated_at=200)
    await asyncio.gather(
        asyncio.to_thread(store.delete_entry, existing.entry_id),
        asyncio.to_thread(store.upsert_entries, [created]),
    )

    assert store.get_entry(existing.entry_id) is None
    assert store.get_entry(created.entry_id) is not None


async def test_concurrent_save_cursor_serialize(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    first = ThreadLtmCursor(
        thread_id="thread:1",
        last_event_id=10,
        last_message_id=20,
        updated_at=30,
    )
    second = replace(first, last_event_id=11, last_message_id=21, updated_at=31)

    await asyncio.gather(
        asyncio.to_thread(store.save_cursor, first),
        asyncio.to_thread(store.save_cursor, second),
    )

    saved = store.load_cursor("thread:1")
    assert saved is not None
    assert saved.last_event_id in {10, 11}
    assert saved.last_message_id in {20, 21}


def test_lancedb_store_validate_passes_on_fresh_database(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")

    result = store.validate()

    assert result.ok is True
    assert result.errors == []
