"""StickyNoteRenderer 测试."""

from __future__ import annotations

from acabot.runtime.memory.file_backed.sticky_notes import StickyNoteRecord
from acabot.runtime.memory.sticky_note_renderer import StickyNoteRenderer


def test_sticky_note_renderer_renders_combined_xml_text() -> None:
    renderer = StickyNoteRenderer()

    content = renderer.render_combined_text(
        StickyNoteRecord(
            entity_ref="qq:user:10001",
            readonly="用户名字叫阿卡西亚",
            editable="说话偏直接",
        )
    )

    assert '<sticky_note entity_ref="qq:user:10001" entity_kind="user">' in content
    assert "<high_confidence_facts>" in content
    assert "用户名字叫阿卡西亚" in content
    assert "<accumulated_observations>" in content
    assert "说话偏直接" in content
    assert "readonly" not in content


def test_sticky_note_renderer_keeps_empty_sections_stable() -> None:
    renderer = StickyNoteRenderer()

    content = renderer.render_combined_text(
        StickyNoteRecord(
            entity_ref="qq:group:20002",
            readonly="",
            editable="",
        )
    )

    assert '<sticky_note entity_ref="qq:group:20002" entity_kind="conversation">' in content
    assert "<high_confidence_facts>" in content
    assert "<accumulated_observations>" in content
    assert content.endswith("</sticky_note>")
