"""StickyNoteService 测试."""

from __future__ import annotations

import pytest

from acabot.runtime.memory.file_backed.sticky_notes import StickyNoteFileStore, StickyNoteRecord
from acabot.runtime.memory.sticky_note_renderer import StickyNoteRenderer
from acabot.runtime.memory.sticky_notes import StickyNoteService


# region helper
def _service(tmp_path) -> StickyNoteService:
    return StickyNoteService(
        store=StickyNoteFileStore(root_dir=tmp_path),
        renderer=StickyNoteRenderer(),
    )


# endregion


# region bot api
async def test_sticky_note_service_read_note_returns_exists_false_for_missing_record(tmp_path) -> None:
    service = _service(tmp_path)

    result = await service.read_note("qq:user:10001")

    assert result == {"exists": False}


async def test_sticky_note_service_append_note_creates_record_and_only_writes_editable(tmp_path) -> None:
    service = _service(tmp_path)

    result = await service.append_note("qq:user:10001", "喜欢直接结论")
    record = await service.load_record("qq:user:10001")

    assert result == {"ok": True}
    assert record is not None
    assert record.readonly == ""
    assert record.editable == "喜欢直接结论"


@pytest.mark.parametrize("text", ["", "   ", "第一行\n第二行"])
async def test_sticky_note_service_append_note_rejects_blank_and_multiline_text(tmp_path, text: str) -> None:
    service = _service(tmp_path)

    with pytest.raises(ValueError):
        await service.append_note("qq:user:10001", text)


@pytest.mark.parametrize("entity_ref", ["thread:front:qq:group:1", "session:qq:private:1"])
async def test_sticky_note_service_append_note_rejects_non_entity_refs(tmp_path, entity_ref: str) -> None:
    service = _service(tmp_path)

    with pytest.raises(ValueError):
        await service.append_note(entity_ref, "喜欢直接结论")


async def test_sticky_note_service_read_note_returns_combined_text_for_existing_record(tmp_path) -> None:
    service = _service(tmp_path)
    await service.save_record(
        StickyNoteRecord(
            entity_ref="qq:user:10001",
            readonly="用户名字叫阿卡西亚",
            editable="喜欢直接结论",
        )
    )

    result = await service.read_note("qq:user:10001")

    assert result["exists"] is True
    assert "qq:user:10001" in str(result["combined_text"])
    assert "用户名字叫阿卡西亚" in str(result["combined_text"])
    assert "喜欢直接结论" in str(result["combined_text"])


# endregion


# region human api
async def test_sticky_note_service_save_load_list_and_delete_record(tmp_path) -> None:
    service = _service(tmp_path)

    saved_record = await service.save_record(
        StickyNoteRecord(
            entity_ref="qq:group:20002",
            readonly="这个群主要聊部署",
            editable="最近在迁 sticky note",
        )
    )
    loaded_record = await service.load_record("qq:group:20002")
    listed_records = await service.list_records(entity_kind="conversation")
    deleted = await service.delete_record("qq:group:20002")

    assert saved_record.entity_ref == "qq:group:20002"
    assert loaded_record is not None
    assert loaded_record.readonly == "这个群主要聊部署"
    assert [item.entity_ref for item in listed_records] == ["qq:group:20002"]
    assert deleted is True
    assert await service.load_record("qq:group:20002") is None


async def test_sticky_note_service_create_record_builds_empty_note(tmp_path) -> None:
    service = _service(tmp_path)

    record = await service.create_record("qq:user:10001")

    assert record.entity_ref == "qq:user:10001"
    assert record.readonly == ""
    assert record.editable == ""


# endregion
