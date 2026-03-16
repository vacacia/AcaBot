"""OneBot v11 消息段到 AcaBot canonical 结构的共享解析 helper."""

from __future__ import annotations

from typing import Any

from acabot.types import EventAttachment, ReplyReference


def extract_onebot_message_features(
    raw_segments: list[dict[str, Any]],
) -> tuple[ReplyReference | None, list[str], bool, list[EventAttachment]]:
    """从 OneBot message segments 提取 reply / mention / attachment."""

    reply_reference: ReplyReference | None = None
    mentioned_user_ids: list[str] = []
    mentioned_everyone = False
    attachments: list[EventAttachment] = []

    for segment in raw_segments:
        seg_type = str(segment.get("type", "") or "")
        data = dict(segment.get("data", {}) or {})

        if seg_type == "reply":
            reply_message_id = str(data.get("id", "") or "")
            if reply_message_id:
                reply_reference = ReplyReference(
                    message_id=reply_message_id,
                    sender_user_id=str(data.get("user_id") or data.get("qq") or ""),
                    text_preview=str(data.get("text", "") or ""),
                    metadata=dict(data),
                )
            continue

        if seg_type == "at":
            mentioned_user_id = str(data.get("qq", "") or "")
            if mentioned_user_id:
                if mentioned_user_id in {"all", "everyone"}:
                    mentioned_everyone = True
                mentioned_user_ids.append(mentioned_user_id)
            continue

        attachment = onebot_segment_to_attachment(seg_type, data)
        if attachment is not None:
            attachments.append(attachment)

    return reply_reference, mentioned_user_ids, mentioned_everyone, attachments


def onebot_segment_to_attachment(seg_type: str, data: dict[str, Any]) -> EventAttachment | None:
    """把单个 OneBot segment 投影成 canonical EventAttachment."""

    attachment_type_map = {
        "image": "image",
        "file": "file",
        "record": "audio",
        "video": "video",
    }
    attachment_type = attachment_type_map.get(seg_type)
    if attachment_type is None:
        return None

    source = str(
        data.get("url")
        or data.get("file")
        or data.get("path")
        or data.get("id")
        or ""
    )
    return EventAttachment(
        type=attachment_type,
        source=source,
        name=str(data.get("name", "") or ""),
        mime_type=str(data.get("mime", "") or ""),
        metadata=dict(data),
    )


def extract_onebot_text(raw_segments: list[dict[str, Any]]) -> str:
    """拼接 OneBot text segments 的纯文本内容."""

    parts: list[str] = []
    for segment in raw_segments:
        if str(segment.get("type", "") or "") != "text":
            continue
        data = dict(segment.get("data", {}) or {})
        text = str(data.get("text", "") or "")
        if text:
            parts.append(text)
    return "".join(parts).strip()
