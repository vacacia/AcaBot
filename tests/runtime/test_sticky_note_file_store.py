"""StickyNoteFileStore 测试."""

from __future__ import annotations

from pathlib import Path

import pytest

from acabot.runtime.memory.file_backed.sticky_notes import StickyNoteFileStore, StickyNoteRecord
from acabot.runtime.memory.sticky_note_entities import derive_sticky_note_entity_kind


# region parser
@pytest.mark.parametrize(
    ("entity_ref", "entity_kind"),
    [
        ("qq:user:10001", "user"),
        ("qq:group:20002", "conversation"),
        ("qq:private:10001", "conversation"),
        ("discord:channel:987654321", "conversation"),
        ("matrix:room:!roomid:example.org", "conversation"),
    ],
)
def test_sticky_note_entity_ref_derives_entity_kind(entity_ref: str, entity_kind: str) -> None:
    assert derive_sticky_note_entity_kind(entity_ref) == entity_kind


@pytest.mark.parametrize(
    "entity_ref",
    [
        "",
        "thread:front:qq:group:1",
        "session:qq:private:1",
        "qq:user:../../etc/passwd",
        "qq:user:10001/subdir",
        "qq:unknown:10001",
    ],
)
def test_sticky_note_file_store_rejects_invalid_entity_ref(tmp_path: Path, entity_ref: str) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)

    with pytest.raises(ValueError):
        store.load_record(entity_ref)


# endregion


# region store
def test_sticky_note_file_store_returns_none_for_missing_record(tmp_path: Path) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)

    assert store.load_record("qq:user:10001") is None


def test_sticky_note_file_store_saves_record_under_entity_ref_layout(tmp_path: Path) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)

    saved_record = store.save_record(
        StickyNoteRecord(
            entity_ref="qq:user:10001",
            readonly="用户名字叫阿卡西亚",
            editable="说话偏直接",
        )
    )

    assert (tmp_path / "user" / "qq:user:10001" / "readonly.md").read_text(encoding="utf-8") == "用户名字叫阿卡西亚"
    assert (tmp_path / "user" / "qq:user:10001" / "editable.md").read_text(encoding="utf-8") == "说话偏直接"
    assert saved_record.entity_ref == "qq:user:10001"
    assert saved_record.updated_at >= 0


def test_sticky_note_file_store_uses_conversation_directory_for_conversation_entity_ref(tmp_path: Path) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)

    store.save_record(
        StickyNoteRecord(
            entity_ref="qq:group:20002",
            readonly="这个群主要聊部署",
            editable="",
        )
    )

    assert (tmp_path / "conversation" / "qq:group:20002" / "readonly.md").exists()


def test_sticky_note_file_store_append_creates_missing_record(tmp_path: Path) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)

    saved_record = store.append_editable_text("qq:user:10001", "喜欢直接结论")

    assert saved_record.readonly == ""
    assert saved_record.editable == "喜欢直接结论"


def test_sticky_note_file_store_append_separates_paragraphs_with_blank_line(tmp_path: Path) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)
    store.append_editable_text("qq:user:10001", "第一条")

    saved_record = store.append_editable_text("qq:user:10001", "第二条")

    assert saved_record.editable == "第一条\n\n第二条"


def test_sticky_note_file_store_lists_records_by_entity_kind(tmp_path: Path) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)
    store.save_record(StickyNoteRecord(entity_ref="qq:user:10001", readonly="u1"))
    store.save_record(StickyNoteRecord(entity_ref="qq:group:20002", readonly="g1"))

    user_records = store.list_records(entity_kind="user")
    conversation_records = store.list_records(entity_kind="conversation")

    assert [item.entity_ref for item in user_records] == ["qq:user:10001"]
    assert [item.entity_ref for item in conversation_records] == ["qq:group:20002"]


def test_sticky_note_file_store_create_record_keeps_existing_note_content(tmp_path: Path) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)
    store.save_record(
        StickyNoteRecord(
            entity_ref="qq:user:10001",
            readonly="用户名字叫阿卡西亚",
            editable="喜欢直接结论",
        )
    )

    created_record = store.create_record("qq:user:10001")

    assert created_record.readonly == "用户名字叫阿卡西亚"
    assert created_record.editable == "喜欢直接结论"


def test_sticky_note_file_store_delete_record_removes_entity_directory(tmp_path: Path) -> None:
    store = StickyNoteFileStore(root_dir=tmp_path)
    store.save_record(StickyNoteRecord(entity_ref="qq:user:10001", readonly="u1"))

    deleted = store.delete_record("qq:user:10001")

    assert deleted is True
    assert store.load_record("qq:user:10001") is None


# endregion
