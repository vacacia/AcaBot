"""runtime.control.session_defaults 提供新建 Session 时的模板级默认配置。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


# region qq group defaults
def _qq_group_computer_default() -> dict[str, Any]:
    """返回 QQ 群聊 responding surface 的默认 computer 配置。"""

    return {
        "default": {
            "backend": "docker",
            "allow_exec": True,
            "allow_sessions": True,
        },
        "cases": [
            {
                "case_id": "bot_admin_host",
                "when": {"is_bot_admin": True},
                "use": {
                    "backend": "host",
                    "allow_exec": True,
                    "allow_sessions": True,
                },
            }
        ],
    }


def build_default_qq_group_surfaces() -> dict[str, Any]:
    """返回新建 `qq_group` session 使用的 responding surface 默认形状。"""

    computer = _qq_group_computer_default()
    return {
        "message.mention": {
            "admission": {"default": {"mode": "respond"}},
            "computer": deepcopy(computer),
        },
        "message.reply_to_bot": {
            "admission": {"default": {"mode": "respond"}},
            "computer": deepcopy(computer),
        },
        "message.plain": {
            "admission": {"default": {"mode": "record_only"}},
            "computer": deepcopy(computer),
        },
    }


def build_default_qq_group_visible_tools() -> list[str]:
    """返回新建 `qq_group` session 的默认前台工具基线。"""

    return [
        "Skill",
        "ask_backend",
        "bash",
        "delegate_subagent",
        "edit",
        "message",
        "read",
        "sticky_note_append",
        "sticky_note_read",
        "write",
        "refresh_extensions",
    ]


# endregion


__all__ = ["build_default_qq_group_surfaces", "build_default_qq_group_visible_tools"]
