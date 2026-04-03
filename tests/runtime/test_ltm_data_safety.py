from pathlib import Path

from acabot.runtime.memory.long_term_ingestor import ThreadLtmCursor
from acabot.runtime.memory.long_term_memory.contracts import MemoryEntry, MemoryProvenance
from acabot.runtime.memory.long_term_memory.storage import LanceDbLongTermMemoryStore


def _entry(entry_id: str) -> MemoryEntry:
    return MemoryEntry(
        entry_id=entry_id,
        conversation_id="qq:group:42",
        created_at=10,
        updated_at=100,
        extractor_version="ltm-v1",
        topic=f"topic-{entry_id}",
        lossless_restatement=f"restatement-{entry_id}",
        keywords=["latte"],
        persons=["Alice"],
        provenance=MemoryProvenance(fact_ids=[f"fact-{entry_id}"]),
    )


def test_backup_produces_restorable_snapshot(tmp_path: Path) -> None:
    src_dir = tmp_path / "lancedb"
    backup_dir = tmp_path / "backups"

    store = LanceDbLongTermMemoryStore(src_dir)
    store.upsert_entries([_entry("e-1"), _entry("e-2"), _entry("e-3")])
    store.save_cursor(
        ThreadLtmCursor(
            thread_id="t-1",
            last_event_id=100,
            last_message_id=50,
            updated_at=1000,
        )
    )

    backup_path = store.backup(backup_dir)
    restored = LanceDbLongTermMemoryStore(backup_path)

    validation = restored.validate()
    assert validation.ok, validation.errors

    for entry_id in ["e-1", "e-2", "e-3"]:
        assert restored.get_entry(entry_id) is not None

    cursor = restored.load_cursor("t-1")
    assert cursor is not None
    assert cursor.last_event_id == 100
