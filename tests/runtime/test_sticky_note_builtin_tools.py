"""sticky note builtin tool surface 测试."""

from __future__ import annotations

from types import SimpleNamespace

from acabot.runtime import AgentProfile, ToolBroker, ToolExecutionContext
from acabot.runtime.builtin_tools.sticky_notes import (
    BUILTIN_STICKY_NOTE_TOOL_SOURCE,
    BuiltinStickyNoteToolSurface,
)
from acabot.runtime.memory.file_backed.sticky_notes import StickyNoteFileStore, StickyNoteRecord
from acabot.runtime.memory.sticky_note_renderer import StickyNoteRenderer
from acabot.runtime.memory.sticky_notes import StickyNoteService
from acabot.types import EventSource


# region helper
def _context(*, enabled_tools: list[str]) -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id="run:1",
        thread_id="thread:1",
        actor_id="qq:user:10001",
        agent_id="aca",
        target=EventSource(
            platform="qq",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        profile=AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            enabled_tools=list(enabled_tools),
        ),
        world_view=SimpleNamespace(name="world"),
    )


# endregion


async def test_sticky_note_builtin_tool_surface_registers_read_and_append(tmp_path) -> None:
    service = StickyNoteService(
        store=StickyNoteFileStore(root_dir=tmp_path),
        renderer=StickyNoteRenderer(),
    )
    broker = ToolBroker()
    surface = BuiltinStickyNoteToolSurface(sticky_note_service=service)

    names = surface.register(broker)
    sources = {item["name"]: item["source"] for item in broker.list_registered_tools()}

    assert names == ["sticky_note_read", "sticky_note_append"]
    assert sources["sticky_note_read"] == BUILTIN_STICKY_NOTE_TOOL_SOURCE
    assert sources["sticky_note_append"] == BUILTIN_STICKY_NOTE_TOOL_SOURCE


async def test_sticky_note_builtin_tool_surface_reads_and_appends_note(tmp_path) -> None:
    service = StickyNoteService(
        store=StickyNoteFileStore(root_dir=tmp_path),
        renderer=StickyNoteRenderer(),
    )
    broker = ToolBroker()
    surface = BuiltinStickyNoteToolSurface(sticky_note_service=service)
    surface.register(broker)
    await service.save_record(
        StickyNoteRecord(
            entity_ref="qq:user:10001",
            readonly="用户名字叫阿卡西亚",
        )
    )
    ctx = _context(enabled_tools=["sticky_note_read", "sticky_note_append"])

    read_result = await broker.execute(
        tool_name="sticky_note_read",
        arguments={"entity_ref": "qq:user:10001"},
        ctx=ctx,
    )
    append_result = await broker.execute(
        tool_name="sticky_note_append",
        arguments={"entity_ref": "qq:user:10001", "text": "喜欢直接结论"},
        ctx=ctx,
    )
    after_append = await service.load_record("qq:user:10001")

    assert "qq:user:10001" in str(read_result.llm_content)
    assert append_result.raw == {"ok": True}
    assert after_append is not None
    assert after_append.editable == "喜欢直接结论"
