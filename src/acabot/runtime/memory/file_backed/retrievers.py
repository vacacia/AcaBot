"""文件型记忆适配器.

这个文件把文件真源包装成统一的 `MemoryBlock`.

关系图:

    SoulSource --------------------> SelfFileRetriever ----------+
                                                                 |
                                                                 v
    StickyNoteFileStore + StickyNoteRenderer -> StickyNoteRetriever -> MemoryBlock

这里不负责决定 sticky note target.
它只负责读取已经选好的 target, 并把结果转成统一 block.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...soul import SoulSource
from ..memory_broker import MemoryAssemblySpec, MemoryBlock, SharedMemoryRetrievalRequest
from ..sticky_note_entities import derive_sticky_note_entity_kind
from ..sticky_note_renderer import StickyNoteRenderer
from .sticky_notes import StickyNoteFileStore


# region self
@dataclass(slots=True)
class SelfFileRetriever:
    """把 `/self` 文件内容适配成统一 MemoryBlock.

    Attributes:
        source (SoulSource): `/self` 文件真源.
        max_daily_files (int): 最多拼接多少份 daily 文件.
    """

    source: SoulSource
    max_daily_files: int = 2

    async def __call__(self, request: SharedMemoryRetrievalRequest) -> list[MemoryBlock]:
        """读取 `/self` 并转成 memory block.

        Args:
            request: 当前共享 retrieval request.

        Returns:
            list[MemoryBlock]: `/self` 对应的 block 列表.
        """

        _ = request
        content = self.source.build_recent_context_text(max_daily_files=self.max_daily_files).strip()
        if not content:
            return []
        return [
            MemoryBlock(
                content=content,
                source="self",
                scope="global",
                source_ids=["self:recent"],
                assembly=MemoryAssemblySpec(
                    target_slot="message_prefix",
                    priority=900,
                ),
                metadata={
                    "source_backend": "file_backed",
                },
            )
        ]


# endregion


# region sticky note
@dataclass(slots=True)
class StickyNoteRetriever:
    """按 `entity_ref` target 读取 sticky note 并转成 `MemoryBlock`.

    Attributes:
        store (StickyNoteFileStore): sticky note 文件真源.
        renderer (StickyNoteRenderer): 完整文本渲染器.
    """

    store: StickyNoteFileStore
    renderer: StickyNoteRenderer

    async def __call__(self, request: SharedMemoryRetrievalRequest) -> list[MemoryBlock]:
        """读取当前 request 指定的 sticky note targets.

        Args:
            request: 当前共享 retrieval request.

        Returns:
            list[MemoryBlock]: 命中的 sticky note block 列表.
        """

        sticky_note_targets = [
            str(value)
            for value in list(request.metadata.get("sticky_note_targets", []) or [])
            if str(value or "").strip()
        ]
        if not sticky_note_targets:
            return []

        blocks: list[MemoryBlock] = []
        for entity_ref in sticky_note_targets:
            record = self.store.load_record(entity_ref)
            if record is None:
                continue
            if not (record.readonly or "").strip() and not (record.editable or "").strip():
                continue
            entity_kind = derive_sticky_note_entity_kind(record.entity_ref)
            blocks.append(
                MemoryBlock(
                    content=self.renderer.render_combined_text(record),
                    source="sticky_notes",
                    scope=entity_kind,
                    source_ids=[f"sticky_note:{record.entity_ref}"],
                    assembly=MemoryAssemblySpec(
                        target_slot="message_prefix",
                        priority=800,
                    ),
                    metadata={
                        "entity_ref": record.entity_ref,
                        "entity_kind": entity_kind,
                        "updated_at": record.updated_at,
                        "source_backend": "file_backed",
                    },
                )
            )
        return blocks


# endregion


__all__ = ["SelfFileRetriever", "StickyNoteRetriever"]
