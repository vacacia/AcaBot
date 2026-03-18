"""runtime.control.session_templates 定义 Session 产品模板目录."""

from __future__ import annotations

from dataclasses import dataclass


SESSION_EVENT_TYPE_OPTIONS = [
    "message",
    "message_mention",
    "message_reply",
    "poke",
    "recall",
    "member_join",
    "member_leave",
    "admin_change",
    "file_upload",
    "friend_added",
    "mute_change",
    "honor_change",
    "title_change",
    "lucky_king",
]

SESSION_EVENT_LABELS = {
    "message": "普通消息",
    "message_mention": "被艾特",
    "message_reply": "引用回复",
    "poke": "戳一戳",
    "recall": "消息撤回",
    "member_join": "成员加入",
    "member_leave": "成员离开",
    "admin_change": "管理员变更",
    "file_upload": "文件上传",
    "friend_added": "新增好友",
    "mute_change": "禁言变更",
    "honor_change": "群荣誉变更",
    "title_change": "头衔变更",
    "lucky_king": "运气王",
}

SESSION_MESSAGE_FILTER_OPTIONS = {
    "all": "全部消息",
    "mention_only": "仅被艾特",
    "reply_only": "仅被引用",
    "mention_or_reply": "被艾特或被引用",
}


@dataclass(frozen=True, slots=True)
class SessionChannelTemplate:
    """一条 Session 渠道模板定义."""

    template_id: str
    label: str
    scope_prefixes: tuple[str, ...]
    event_types: tuple[str, ...]
    message_filter_options: tuple[str, ...]
    default_message_filter: str = "all"

    def to_dict(self) -> dict[str, object]:
        """把模板转换成 WebUI 可消费的字典."""

        return {
            "template_id": self.template_id,
            "label": self.label,
            "event_types": list(public_event_types_for_template(self)),
            "message_filter_options": [
                {
                    "value": option,
                    "label": SESSION_MESSAGE_FILTER_OPTIONS.get(option, option),
                }
                for option in self.message_filter_options
            ],
            "default_message_filter": self.default_message_filter,
        }


SESSION_CHANNEL_TEMPLATES = {
    "qq_private": SessionChannelTemplate(
        template_id="qq_private",
        label="QQ 私聊",
        scope_prefixes=("qq:user:", "qq:private:"),
        event_types=("message", "poke", "recall", "friend_added"),
        message_filter_options=("all",),
        default_message_filter="all",
    ),
    "qq_group": SessionChannelTemplate(
        template_id="qq_group",
        label="QQ群聊",
        scope_prefixes=("qq:group:",),
        event_types=(
            "message",
            "poke",
            "recall",
            "member_join",
            "member_leave",
            "admin_change",
            "file_upload",
            "mute_change",
            "honor_change",
            "title_change",
            "lucky_king",
        ),
        message_filter_options=("all", "mention_only", "reply_only", "mention_or_reply"),
        default_message_filter="mention_or_reply",
    ),
    "custom": SessionChannelTemplate(
        template_id="custom",
        label="自定义",
        scope_prefixes=(),
        event_types=tuple(SESSION_EVENT_TYPE_OPTIONS),
        message_filter_options=("all", "mention_only", "reply_only", "mention_or_reply"),
        default_message_filter="all",
    ),
}


def public_event_types_for_template(template: SessionChannelTemplate) -> tuple[str, ...]:
    """返回某个模板在前端应暴露的事件类型列表."""

    public_event_types: list[str] = []
    split_message = len(template.message_filter_options) > 1
    for event_type in template.event_types:
        if event_type != "message" or not split_message:
            public_event_types.append(event_type)
            continue
        public_event_types.extend(("message", "message_mention", "message_reply"))
    return tuple(public_event_types)


def list_session_channel_templates() -> list[dict[str, object]]:
    """返回全部 Session 渠道模板定义."""

    return [SESSION_CHANNEL_TEMPLATES[key].to_dict() for key in ("qq_private", "qq_group", "custom")]


def get_session_channel_template(template_id: str, *, channel_scope: str = "") -> SessionChannelTemplate:
    """按模板 ID 或 channel scope 返回 Session 渠道模板."""

    normalized_id = str(template_id or "").strip()
    if normalized_id and normalized_id in SESSION_CHANNEL_TEMPLATES:
        return SESSION_CHANNEL_TEMPLATES[normalized_id]
    inferred = default_session_channel_template_id(channel_scope)
    return SESSION_CHANNEL_TEMPLATES[inferred]


def default_session_channel_template_id(channel_scope: str) -> str:
    """根据 channel scope 推断默认 Session 渠道模板."""

    normalized_scope = str(channel_scope or "").strip()
    for template in SESSION_CHANNEL_TEMPLATES.values():
        if any(normalized_scope.startswith(prefix) for prefix in template.scope_prefixes):
            return template.template_id
    return "custom"


__all__ = [
    "SESSION_CHANNEL_TEMPLATES",
    "SESSION_EVENT_LABELS",
    "SESSION_EVENT_TYPE_OPTIONS",
    "SESSION_MESSAGE_FILTER_OPTIONS",
    "SessionChannelTemplate",
    "default_session_channel_template_id",
    "get_session_channel_template",
    "list_session_channel_templates",
    "public_event_types_for_template",
]
