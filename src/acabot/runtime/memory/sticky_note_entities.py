"""sticky note 实体引用解析 helper.

这个文件只负责一件事: 把 sticky note 相关的 `entity_ref` 解析成
稳定的 `entity_kind` 和安全目录信息.

关系图:

    StickyNoteFileStore
            |
            v
    parse_sticky_note_entity_ref()
            ^
            |
    StickyNoteService / StickyNoteRenderer / StickyNoteRetriever / ControlPlane

这里不负责读写文件, 也不负责拼 prompt 文本.
它只负责:
- 校验 `entity_ref` 是否合法
- 从 `entity_ref` 派生 `entity_kind = user | conversation`
- 拒绝 thread_id / session_id / 路径穿越类输入
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

StickyNoteEntityKind = Literal["user", "conversation"]


_ALLOWED_ENTITY_REF_PATTERN = re.compile(r"^[A-Za-z0-9:_.@!\-]+$")
_CONVERSATION_SEGMENTS = {
    "channel",
    "conversation",
    "dm",
    "group",
    "private",
    "room",
}


# region records
@dataclass(slots=True, frozen=True)
class ParsedStickyNoteEntityRef:
    """一条已经通过 sticky note 边界校验的实体引用.

    Attributes:
        entity_ref (str): 原始实体引用.
        entity_kind (StickyNoteEntityKind): 从 `entity_ref` 派生出的实体分类.
        storage_directory_name (str): 可以直接拿来做目录名的稳定名字.
    """

    entity_ref: str
    entity_kind: StickyNoteEntityKind
    storage_directory_name: str


# endregion


# region parser
def parse_sticky_note_entity_ref(entity_ref: str) -> ParsedStickyNoteEntityRef:
    """校验并解析 sticky note 的 `entity_ref`.

    Args:
        entity_ref: 待解析的实体引用.

    Returns:
        ParsedStickyNoteEntityRef: 通过校验后的解析结果.

    Raises:
        ValueError: 当 `entity_ref` 非法, 或不能稳定派生到 `user/conversation` 时抛出.
    """

    normalized_ref = str(entity_ref or "").strip()
    if not normalized_ref:
        raise ValueError("entity_ref is required")
    if normalized_ref.startswith("thread:"):
        raise ValueError("thread_id cannot be used as sticky note entity_ref")
    if normalized_ref.startswith("session:"):
        raise ValueError("session_id cannot be used as sticky note entity_ref")
    if "/" in normalized_ref or "\\" in normalized_ref or ".." in normalized_ref:
        raise ValueError("entity_ref contains invalid path characters")
    if _ALLOWED_ENTITY_REF_PATTERN.fullmatch(normalized_ref) is None:
        raise ValueError("entity_ref contains unsupported characters")

    parts = normalized_ref.split(":")
    if len(parts) < 3:
        raise ValueError("entity_ref must use canonical ref format")

    entity_segment = str(parts[1] or "").strip().lower()
    if entity_segment == "user":
        entity_kind: StickyNoteEntityKind = "user"
    elif entity_segment in _CONVERSATION_SEGMENTS:
        entity_kind = "conversation"
    else:
        raise ValueError("entity_ref cannot be mapped to sticky note entity_kind")

    return ParsedStickyNoteEntityRef(
        entity_ref=normalized_ref,
        entity_kind=entity_kind,
        storage_directory_name=normalized_ref,
    )


def derive_sticky_note_entity_kind(entity_ref: str) -> StickyNoteEntityKind:
    """从 `entity_ref` 派生 sticky note 的 `entity_kind`.

    Args:
        entity_ref: 待派生的实体引用.

    Returns:
        Literal["user", "conversation"]: 对应的实体分类.
    """

    return parse_sticky_note_entity_ref(entity_ref).entity_kind


def normalize_sticky_note_entity_kind(entity_kind: str) -> StickyNoteEntityKind:
    """校验并规范化 sticky note 的实体分类.

    Args:
        entity_kind: 待校验的实体分类.

    Returns:
        StickyNoteEntityKind: 规范化后的实体分类.

    Raises:
        ValueError: 当分类不是 `user` 或 `conversation` 时抛出.
    """

    normalized_kind = str(entity_kind or "").strip()
    if normalized_kind not in {"user", "conversation"}:
        raise ValueError(f"invalid sticky note entity_kind: {entity_kind}")
    return normalized_kind


# endregion


__all__ = [
    "ParsedStickyNoteEntityRef",
    "StickyNoteEntityKind",
    "derive_sticky_note_entity_kind",
    "normalize_sticky_note_entity_kind",
    "parse_sticky_note_entity_ref",
]
