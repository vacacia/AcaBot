import pytest

from acabot.runtime.memory.long_term_memory.extractor import (
    WindowExtractionError,
    parse_extractor_response,
)
from acabot.runtime.memory.long_term_memory.fact_ids import build_fact_anchor_map


def test_extractor_rejects_window_if_any_entry_lacks_anchor_evidence() -> None:
    response = [
        {
            "topic": "咖啡偏好",
            "lossless_restatement": "Alice 喜欢拿铁。",
            "evidence": [],
        }
    ]

    with pytest.raises(WindowExtractionError):
        parse_extractor_response(
            response=response,
            anchor_map=build_fact_anchor_map(["e:evt-1"]),
            fact_roles={},
            conversation_id="qq:group:42",
            extractor_version="v1",
            now_ts=123,
        )


def test_extractor_maps_local_fact_anchors_back_to_fact_ids() -> None:
    anchors = build_fact_anchor_map(["e:evt-1", "m:msg-1"])
    entries = parse_extractor_response(
        response=[
            {
                "topic": "偏好",
                "lossless_restatement": "Alice 喜欢拿铁。",
                "evidence": ["f2"],
            }
        ],
        anchor_map=anchors,
        fact_roles={},
        conversation_id="qq:group:42",
        extractor_version="v1",
        now_ts=123,
    )

    assert entries[0].provenance.fact_ids == ["m:msg-1"]


def test_extractor_accepts_object_wrapper_with_entries_key() -> None:
    anchors = build_fact_anchor_map(["e:evt-1"])

    entries = parse_extractor_response(
        response={
            "entries": [
                {
                    "topic": "工作地点",
                    "lossless_restatement": "Alice 在上海办公。",
                    "keywords": ["上海", "办公"],
                    "persons": ["Alice"],
                    "entities": ["AcaBot"],
                    "location": "上海",
                    "evidence": ["f1"],
                }
            ]
        },
        anchor_map=anchors,
        fact_roles={},
        conversation_id="qq:group:42",
        extractor_version="v1",
        now_ts=123,
    )

    assert entries[0].topic == "工作地点"
    assert entries[0].entry_id


def test_extractor_wraps_unknown_anchor_as_window_error() -> None:
    anchors = build_fact_anchor_map(["e:evt-1"])

    with pytest.raises(WindowExtractionError, match="unknown fact anchor: f2"):
        parse_extractor_response(
            response=[
                {
                    "topic": "偏好",
                    "lossless_restatement": "Alice 喜欢拿铁。",
                    "evidence": ["f2"],
                }
            ],
            anchor_map=anchors,
            fact_roles={},
            conversation_id="qq:group:42",
            extractor_version="v1",
            now_ts=123,
        )
