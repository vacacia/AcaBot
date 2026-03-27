"""runtime.memory.long_term_memory.fact_ids 负责事实身份和窗口锚点.

这个模块只做四件事:
- 把 `ConversationFact` 规范成正式 `fact_id`
- 把 `fact_ids` 收成 canonical 集合
- 给当前提取窗口分配本地锚点
- 根据 `conversation_id + canonical fact_ids` 生成稳定 `entry_id`
"""

from __future__ import annotations

from typing import Iterable
import uuid

from ..conversation_facts import ConversationFact
from .contracts import ConversationFactAnchorMap

LONG_TERM_MEMORY_NAMESPACE = uuid.UUID("8b4d31e0-0ac2-58a9-9c1f-90c7e05c19b6")


# region helpers
def _normalize_text(value: str) -> str:
    """清理一个字符串的首尾空白.

    Args:
        value: 原始字符串.

    Returns:
        去掉首尾空白后的字符串.
    """

    return str(value or "").strip()


def normalize_fact_ids(fact_ids: Iterable[str]) -> list[str]:
    """把 fact_id 列表收成 canonical 集合.

    Args:
        fact_ids: 原始 fact_id 列表.

    Returns:
        去空、去重、排序后的 fact_id 列表.
    """

    return sorted({text for text in (_normalize_text(item) for item in list(fact_ids or [])) if text})


# endregion


# region public helpers
def build_fact_id_from_conversation_fact(fact: ConversationFact) -> str:
    """把一条对话事实规范成正式 fact_id.

    Args:
        fact: 当前对话事实.

    Returns:
        规范化后的正式 fact_id.

    Raises:
        ValueError: 当来源类型不受支持时抛出.
    """

    if fact.source_kind == "channel_event":
        return f"e:{_normalize_text(fact.source_id)}"
    if fact.source_kind == "message":
        return f"m:{_normalize_text(fact.source_id)}"
    raise ValueError(f"unsupported conversation fact source_kind: {fact.source_kind}")


def build_memory_entry_id(conversation_id: str, fact_ids: Iterable[str]) -> str:
    """根据对话容器和 canonical fact 集合生成稳定 entry_id.

    Args:
        conversation_id: 所属对话容器.
        fact_ids: 这条记忆依赖的事实集合.

    Returns:
        稳定的确定性 `entry_id`.
    """

    canonical_fact_ids = normalize_fact_ids(fact_ids)
    payload = f"{_normalize_text(conversation_id)}|{'|'.join(canonical_fact_ids)}"
    return str(uuid.uuid5(LONG_TERM_MEMORY_NAMESPACE, payload))


def build_fact_anchor_map(fact_ids: Iterable[str]) -> ConversationFactAnchorMap:
    """给当前窗口里的事实集合分配本地锚点.

    Args:
        fact_ids: 当前窗口里的正式 fact_id 列表.

    Returns:
        一份窗口级锚点映射.
    """

    anchors_by_fact_id: dict[str, str] = {}
    fact_ids_by_anchor: dict[str, str] = {}
    for fact_id in list(fact_ids or []):
        normalized_fact_id = _normalize_text(fact_id)
        if not normalized_fact_id or normalized_fact_id in anchors_by_fact_id:
            continue
        anchor_id = f"f{len(anchors_by_fact_id) + 1}"
        anchors_by_fact_id[normalized_fact_id] = anchor_id
        fact_ids_by_anchor[anchor_id] = normalized_fact_id
    return ConversationFactAnchorMap(
        anchors_by_fact_id=anchors_by_fact_id,
        fact_ids_by_anchor=fact_ids_by_anchor,
    )


def resolve_anchor_ids(
    anchor_map: ConversationFactAnchorMap,
    anchor_ids: Iterable[str],
) -> list[str]:
    """把窗口级锚点列表回填成正式 fact_id 列表.

    Args:
        anchor_map: 当前窗口的锚点映射.
        anchor_ids: 模型返回的本地锚点列表.

    Returns:
        去空、去重、保序后的正式 fact_id 列表.

    Raises:
        ValueError: 当 anchor 不存在于当前窗口时抛出.
    """

    resolved_fact_ids: list[str] = []
    for anchor_id in list(anchor_ids or []):
        normalized_anchor_id = _normalize_text(anchor_id)
        if not normalized_anchor_id:
            continue
        fact_id = anchor_map.fact_id_for(normalized_anchor_id)
        if fact_id is None:
            raise ValueError(f"unknown fact anchor: {normalized_anchor_id}")
        if fact_id not in resolved_fact_ids:
            resolved_fact_ids.append(fact_id)
    return resolved_fact_ids


# endregion


__all__ = [
    "LONG_TERM_MEMORY_NAMESPACE",
    "build_fact_anchor_map",
    "build_fact_id_from_conversation_fact",
    "build_memory_entry_id",
    "normalize_fact_ids",
    "resolve_anchor_ids",
]
