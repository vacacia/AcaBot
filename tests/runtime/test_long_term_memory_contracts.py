import pytest

from acabot.runtime.memory.conversation_facts import ConversationFact
from acabot.runtime.memory.long_term_memory.contracts import (
    MemoryEntry,
    MemoryProvenance,
)
from acabot.runtime.memory.long_term_memory.fact_ids import (
    build_fact_anchor_map,
    build_fact_id_from_conversation_fact,
    build_memory_entry_id,
)


def test_entry_id_is_deterministic_from_conversation_and_fact_set() -> None:
    fact_ids = ["m:msg-2", "e:evt-1", "e:evt-1"]

    entry_id_a = build_memory_entry_id("qq:group:42", fact_ids)
    entry_id_b = build_memory_entry_id("qq:group:42", ["e:evt-1", "m:msg-2"])

    assert entry_id_a == entry_id_b


def test_memory_entry_requires_non_empty_topic_and_fact_ids() -> None:
    with pytest.raises(ValueError):
        MemoryEntry(
            entry_id="entry-1",
            conversation_id="qq:group:42",
            created_at=1,
            updated_at=1,
            extractor_version="ltm-v1",
            topic="",
            lossless_restatement="Alice likes latte.",
            provenance=MemoryProvenance(fact_ids=[]),
        )


def test_anchor_map_round_trips_fact_ids() -> None:
    anchors = build_fact_anchor_map(["e:evt-1", "m:msg-1"])

    assert anchors.anchor_for("e:evt-1") == "f1"
    assert anchors.fact_id_for("f2") == "m:msg-1"


def test_build_fact_id_from_conversation_fact_uses_stable_prefixes() -> None:
    event_fact = ConversationFact(
        thread_id="thread:front:qq:group:42",
        timestamp=1,
        source_kind="channel_event",
        source_id="evt-1",
        role="user",
        text="hello",
        payload={},
        actor_id="qq:user:1",
        actor_display_name="A",
        channel_scope="qq:group:42",
        run_id=None,
    )
    message_fact = ConversationFact(
        thread_id="thread:front:qq:group:42",
        timestamp=2,
        source_kind="message",
        source_id="msg-1",
        role="assistant",
        text="hi",
        payload={},
        actor_id="agent:aca",
        actor_display_name="Aca",
        channel_scope="qq:group:42",
        run_id="run-1",
    )

    assert build_fact_id_from_conversation_fact(event_fact) == "e:evt-1"
    assert build_fact_id_from_conversation_fact(message_fact) == "m:msg-1"
