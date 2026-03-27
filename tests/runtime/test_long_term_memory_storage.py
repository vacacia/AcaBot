from dataclasses import replace
from pathlib import Path

from acabot.runtime.memory.long_term_ingestor import ThreadLtmCursor
from acabot.runtime.memory.long_term_memory.contracts import (
    FailedWindowRecord,
    MemoryEntry,
    MemoryProvenance,
)
from acabot.runtime.memory.long_term_memory.storage import LanceDbLongTermMemoryStore


def _entry(
    *,
    entry_id: str = "entry-1",
    updated_at: int = 100,
    topic: str = "咖啡偏好",
    keywords: list[str] | None = None,
    persons: list[str] | None = None,
) -> MemoryEntry:
    return MemoryEntry(
        entry_id=entry_id,
        conversation_id="qq:group:42",
        created_at=10,
        updated_at=updated_at,
        extractor_version="ltm-v1",
        topic=topic,
        lossless_restatement="Alice 喜欢拿铁。",
        keywords=keywords or ["latte"],
        persons=persons or ["Alice"],
        provenance=MemoryProvenance(fact_ids=["e:evt-1"]),
    )


def test_lancedb_store_upserts_entry_and_keeps_latest_version(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    entry = _entry(updated_at=100)
    newer = replace(entry, updated_at=200, keywords=["latte", "coffee"])

    store.upsert_entries([entry])
    store.upsert_entries([newer])

    saved = store.get_entry(entry.entry_id)
    assert saved is not None
    assert saved.updated_at == 200
    assert saved.keywords == ["latte", "coffee"]
    assert saved.created_at == 10


def test_lancedb_store_preserves_created_at_and_updated_at_for_identical_reingest(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    entry = _entry(updated_at=100)
    duplicate = replace(entry, created_at=999, updated_at=300)

    store.upsert_entries([entry], vectors=[[0.1, 0.2, 0.3]])
    store.upsert_entries([duplicate])

    saved = store.get_entry(entry.entry_id)
    assert saved is not None
    assert saved.created_at == 10
    assert saved.updated_at == 100


def test_lancedb_store_preserves_created_at_when_content_changes(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    entry = _entry(updated_at=100)
    changed = replace(
        entry,
        created_at=999,
        updated_at=300,
        lossless_restatement="Alice 更喜欢美式。",
    )

    store.upsert_entries([entry])
    store.upsert_entries([changed])

    saved = store.get_entry(entry.entry_id)
    assert saved is not None
    assert saved.created_at == 10
    assert saved.updated_at == 300
    assert saved.lossless_restatement == "Alice 更喜欢美式。"


def test_lancedb_store_supports_symbolic_and_lexical_queries(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    store.upsert_entries(
        [
            _entry(
                topic="咖啡偏好",
                keywords=["latte"],
                persons=["Alice"],
            )
        ]
    )

    lexical = store.keyword_search("latte", conversation_id="qq:group:42", limit=5)
    symbolic = store.structured_search(
        conversation_id="qq:group:42",
        persons=["Alice"],
        entities=[],
        location=None,
        time_range=None,
        limit=5,
    )

    assert len(lexical) == 1
    assert len(symbolic) == 1


def test_lancedb_store_persists_cursor_and_failed_window_state(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    store.save_cursor(
        ThreadLtmCursor(
            thread_id="thread:1",
            last_event_id=10,
            last_message_id=20,
            updated_at=30,
        )
    )
    store.save_failed_window(
        FailedWindowRecord(
            window_id="win:1",
            conversation_id="qq:group:42",
            thread_id="thread:1",
            fact_ids=["e:evt-1", "m:msg-1"],
            error="extract failed",
            retry_count=2,
            first_failed_at=100,
            last_failed_at=200,
        )
    )

    saved_cursor = store.load_cursor("thread:1")
    failed_windows = store.list_failed_windows("qq:group:42")

    assert saved_cursor is not None
    assert saved_cursor.last_message_id == 20
    assert failed_windows[0].window_id == "win:1"


def test_lancedb_store_keyword_search_returns_empty_on_fresh_database(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")

    lexical = store.keyword_search("latte", conversation_id="qq:group:42", limit=5)

    assert lexical == []
