"""runtime.context_assembly.contracts 定义最终上下文组装的最小对象.

这一层位于:

    ThreadPipeline / MemoryBroker / ToolRuntime
        |
        v
    ContextAssembler
        |
        v
    AssembledContext -> ModelAgentRuntime -> BaseAgent.run(...)

它不负责读取任何来源, 只负责表达:
- 每一条会进入模型上下文的正式条目
- 最终发给模型的 system prompt 和 messages
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# region context contribution
@dataclass(slots=True)
class ContextContribution:
    """一条正式上下文条目.

    Attributes:
        source_kind (str): 当前条目的来源类型.
        target_slot (str): 当前条目最终要落到的正式槽位.
        priority (int): 同一个槽位内部的排序优先级.
        role (str): 当前条目落到 messages 时使用的 role.
        content (str | list[dict[str, Any]]): 真正发给模型的内容.
        metadata (dict[str, Any]): 额外的调试和来源信息.
    """

    source_kind: str
    target_slot: str
    priority: int
    role: str
    content: str | list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AssembledContext:
    """最终发给模型的正式上下文结果.

    Attributes:
        system_prompt (str): 最终 system prompt.
        messages (list[dict[str, Any]]): 最终 messages 列表.
    """

    system_prompt: str
    messages: list[dict[str, Any]]


# endregion


__all__ = ["AssembledContext", "ContextContribution"]
