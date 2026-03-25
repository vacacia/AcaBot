"""sticky note builtin tool surface.

这个文件负责把 sticky note 服务接成模型可见的 builtin tools.

关系图:

    StickyNoteService
           |
           v
    BuiltinStickyNoteToolSurface
           |
           v
        ToolBroker

负责:
    - 注册 `sticky_note_read`
    - 注册 `sticky_note_append`
    - 把服务层结果转成统一 `ToolResult`
"""

from __future__ import annotations

from typing import Any

from acabot.agent import ToolSpec

from ..memory.sticky_notes import StickyNoteService
from ..tool_broker import ToolBroker, ToolExecutionContext, ToolResult


# region source
BUILTIN_STICKY_NOTE_TOOL_SOURCE = "builtin:sticky_notes"


# endregion


# region surface
class BuiltinStickyNoteToolSurface:
    """sticky note builtin tools 的注册入口.

    Attributes:
        sticky_note_service (StickyNoteService | None): sticky note 服务层.
    """

    def __init__(self, *, sticky_note_service: StickyNoteService | None) -> None:
        """保存 sticky note builtin tools 需要的依赖.

        Args:
            sticky_note_service: 当前 sticky note 服务层.
        """

        self.sticky_note_service = sticky_note_service

    def register(self, tool_broker: ToolBroker) -> list[str]:
        """把 sticky note builtin tools 注册到 ToolBroker.

        Args:
            tool_broker: 当前 runtime 使用的 ToolBroker.

        Returns:
            list[str]: 这次注册的工具名列表.
        """

        tool_broker.unregister_source(BUILTIN_STICKY_NOTE_TOOL_SOURCE)
        if self.sticky_note_service is None:
            return []
        definitions = [
            (
                ToolSpec(
                    name="sticky_note_read",
                    description=(
                        "Read the full sticky note view for a specific entity_ref. "
                        "entity_ref must point to a user or conversation, for example "
                        "qq:user:10001 or qq:group:20002."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "entity_ref": {"type": "string"},
                        },
                        "required": ["entity_ref"],
                    },
                ),
                self._read_note,
            ),
            (
                ToolSpec(
                    name="sticky_note_append",
                    description=(
                        "Append one single-line observation to the editable area of the sticky note "
                        "for a specific entity_ref. text must be non-empty and must not contain newlines."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "entity_ref": {"type": "string"},
                            "text": {"type": "string"},
                        },
                        "required": ["entity_ref", "text"],
                    },
                ),
                self._append_note,
            ),
        ]
        names: list[str] = []
        for spec, handler in definitions:
            tool_broker.register_tool(
                spec,
                handler,
                source=BUILTIN_STICKY_NOTE_TOOL_SOURCE,
            )
            names.append(spec.name)
        return names

    async def _read_note(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        """执行 `sticky_note_read`.

        Args:
            arguments: 工具参数.
            ctx: 当前工具执行上下文.

        Returns:
            ToolResult: 读到内容时返回完整文本, 没有 note 时返回明确空结果.
        """

        _ = ctx
        service = self._require_service()
        result = await service.read_note(str(arguments.get("entity_ref", "") or ""))
        if result.get("exists") is not True:
            return ToolResult(
                llm_content="Sticky note not found.",
                raw={"exists": False},
            )
        return ToolResult(
            llm_content=str(result.get("combined_text", "") or ""),
            raw=result,
        )

    async def _append_note(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        """执行 `sticky_note_append`.

        Args:
            arguments: 工具参数.
            ctx: 当前工具执行上下文.

        Returns:
            ToolResult: 简洁成功结果.
        """

        _ = ctx
        service = self._require_service()
        result = await service.append_note(
            str(arguments.get("entity_ref", "") or ""),
            str(arguments.get("text", "") or ""),
        )
        return ToolResult(
            llm_content="Sticky note appended.",
            raw=result,
        )

    def _require_service(self) -> StickyNoteService:
        """返回当前必需的 sticky note 服务层.

        Returns:
            StickyNoteService: 当前 sticky note 服务层.

        Raises:
            RuntimeError: 当前服务层不可用时抛错.
        """

        if self.sticky_note_service is None:
            raise RuntimeError("sticky note service unavailable")
        return self.sticky_note_service


# endregion


__all__ = [
    "BUILTIN_STICKY_NOTE_TOOL_SOURCE",
    "BuiltinStickyNoteToolSurface",
]
