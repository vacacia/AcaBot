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
class EventAttachment:
    """统一 inbound 附件引用.

    Attributes:
        type (str): canonical 附件类型, 例如 `image` `file` `audio` `video`.
        source (str): 平台给出的可引用地址或文件标识.
        name (str): 附件名称. 平台未提供时为空.
        mime_type (str): MIME 类型. 平台未提供时为空.
        metadata (dict[str, Any]): 其他平台特定字段.
    """

    type: str
    source: str = ""
    name: str = ""
    mime_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplyReference:
    """统一 reply 引用信息.

    Attributes:
        message_id (str): 被引用的目标消息 ID.
        sender_user_id (str): 被引用消息的发送者 ID. 平台未提供时为空.
        text_preview (str): 被引用消息的简短文本摘要. 平台未提供时为空.
        metadata (dict[str, Any]): 其他平台特定字段.
    """

    message_id: str
    sender_user_id: str = ""
    text_preview: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


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
        message_subtype (str | None): 平台消息子类型. message 事件可用, 例如 `friend` `normal`.
        operator_id (str | None): 操作者 ID. recall 等事件会用到.
        subject_user_id (str | None): notice 事件的主体用户 ID, 例如被撤回消息的原作者, 被加入群的成员.
        target_message_id (str | None): 被操作的目标消息 ID.
        notice_type (str | None): 平台 notice 主类型. message 事件通常为空.
        notice_subtype (str | None): 平台 notice 子类型. 无子类型时为空.
        reply_to_message_id (str | None): 当前消息引用的上游消息 ID.
        reply_reference (ReplyReference | None): 当前消息的 reply 引用详情.
        mentioned_user_ids (list[str]): 当前消息里显式提及的用户 ID 列表.
        mentioned_everyone (bool): 当前消息是否显式 @全体.
        targets_self (bool): 当前事件是否明确指向 bot 自身.
        attachments (list[EventAttachment]): 当前消息携带的 canonical 附件列表.
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
    message_subtype: str | None = None
    operator_id: str | None = None
    subject_user_id: str | None = None
    target_message_id: str | None = None
    notice_type: str | None = None
    notice_subtype: str | None = None
    reply_to_message_id: str | None = None
    reply_reference: ReplyReference | None = None
    mentioned_user_ids: list[str] = field(default_factory=list)
    mentioned_everyone: bool = False
    targets_self: bool = False
    attachments: list[EventAttachment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_event: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """在兼容字段之间做最小同步.

        `reply_to_message_id` 是较早引入的兼容字段.
        新代码优先使用 `reply_reference`, 但两者会在初始化时保持一致.
        """

        if self.reply_reference is None and self.reply_to_message_id:
            self.reply_reference = ReplyReference(message_id=self.reply_to_message_id)
        elif self.reply_reference is not None and not self.reply_to_message_id:
            self.reply_to_message_id = self.reply_reference.message_id
        if self.is_private:
            self.targets_self = True

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

    @property
    def message_preview(self) -> str:
        """返回 message world 的 canonical 文本投影.

        Returns:
            一个适合 working memory 和 event log 的简短文本.
        """

        if not self.is_message:
            return ""

        parts: list[str] = []
        if self.reply_to_message_id:
            parts.append(f"[reply:{self.reply_to_message_id}]")
        if self.mentioned_user_ids:
            joined = ",".join(self.mentioned_user_ids)
            parts.append(f"[mentions:{joined}]")

        text = self.text.strip()
        if text:
            parts.append(text)

        if self.attachments:
            attachment_types = ",".join(attachment.type for attachment in self.attachments)
            parts.append(f"[attachments:{attachment_types}]")

        return " ".join(part for part in parts if part).strip()

    @property
    def notice_preview(self) -> str:
        """返回 notice world 的 canonical 文本投影.

        Returns:
            一个适合 working memory 和 event log 的 notice 文本.
        """

        if self.event_type == "poke":
            target_id = self.subject_user_id or str(self.metadata.get("target_id", "") or "")
            if target_id:
                return f"[notice:poke target={target_id}]"
            return "[notice:poke]"
        if self.event_type == "recall":
            target_id = self.target_message_id or ""
            subject_user_id = self.subject_user_id or ""
            if target_id and subject_user_id:
                return f"[notice:recall target={target_id} user={subject_user_id}]"
            if target_id:
                return f"[notice:recall target={target_id}]"
            return "[notice:recall]"
        if self.event_type in {"member_join", "member_leave"}:
            parts = [f"[notice:{self.event_type}"]
            if self.subject_user_id:
                parts.append(f"user={self.subject_user_id}")
            if self.notice_subtype:
                parts.append(f"sub_type={self.notice_subtype}")
            return " ".join(parts) + "]"
        if self.event_type == "admin_change":
            parts = ["[notice:admin_change"]
            if self.subject_user_id:
                parts.append(f"user={self.subject_user_id}")
            if self.notice_subtype:
                parts.append(f"sub_type={self.notice_subtype}")
            return " ".join(parts) + "]"
        if self.event_type == "file_upload":
            parts = ["[notice:file_upload"]
            if self.subject_user_id:
                parts.append(f"user={self.subject_user_id}")
            file_name = str(self.metadata.get("file_name", "") or "")
            if file_name:
                parts.append(f"file={file_name}")
            return " ".join(parts) + "]"
        return f"[notice:{self.event_type}]"

    @property
    def content_preview(self) -> str:
        """返回统一的事件内容投影.

        Returns:
            message 事件返回 `message_preview`, 其他事件返回 `notice_preview`.
        """

        if self.is_message:
            return self.message_preview
        return self.notice_preview

    @property
    def actor_tag(self) -> str:
        """返回用于 working memory 的 actor 标识前缀.

        Returns:
            形如 `[nickname/user_id]` 或 `[user_id]` 的前缀.
        """

        nickname = self.sender_nickname or ""
        user_id = self.source.user_id
        if nickname:
            return f"[{nickname}/{user_id}]"
        return f"[{user_id}]"

    @property
    def working_memory_text(self) -> str:
        """返回写入 working memory 的统一文本.

        Returns:
            一条带 actor 标识的 canonical 文本.
        """

        content = self.content_preview.strip()
        if not content:
            return self.actor_tag
        return f"{self.actor_tag} {content}".strip()

    def to_payload_json(self) -> dict[str, Any]:
        """把事件序列化成稳定的 canonical payload.

        Returns:
            可直接落到 `ChannelEventRecord.payload_json` 的结构化字典.
        """

        return {
            "source": {
                "platform": self.source.platform,
                "message_type": self.source.message_type,
                "user_id": self.source.user_id,
                "group_id": self.source.group_id,
            },
            "segments": [
                {"type": segment.type, "data": dict(segment.data)}
                for segment in self.segments
            ],
            "reply_to_message_id": self.reply_to_message_id,
            "reply_reference": self._reply_reference_payload(),
            "mentioned_user_ids": list(self.mentioned_user_ids),
            "mentioned_everyone": self.mentioned_everyone,
            "targets_self": self.targets_self,
            "attachments": [
                {
                    "type": attachment.type,
                    "source": attachment.source,
                    "name": attachment.name,
                    "mime_type": attachment.mime_type,
                    "metadata": dict(attachment.metadata),
                }
                for attachment in self.attachments
            ],
            "sender_nickname": self.sender_nickname,
            "sender_role": self.sender_role,
            "message_subtype": self.message_subtype,
            "operator_id": self.operator_id,
            "subject_user_id": self.subject_user_id,
            "target_message_id": self.target_message_id,
            "notice_type": self.notice_type,
            "notice_subtype": self.notice_subtype,
            "metadata": dict(self.metadata),
        }

    def _reply_reference_payload(self) -> dict[str, Any] | None:
        """把 reply_reference 序列化为 JSON 友好结构.

        Returns:
            reply payload, 未设置时返回 None.
        """

        if self.reply_reference is None:
            return None
        return {
            "message_id": self.reply_reference.message_id,
            "sender_user_id": self.reply_reference.sender_user_id,
            "text_preview": self.reply_reference.text_preview,
            "metadata": dict(self.reply_reference.metadata),
        }


# endregion
