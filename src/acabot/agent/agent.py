"""agent.agent 提供基于 litellm 的 BaseAgent 实现."""

from __future__ import annotations

import json
import logging
from inspect import isawaitable
from typing import Any

from .base import BaseAgent
from .response import AgentResponse, ToolCallRecord
from .tool import (
    ToolDef,
    ToolExecutionResult,
    ToolExecutor,
    ToolSpec,
    normalize_tool_result,
)

try:
    from litellm import acompletion as _litellm_acompletion
except ImportError:
    _litellm_acompletion = None

acompletion = _litellm_acompletion

logger = logging.getLogger("acabot.agent")


class LitellmAgent(BaseAgent):
    """litellm.acompletion 实现的 Agent.

    - LLM 可见工具来自 `tools`
    - 真正执行工具依赖 `tool_executor`

    agent 自己不再默认拥有执行权.
    """

    def __init__(self, default_model: str = "gpt-4o-mini", max_tool_rounds: int = 5):
        """初始化 LitellmAgent.

        Args:
            default_model: 默认使用的 model name.
            max_tool_rounds: 最多允许多少轮 tool calling.
        """

        self.default_model = default_model
        self.max_tool_rounds = max_tool_rounds
        self._registered_tools: dict[str, ToolDef] = {}

    # region legacy convenience
    def register_tool(self, tool: ToolDef) -> None:
        """注册一条 legacy convenience tool.

        Args:
            tool: 要注册的 ToolDef.
        """

        self._registered_tools[tool.name] = tool

    def _registered_specs(self) -> list[ToolSpec]:
        """返回当前已注册工具对应的 ToolSpec 列表.

        Returns:
            当前已注册的 ToolSpec 列表.
        """

        return [tool.to_spec() for tool in self._registered_tools.values()]

    async def _run_registered_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolExecutionResult:
        """执行一条已注册的 legacy convenience tool.

        Args:
            tool_name: 目标 tool name.
            arguments: tool 参数.

        Returns:
            标准化后的 ToolExecutionResult.
        """

        tool_def = self._registered_tools.get(tool_name)
        if tool_def is None:
            return ToolExecutionResult(
                content=json.dumps(
                    {"error": f"Unknown tool: {tool_name}"},
                    ensure_ascii=False,
                )
            )
        try:
            raw = tool_def.handler(arguments)
            if isawaitable(raw):
                raw = await raw
        except Exception as exc:
            return ToolExecutionResult(
                content=json.dumps({"error": str(exc)}, ensure_ascii=False),
                raw={"error": str(exc)},
            )
        return normalize_tool_result(raw)

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[str | list[dict[str, Any]], list[Any]]:
        """执行一条 registered tool 的 legacy compatibility wrapper.

        Args:
            tool_name: 目标 tool name.
            arguments: tool 参数.

        Returns:
            `(content, attachments)`.
        """

        result = await self._run_registered_tool(tool_name, arguments)
        return result.content, list(result.attachments)

    # endregion

    # region run
    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        tools: list[ToolSpec] | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> AgentResponse:
        """执行一次完整的 agent run.

        Args:
            system_prompt: 本次调用使用的 system prompt.
            messages: 传给 model 的 message list.
            model: 可选的 model override.
            tools: 当前 run 暴露给 LLM 的工具 schema.
            tool_executor: 当前 run 使用的外部 tool executor.

        Returns:
            一份 AgentResponse.
        """

        use_model = model or self.default_model
        active_tools, active_executor = self._resolve_tool_runtime(tools, tool_executor)
        if active_tools and active_executor is None:
            return AgentResponse(
                error="tool_executor is required when tools are provided",
                model_used=use_model,
            )

        completion = self._get_acompletion()
        full_messages = [{"role": "system", "content": system_prompt}] + list(messages)
        tools_param = self._build_tools_param(active_tools)
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        tool_calls_made: list[ToolCallRecord] = []
        all_attachments = []

        for _ in range(self.max_tool_rounds + 1):
            try:
                kwargs: dict[str, Any] = {"model": use_model, "messages": full_messages}
                if tools_param:
                    kwargs["tools"] = tools_param

                response = completion(**kwargs)
                if isawaitable(response):
                    response = await response
                choice = response.choices[0]
                usage = response.usage
                for key in total_usage:
                    total_usage[key] += getattr(usage, key, 0)
            except Exception as exc:
                logger.error("LLM call failed: %s", exc)
                return AgentResponse(error=str(exc), model_used=use_model)

            msg = choice.message
            if msg.tool_calls:
                if active_executor is None:
                    return AgentResponse(
                        error="LLM requested tool calls without tool_executor",
                        model_used=use_model,
                        raw=response,
                    )
                await self._handle_tool_calls(
                    msg=msg,
                    full_messages=full_messages,
                    tool_calls_made=tool_calls_made,
                    all_attachments=all_attachments,
                    tool_executor=active_executor,
                )
                continue

            return AgentResponse(
                text=msg.content or "",
                attachments=all_attachments,
                usage=total_usage,
                tool_calls_made=tool_calls_made,
                model_used=use_model,
                raw=response,
            )

        return AgentResponse(
            error=f"Tool calling exceeded max rounds ({self.max_tool_rounds})",
            model_used=use_model,
        )

    # endregion

    # region complete
    async def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> AgentResponse:
        """执行一次不带 tool loop 的 completion.

        Args:
            system_prompt: 本次调用使用的 system prompt.
            messages: 传给 model 的 message list.
            model: 可选的 model override.

        Returns:
            一份 AgentResponse.
        """

        completion = self._get_acompletion()
        use_model = model or self.default_model
        full_messages = [{"role": "system", "content": system_prompt}] + list(messages)
        try:
            response = completion(model=use_model, messages=full_messages)
            if isawaitable(response):
                response = await response
            choice = response.choices[0]
            usage = response.usage
            return AgentResponse(
                text=choice.message.content or "",
                usage={
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                },
                model_used=use_model,
                raw=response,
            )
        except Exception as exc:
            logger.error("LLM complete failed: %s", exc)
            return AgentResponse(error=str(exc), model_used=use_model)

    # endregion

    # region internals
    def _resolve_tool_runtime(
        self,
        tools: list[ToolSpec] | None,
        tool_executor: ToolExecutor | None,
    ) -> tuple[list[ToolSpec], ToolExecutor | None]:
        """决定本次 run 使用哪些 tools 和哪个 tool executor.

        Args:
            tools: 调用方显式传入的 ToolSpec 列表.
            tool_executor: 调用方显式传入的 ToolExecutor.

        Returns:
            `(active_tools, active_executor)`.
        """

        if tools is not None:
            return list(tools), tool_executor
        if not self._registered_tools:
            return [], None
        return self._registered_specs(), self._run_registered_tool

    def _build_tools_param(self, tools: list[ToolSpec]) -> list[dict[str, Any]] | None:
        """把 ToolSpec 列表转成 OpenAI function calling 格式.

        Args:
            tools: 当前 run 可见的 ToolSpec 列表.

        Returns:
            litellm 需要的 `tools` 参数. 没有工具时返回 None.
        """

        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]

    async def _handle_tool_calls(
        self,
        *,
        msg: Any,
        full_messages: list[dict[str, Any]],
        tool_calls_made: list[ToolCallRecord],
        all_attachments: list[Any],
        tool_executor: ToolExecutor,
    ) -> None:
        """处理一轮 tool calls.

        Args:
            msg: LLM 返回的 message 对象.
            full_messages: 对话历史, 就地追加.
            tool_calls_made: tool call 审计记录, 就地追加.
            all_attachments: 附件累积列表, 就地追加.
            tool_executor: 本次 run 的外部 tool executor.
        """

        raw = msg.model_dump()
        assistant_msg = {
            key: value for key, value in raw.items() if value is not None or key == "content"
        }
        full_messages.append(assistant_msg)

        for tool_call in msg.tool_calls:
            tool_name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}

            execution = tool_executor(tool_name, arguments)
            if isawaitable(execution):
                execution = await execution
            if not isinstance(execution, ToolExecutionResult):
                execution = normalize_tool_result(execution)
            all_attachments.extend(execution.attachments)
            full_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": execution.content,
                }
            )
            tool_calls_made.append(
                ToolCallRecord(
                    name=tool_name,
                    arguments=arguments,
                    result=execution.raw if execution.raw is not None else execution.content,
                )
            )

    @staticmethod
    def _get_acompletion() -> Any:
        """返回 litellm.acompletion callable.

        Returns:
            可 await 的 acompletion callable.

        Raises:
            RuntimeError: 当 litellm dependency 不可用时抛出.
        """

        if acompletion is None:
            raise RuntimeError("litellm dependency is required to run LitellmAgent")
        return acompletion

    # endregion
