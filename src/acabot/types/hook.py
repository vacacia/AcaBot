from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, TYPE_CHECKING

from .event import StandardEvent
from .action import Action

if TYPE_CHECKING:
    from acabot.session.base import Session
    from acabot.agent.response import AgentResponse


class HookPoint(Enum):
    """消息生命周期中的 hook 切入点.

    消息流: on_receive -> pre_llm -> [LLM] -> post_llm -> before_send -> [send] -> on_sent
    特殊点: on_error(异常时), on_session_expire(会话过期时)
    工具点: on_tool_call / on_tool_result
    """
    ON_RECEIVE = "on_receive"
    PRE_LLM = "pre_llm"
    ON_TOOL_CALL = "on_tool_call"
    ON_TOOL_RESULT = "on_tool_result"
    POST_LLM = "post_llm"
    BEFORE_SEND = "before_send"
    ON_SENT = "on_sent"
    ON_ERROR = "on_error"
    ON_SESSION_EXPIRE = "on_session_expire"


@dataclass
class HookResult:
    """Hook 返回值, 控制 Pipeline 后续行为.

    action:
        "continue"  
            — 继续执行下一个 hook
        "skip_llm": 
            — 跳过 LLM 调用, 直接用 early_response 回复(仅 on_receive/pre_llm 有效)
            - 后续的 before_send / on_sent hook 仍然执行
            - skip_llm + early_response:  on_receive → [跳过LLM] → before_send → send → on_sent
        "abort": 会截断后续 hook 链
            — 中断整个流程, 不发送任何回复
            - abort: on_receive → (直接结束)
    early_response: skip_llm 时要发送的 Action 列表
    """
    action: Literal["continue", "skip_llm", "abort"] = "continue"
    early_response: list[Action] | None = None


@dataclass
class HookContext:
    """贯穿 Pipeline 的共享上下文, hook 通过修改它来影响后续流程.

    Attributes:
        event: 原始 StandardEvent(只读, 不要修改)
        session: 当前 Session
        messages: 要送给 LLM 的上下文消息列表(hook 可增删改)
        system_prompt: system prompt(hook 可追加记忆/人设等)
        model: LLM 模型名(hook 可覆盖, 实现热切换)
        response: LLM 回复(post_llm 阶段才有值)
        actions: 待发送动作列表(post_llm/before_send hook 可改)
        metadata: hook 间传数据的共享字典
    """
    event: StandardEvent
    session: Session | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    system_prompt: str = ""
    model: str | None = None
    response: AgentResponse | None = None
    actions: list[Action] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
