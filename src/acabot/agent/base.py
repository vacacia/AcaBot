"""agent.base 定义 BaseAgent 的正式契约."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .response import AgentResponse
from .tool import ToolExecutor, ToolSpec


class BaseAgent(ABC):
    """Agent 接口.

    这一版把:
    - 模型可见的 `tools`
    - 真正执行的 `tool_executor`

    从 agent 内部拆出来.
    """

    @abstractmethod
    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        tools: list[ToolSpec] | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> AgentResponse:
        """执行一次完整的 LLM 调用.

        Args:
            system_prompt: 系统提示词.
            messages: 上下文消息列表.
            model: 模型名覆盖.
            tools: 当前 run 可见的 tool schema 列表.
            tool_executor: 当前 run 的外部 tool executor.

        Returns:
            一份 AgentResponse.
        """

        ...

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> AgentResponse:
        """执行一次不带 tool loop 的单次 completion.

        Args:
            system_prompt: 系统提示词.
            messages: 上下文消息列表.
            model: 模型名覆盖.

        Returns:
            一份 AgentResponse.
        """

        ...
