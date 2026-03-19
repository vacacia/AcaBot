"""runtime.control WebUI 目录相关常量和小型组装 helper."""

from __future__ import annotations

from .session_templates import (
    SESSION_EVENT_LABELS,
    SESSION_EVENT_TYPE_OPTIONS,
    SESSION_MESSAGE_FILTER_OPTIONS,
    list_session_channel_templates,
)

UI_EVENT_TYPE_OPTIONS = [
    "message",
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

UI_MESSAGE_SUBTYPE_OPTIONS = [
    "friend",
    "normal",
]

UI_NOTICE_TYPE_OPTIONS = [
    "notify",
    "group_recall",
    "friend_recall",
    "group_increase",
    "group_decrease",
    "group_admin",
    "group_upload",
    "friend_add",
    "group_ban",
]

UI_NOTICE_SUBTYPE_OPTIONS = [
    "poke",
    "invite",
    "kick",
    "kick_me",
    "set",
    "unset",
    "ban",
    "lift_ban",
    "lucky_king",
    "talkative",
    "performer",
    "emotion",
    "title",
]


def build_ui_options(*, api_key_env_names: list[str]) -> dict[str, object]:
    """返回 WebUI 通用选择项."""

    return {
        "provider_kinds": ["openai_compatible", "anthropic", "google_gemini"],
        "binding_target_types": ["global", "agent", "system"],
        "run_modes": ["respond", "record_only", "silent_drop"],
        "event_types": list(UI_EVENT_TYPE_OPTIONS),
        "event_type_labels": dict(SESSION_EVENT_LABELS),
        "session_channel_templates": list_session_channel_templates(),
        "session_message_filters": [
            {"value": value, "label": label}
            for value, label in SESSION_MESSAGE_FILTER_OPTIONS.items()
        ],
        "message_subtypes": list(UI_MESSAGE_SUBTYPE_OPTIONS),
        "notice_types": list(UI_NOTICE_TYPE_OPTIONS),
        "notice_subtypes": list(UI_NOTICE_SUBTYPE_OPTIONS),
        "sender_roles": ["owner", "admin", "member"],
        "computer_backends": ["host", "docker"],
        "computer_network_modes": ["enabled", "disabled"],
        "api_key_env_names": sorted(api_key_env_names),
    }
