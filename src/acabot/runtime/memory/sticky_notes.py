"""sticky note 受控服务层.

这个文件把 sticky note 文件真源收成稳定的业务动作.

关系图:

    builtin sticky note tools
              |
              v
       StickyNoteService
          |        |
          |        +--> StickyNoteRenderer
          |
          +-----------> StickyNoteFileStore

这里不负责决定 retrieval target.
它只负责:
- bot 的 `read + append`
- 人类控制面的整张 record 读写和删除
- 统一输入校验
"""

from __future__ import annotations

from dataclasses import dataclass
from .sticky_note_entities import StickyNoteEntityKind, normalize_sticky_note_entity_kind
from .file_backed.sticky_notes import StickyNoteFileStore, StickyNoteRecord
from .sticky_note_renderer import StickyNoteRenderer


# region service
@dataclass(slots=True)
class StickyNoteService:
    """sticky note 的正式服务层.

    Attributes:
        store (StickyNoteFileStore): sticky note 文件真源.
        renderer (StickyNoteRenderer): 完整文本渲染器.
    """

    store: StickyNoteFileStore
    renderer: StickyNoteRenderer

    async def read_note(self, entity_ref: str) -> dict[str, object]:
        """读取一张实体便签的完整文本视图.

        Args:
            entity_ref: 目标实体引用.

        Returns:
            dict[str, object]: 目标不存在时返回 `{"exists": False}`,
            存在时返回 `{"exists": True, "combined_text": ...}`.
        """

        record = self.store.load_record(entity_ref)
        if record is None:
            return {"exists": False}
        return {
            "exists": True,
            "combined_text": self.renderer.render_combined_text(record),
        }

    async def append_note(self, entity_ref: str, text: str) -> dict[str, object]:
        """向实体便签的 editable 区追加一条观察.

        Args:
            entity_ref: 目标实体引用.
            text: 待追加的单行文本.

        Returns:
            dict[str, object]: 简洁成功结果.

        Raises:
            ValueError: 当 `text` 为空、纯空白或包含换行时抛出.
        """

        normalized_text = self._normalize_append_text(text)
        self.store.append_editable_text(entity_ref, normalized_text)
        return {"ok": True}

    async def load_record(self, entity_ref: str) -> StickyNoteRecord | None:
        """读取一张完整的 sticky note record.

        Args:
            entity_ref: 目标实体引用.

        Returns:
            StickyNoteRecord | None: 不存在时返回 `None`.
        """

        return self.store.load_record(entity_ref)

    async def save_record(self, record: StickyNoteRecord) -> StickyNoteRecord:
        """保存一张完整的 sticky note record.

        Args:
            record: 待保存的记录对象.

        Returns:
            StickyNoteRecord: 保存后的最新记录.
        """

        return self.store.save_record(record)

    async def create_record(self, entity_ref: str) -> StickyNoteRecord:
        """创建一张空的实体便签.

        Args:
            entity_ref: 目标实体引用.

        Returns:
            StickyNoteRecord: 新建后的空记录.
        """

        return self.store.create_record(entity_ref)

    async def delete_record(self, entity_ref: str) -> bool:
        """删除一张实体便签.

        Args:
            entity_ref: 目标实体引用.

        Returns:
            bool: 目标存在并已删除时返回 `True`.
        """

        return self.store.delete_record(entity_ref)

    async def list_records(
        self,
        *,
        entity_kind: StickyNoteEntityKind | None = None,
    ) -> list[StickyNoteRecord]:
        """按实体分类列出 sticky note records.

        Args:
            entity_kind: 可选分类过滤.

        Returns:
            list[StickyNoteRecord]: 命中的记录列表.
        """

        normalized_entity_kind = (
            normalize_sticky_note_entity_kind(entity_kind)
            if entity_kind is not None
            else None
        )
        return self.store.list_records(entity_kind=normalized_entity_kind)

    @staticmethod
    def _normalize_append_text(text: str) -> str:
        """校验 bot 追加文本.

        Args:
            text: 原始追加文本.

        Returns:
            str: 规范化后的单行文本.

        Raises:
            ValueError: 当文本为空、纯空白或包含换行时抛出.
        """

        normalized_text = str(text or "").strip()
        if not normalized_text:
            raise ValueError("sticky note append text cannot be blank")
        if "\n" in normalized_text or "\r" in normalized_text:
            raise ValueError("sticky note append text must be single-line")
        return normalized_text


# endregion


__all__ = ["StickyNoteService", "StickyNoteRecord"]
