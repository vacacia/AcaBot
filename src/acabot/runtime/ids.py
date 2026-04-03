"""runtime.ids 统一维护 conversation_id 和 thread_id 的 canonical helper."""

from __future__ import annotations

import re

from acabot.types import EventSource

_CANONICAL_CONVERSATION_ID_RE = re.compile(r"^qq:(group|user):([A-Za-z0-9._@!-]+)$")


def parse_conversation_id(conversation_id: str) -> tuple[str, str]:
    """解析 canonical conversation_id.

    Args:
        conversation_id: 目标外部对话容器 ID.

    Returns:
        tuple[str, str]: `(scope_kind, scope_value)`.

    Raises:
        ValueError: 当 conversation_id 不是受支持的 canonical 形式时抛出.
    """

    normalized = str(conversation_id or "").strip()
    match = _CANONICAL_CONVERSATION_ID_RE.fullmatch(normalized)
    if match is None:
        raise ValueError(
            "conversation_id must be a canonical qq:group:<id> or qq:user:<id>"
        )
    return match.group(1), match.group(2)


def build_event_source_from_conversation_id(
    conversation_id: str,
    *,
    actor_user_id: str,
) -> EventSource:
    """把 canonical conversation_id 转成可发送的 EventSource.

    Args:
        conversation_id: 目标外部对话容器 ID.
        actor_user_id: 当前 run 的 actor_user_id. 发群消息时保留为 sender user_id.

    Returns:
        EventSource: 可直接交给 Action.target 的目标地址.
    """

    scope_kind, scope_value = parse_conversation_id(conversation_id)
    if scope_kind == "group":
        return EventSource(
            platform="qq",
            message_type="group",
            user_id=str(actor_user_id or "").strip(),
            group_id=scope_value,
        )
    return EventSource(
        platform="qq",
        message_type="private",
        user_id=scope_value,
        group_id=None,
    )


def build_thread_id_from_conversation_id(conversation_id: str) -> str:
    """统一生成目标 runtime thread_id.

    v1 暂时沿用 canonical conversation_id 本身作为 thread_id,
    但字段语义仍然和 conversation_id 分开保留.
    """

    normalized = str(conversation_id or "").strip()
    parse_conversation_id(normalized)
    return normalized


__all__ = [
    "build_event_source_from_conversation_id",
    "build_thread_id_from_conversation_id",
    "parse_conversation_id",
]
