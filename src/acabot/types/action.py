

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .event import EventSource


class ActionType(str, Enum):
    """Bot 能执行的所有操作类型.

    继承 str 使枚举值本身就是字符串, 序列化时无需 .value.
    扩展新操作: 增加枚举值 + Gateway 里处理对应 API.
    """
    # 消息类
    SEND_TEXT = "send_text"
    SEND_SEGMENTS = "send_segments"
    RECALL = "recall"
    # 群管理类
    GROUP_BAN = "group_ban"
    GROUP_KICK = "group_kick"
    # 反应类 — 不产生实际消息, 只是交互反馈
    TYPING = "typing"       # "对方正在输入..." 状态, 用于 LLM 思考期间给用户反馈
    REACTION = "reaction"


@dataclass
class Action:
    """Bot 要执行的一个动作.

    Attributes:
        action_type: 操作类型(ActionType 枚举)
        target: 动作目标 — "发给谁". 复用 EventSource, 指定发到哪个群/哪个私聊
        payload: 动作参数, 内容取决于 action_type(如 {"text": "hello"})
        reply_to: 引用回复的消息 ID — "回复哪条". None 则为普通发送, 不引用
    """
    action_type: ActionType
    target: EventSource
    payload: dict[str, Any] = field(default_factory=dict)
    reply_to: str | None = None
