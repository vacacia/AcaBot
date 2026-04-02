"""sticky note 文件真源.

这个文件负责把实体便签落到运行时目录中.

关系图:

    StickyNoteService / StickyNoteRetriever / RuntimeControlPlane
                            |
                            v
                     StickyNoteFileStore
                            |
                            v
         runtime_data/sticky_notes/<entity_kind>/<entity_ref>/
                |- readonly.md
                `- editable.md

这里不负责工具语义, 也不负责 prompt 文本渲染.
它只负责:
- 校验 `entity_ref`
- 组织目录结构
- 读取和保存 `StickyNoteRecord`
- 追加 editable 区内容
- 列出实体便签
- 聚合 `updated_at`
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from ..sticky_note_entities import (
    ParsedStickyNoteEntityRef,
    StickyNoteEntityKind,
    normalize_sticky_note_entity_kind,
    parse_sticky_note_entity_ref,
)


# region helpers
def _path_mtime(path: Path) -> int:
    """读取一个文件路径的修改时间.

    Args:
        path: 目标文件路径.

    Returns:
        int: 秒级时间戳. 文件不存在或读取失败时返回 0.
    """

    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


# endregion


# region records
@dataclass(slots=True)
class StickyNoteRecord:
    """一张实体 sticky note 的正式记录对象.

    Attributes:
        entity_ref (str): 这张便签绑定的正式实体引用.
        readonly (str): 人工维护的高可信内容.
        editable (str): bot 可追加的观察内容.
        updated_at (int): 整张便签最后一次更新时间.
    """

    entity_ref: str
    readonly: str = ""
    editable: str = ""
    updated_at: int = 0


# endregion


# region store
@dataclass(slots=True)
class StickyNoteFileStore:
    """基于文件系统的 sticky note 真源层.

    Attributes:
        root_dir (Path): sticky note 根目录.
    """

    root_dir: Path

    def __post_init__(self) -> None:
        """初始化 sticky note 根目录."""

        self.root_dir = Path(self.root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        for entity_kind in ("user", "conversation"):
            (self.root_dir / entity_kind).mkdir(parents=True, exist_ok=True)

    def load_record(self, entity_ref: str) -> StickyNoteRecord | None:
        """读取一张实体便签.

        Args:
            entity_ref: 目标实体引用.

        Returns:
            StickyNoteRecord | None: 命中的记录. 不存在时返回 `None`.
        """

        parsed_entity = parse_sticky_note_entity_ref(entity_ref)
        note_root = self._note_root(parsed_entity)
        if not note_root.exists() or not note_root.is_dir():
            return None
        readonly_path = note_root / "readonly.md"
        editable_path = note_root / "editable.md"
        readonly_text = readonly_path.read_text(encoding="utf-8") if readonly_path.exists() else ""
        editable_text = editable_path.read_text(encoding="utf-8") if editable_path.exists() else ""
        return StickyNoteRecord(
            entity_ref=parsed_entity.entity_ref,
            readonly=readonly_text,
            editable=editable_text,
            updated_at=max(_path_mtime(readonly_path), _path_mtime(editable_path)),
        )

    def save_record(self, record: StickyNoteRecord) -> StickyNoteRecord:
        """保存一张完整的 sticky note 记录.

        Args:
            record: 待保存的记录对象.

        Returns:
            StickyNoteRecord: 保存后的最新记录.
        """

        parsed_entity = parse_sticky_note_entity_ref(record.entity_ref)
        note_root = self._ensure_note_root(parsed_entity)
        (note_root / "readonly.md").write_text(str(record.readonly or ""), encoding="utf-8")
        (note_root / "editable.md").write_text(str(record.editable or ""), encoding="utf-8")
        saved_record = self.load_record(parsed_entity.entity_ref)
        if saved_record is None:
            raise RuntimeError("sticky note save failed")
        return saved_record

    def create_record(self, entity_ref: str) -> StickyNoteRecord:
        """创建一张空的实体便签.

        Args:
            entity_ref: 目标实体引用.

        Returns:
            StickyNoteRecord: 新建后的空记录. 如果目标已经存在, 直接返回现有记录.
        """

        existing_record = self.load_record(entity_ref)
        if existing_record is not None:
            return existing_record
        return self.save_record(StickyNoteRecord(entity_ref=entity_ref))

    def append_editable_text(self, entity_ref: str, text: str) -> StickyNoteRecord:
        """向 editable 区追加一段文本.

        Args:
            entity_ref: 目标实体引用.
            text: 要追加的文本.

        Returns:
            StickyNoteRecord: 追加后的记录.
        """

        current_record = self.load_record(entity_ref)
        if current_record is None:
            current_record = StickyNoteRecord(entity_ref=entity_ref)
        normalized_existing = (current_record.editable or "").rstrip()
        normalized_text = str(text or "").strip()
        if normalized_existing:
            current_record.editable = f"{normalized_existing}\n\n{normalized_text}"
        else:
            current_record.editable = normalized_text
        return self.save_record(current_record)

    def delete_record(self, entity_ref: str) -> bool:
        """删除一张实体便签.

        Args:
            entity_ref: 目标实体引用.

        Returns:
            bool: 目标存在并且已经删除时返回 `True`.
        """

        parsed_entity = parse_sticky_note_entity_ref(entity_ref)
        note_root = self._note_root(parsed_entity)
        if not note_root.exists():
            return False
        shutil.rmtree(note_root)
        return True

    def list_records(
        self,
        *,
        entity_kind: StickyNoteEntityKind | None = None,
    ) -> list[StickyNoteRecord]:
        """列出当前 sticky note 文件真源里的记录.

        Args:
            entity_kind: 可选的实体分类过滤. 不传时返回全部记录.

        Returns:
            list[StickyNoteRecord]: 当前命中的记录列表.
        """

        target_kinds = [normalize_sticky_note_entity_kind(entity_kind)] if entity_kind else ["user", "conversation"]
        records: list[StickyNoteRecord] = []
        for current_kind in target_kinds:
            kind_root = self.root_dir / str(current_kind)
            if not kind_root.exists():
                continue
            for note_dir in sorted(kind_root.iterdir(), key=lambda item: item.name):
                if not note_dir.is_dir():
                    continue
                loaded_record = self.load_record(note_dir.name)
                if loaded_record is None:
                    continue
                records.append(loaded_record)
        return sorted(records, key=lambda item: (-item.updated_at, item.entity_ref))

    # region path helpers
    def _note_root(self, parsed_entity: ParsedStickyNoteEntityRef) -> Path:
        """返回一张 note 的目录路径.

        Args:
            parsed_entity: 已解析的实体引用.

        Returns:
            Path: note 根目录.
        """

        path = (
            self.root_dir
            / parsed_entity.entity_kind
            / parsed_entity.storage_directory_name
        ).resolve()
        try:
            path.relative_to(self.root_dir)
        except ValueError as exc:
            raise ValueError("invalid sticky note path") from exc
        return path

    def _ensure_note_root(self, parsed_entity: ParsedStickyNoteEntityRef) -> Path:
        """确保 note 根目录存在.

        Args:
            parsed_entity: 已解析的实体引用.

        Returns:
            Path: 已存在的 note 根目录.
        """

        note_root = self._note_root(parsed_entity)
        note_root.mkdir(parents=True, exist_ok=True)
        return note_root

    # endregion


# endregion


__all__ = ["StickyNoteFileStore", "StickyNoteRecord"]
