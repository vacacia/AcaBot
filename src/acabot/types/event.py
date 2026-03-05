"""
数据来源只有一个: NapCat Gateway 的 translate() 方法, 信任传入数据正确
    - 不需要 Pydantic
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MsgSegment:
    type: str
    data: dict[str, Any]


@dataclass
class EventSource:
    platform: str
    message_type: str       # "private" | "group"
    user_id: str
    group_id: str | None


@dataclass
class StandardEvent:
    event_id: str
    event_type: str
    platform: str
    timestamp: int
    source: EventSource
    segments: list[MsgSegment]
    raw_message_id: str
    sender_nickname: str
    sender_role: str | None

    @property
    def is_private(self) -> bool:
        return self.source.message_type == "private"

    @property
    def is_group(self) -> bool:
        return self.source.message_type == "group"

    @property
    def session_key(self) -> str:
        if self.is_group:
            return f"{self.platform}:group:{self.source.group_id}"
        return f"{self.platform}:user:{self.source.user_id}"

    @property
    def text(self) -> str:
        parts = []
        for seg in self.segments:
            if seg.type == "text":
                parts.append(seg.data.get("text", ""))
        return "".join(parts)
