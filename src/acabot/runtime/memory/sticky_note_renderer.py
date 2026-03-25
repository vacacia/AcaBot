"""sticky note 统一文本渲染器.

这个文件把 `StickyNoteRecord` 渲染成对模型和工具都一致的完整文本.

关系图:

    StickyNoteRecord
          |
          v
    StickyNoteRenderer
      |         |
      |         +--> sticky_note_read()
      |
      +------------> StickyNoteRetriever -> MemoryBlock

这里不负责文件读写, 也不负责决定 retrieval target.
它只负责把一张实体便签稳定地表达成一段 XML 风格文本.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .sticky_note_entities import derive_sticky_note_entity_kind

if TYPE_CHECKING:
    from .file_backed.sticky_notes import StickyNoteRecord


# region renderer
@dataclass(slots=True)
class StickyNoteRenderer:
    """把 `StickyNoteRecord` 渲染成统一文本视图的组件.

    Attributes:
        None.
    """

    def render_combined_text(self, record: StickyNoteRecord) -> str:
        """渲染一张 sticky note 的完整文本视图.

        Args:
            record: 待渲染的 sticky note 记录.

        Returns:
            str: 给工具读取和 retrieval 注入共用的完整文本.
        """

        entity_kind = derive_sticky_note_entity_kind(record.entity_ref)
        high_confidence_text = (record.readonly or "").strip()
        observation_text = (record.editable or "").strip()
        return "\n".join(
            [
                f'<sticky_note entity_ref="{record.entity_ref}" entity_kind="{entity_kind}">',
                "  <high_confidence_facts>",
                self._indent_block(high_confidence_text),
                "  </high_confidence_facts>",
                "  <accumulated_observations>",
                self._indent_block(observation_text),
                "  </accumulated_observations>",
                "</sticky_note>",
            ]
        )

    @staticmethod
    def _indent_block(text: str) -> str:
        """把正文缩进到 XML 节点内部.

        Args:
            text: 节点正文.

        Returns:
            str: 已经补好缩进的文本. 空内容时返回空缩进占位.
        """

        if not text:
            return "    "
        return "\n".join(f"    {line}" for line in text.splitlines())


# endregion


__all__ = ["StickyNoteRenderer"]
