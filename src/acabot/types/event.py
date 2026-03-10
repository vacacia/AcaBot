"""types.event 定义 runtime world 使用的统一 inbound event.

当前设计目标:
- `message` 和 `notice` 共用一份稳定对象
- 先提供 canonical 字段
- 同时保留 raw platform payload, 避免平台扩展信息丢失
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# region inbound消息
@dataclass
class MsgSegment:
    """统一消息片段.

    Attributes:
        type (str): canonical segment 类型.
        data (dict[str, Any]): segment 负载.
    """

    type: str
    data: dict[str, Any]


@dataclass
class EventSource:
    """事件来源地址.

    Attributes:
        platform (str): 平台名, 例如 `qq`.
        message_type (str): 会话类型, 例如 `private` 或 `group`.
        user_id (str): 当前事件主发送者 ID.
        group_id (str | None): 群 ID. 私聊时为空.
    """

    platform: str
    message_type: str       # "private" | "group"
    user_id: str
    group_id: str | None


@dataclass
class StandardEvent:
    """统一 inbound event.

    Attributes:
        event_id (str): 当前事件唯一 ID.
        event_type (str): canonical 事件类型, 例如 `message`, `poke`, `recall`.
        platform (str): 平台名.
        timestamp (int): 事件时间戳.
        source (EventSource): 当前事件来源地址.
        segments (list[MsgSegment]): message world 的消息段列表. notice event 通常为空.
        raw_message_id (str): 关联的平台 message ID. notice event 可为空.
        sender_nickname (str): 发送者昵称. notice event 可为空.
        sender_role (str | None): 群角色信息.
        operator_id (str | None): 操作者 ID. recall 等事件会用到.
        target_message_id (str | None): 被操作的目标消息 ID.
        metadata (dict[str, Any]): canonical 扩展字段.
        raw_event (dict[str, Any]): 平台原始 payload.
    """

    event_id: str
    event_type: str
    platform: str
    timestamp: int
    source: EventSource
    segments: list[MsgSegment]
    raw_message_id: str
    sender_nickname: str
    sender_role: str | None
    operator_id: str | None = None
    target_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_event: dict[str, Any] = field(default_factory=dict)

    @property
    def is_private(self) -> bool:
        """返回当前事件是否来自私聊."""

        return self.source.message_type == "private"

    @property
    def is_group(self) -> bool:
        """返回当前事件是否来自群聊."""

        return self.source.message_type == "group"

    @property
    def is_message(self) -> bool:
        """返回当前事件是否是消息事件."""

        return self.event_type == "message"

    @property
    def is_notice(self) -> bool:
        """返回当前事件是否是非消息 notice 事件."""

        return self.event_type != "message"

    @property
    def session_key(self) -> str:
        """返回旧世界兼容使用的 session_key."""

        if self.is_group:
            return f"{self.platform}:group:{self.source.group_id}"
        return f"{self.platform}:user:{self.source.user_id}"

    @property
    def text(self) -> str:
        """提取 text segment 拼接后的纯文本."""

        parts = []
        for seg in self.segments:
            if seg.type == "text":
                parts.append(seg.data.get("text", ""))
        return "".join(parts)


# endregion
