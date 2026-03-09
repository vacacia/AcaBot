from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .response import AgentResponse
from .tool import ToolDef


class BaseAgent(ABC):
    """Agent 接口 — 封装 LLM 调用 + tool calling loop.

    Pipeline 只调一次 run(), 内部可能经历多轮 tool call.
    v0.3 实现 LitellmAgent(基于 litellm.acompletion).

    Note:
        max_tool_rounds 等实现细节由具体 Agent 子类控制,
        不在接口层约束.
    """

    @abstractmethod
    def register_tool(self, tool: ToolDef) -> None:
        """注册工具供 LLM 调用.

        Args:
            tool: 工具定义, 包含 name/description/parameters/handler.
        """
        ...

    @abstractmethod
    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> AgentResponse:
        """执行一次完整的 LLM 调用(含 tool calling loop).

        Args:
            system_prompt: 系统提示词.
            messages: 上下文消息列表(OpenAI messages 格式).
                - 直接传给 litellm , litellm 期望 list[dict]
                - 不结构化
            model: 模型名, None 则用 Agent 默认模型.
                hook 可通过 HookContext.model 覆盖, 实现热切换.

        Returns:
            AgentResponse, 包含文本回复、附件、token 用量等.
        """
        ...

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> AgentResponse:
        """单次 LLM completion, 不带 tool calling loop.

        适用场景: 插件调 VLM 识图 / 提取关键信息 / 生成摘要等,
        不需要工具调用, 只要一次 LLM 回复.

        Args:
            system_prompt: 系统提示词.
            messages: 上下文消息列表(OpenAI messages 格式).
            model: 模型名, None 则用 Agent 默认模型.

        Returns:
            AgentResponse, 只有 text/error/usage/model_used, 无 tool_calls_made.
        """
        ...
