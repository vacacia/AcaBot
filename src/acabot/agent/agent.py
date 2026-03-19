"""agent.agent 提供基于 litellm 的 BaseAgent 实现."""

from __future__ import annotations

import json
import logging
from inspect import isawaitable
from typing import Any

from .base import BaseAgent
from .response import AgentResponse, ToolCallRecord
from .tool import (
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

    def __init__(self, max_tool_rounds: int = 30):
        """初始化 LitellmAgent.

        Args:
            max_tool_rounds: 缺省的 tool loop 上限. Runtime 可在每次调用时覆盖.
        """

        self.max_tool_rounds = max_tool_rounds

    # region run
    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        request_options: dict[str, Any] | None = None,
        max_tool_rounds: int | None = None,
        tools: list[ToolSpec] | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> AgentResponse:
        """执行一次完整的 agent run.

        Args:
            system_prompt: 本次调用使用的 system prompt.
            messages: 传给 model 的 message list.
            model: 可选的 model override. Runtime 层必须拥有决定 model 和 agent 的最高权力.
            request_options: 当前 run 已解析好的 provider 请求选项.
            max_tool_rounds: 当前 run 允许的最大 tool loop 轮数. 缺省时回退到实例默认值.
            tools: 当前 run 暴露给 LLM 的工具 schema.
            tool_executor: 当前 run 使用的外部 tool executor.

        Returns:
            一份 AgentResponse.
        """

        use_model = str(model or "").strip()
        if not use_model:
            return AgentResponse(error="model is required", model_used="")
        active_max_tool_rounds = self._resolve_max_tool_rounds(max_tool_rounds)
        active_tools, active_executor = self._resolve_tool_runtime(tools, tool_executor)
        # 如果有工具但没有 executor, 报错返回
        if active_tools and active_executor is None:
            return AgentResponse(
                error="tool_executor is required when tools are provided",
                model_used=use_model,
            )

        completion = self._get_acompletion()
        full_messages = self._sanitize_messages(
            [{"role": "system", "content": system_prompt}] + list(messages)
        )
        tools_param = self._build_tools_param(active_tools)
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        tool_calls_made: list[ToolCallRecord] = []
        all_attachments = []

        for _ in range(active_max_tool_rounds + 1):
            try:
                kwargs: dict[str, Any] = {"model": use_model, "messages": full_messages}
                # 合并配置文件里的额外配置 (比如 api_key, temperature)
                # 但不允许覆盖 model, messages, tools 这些主参数
                kwargs.update(self._normalized_request_options(request_options))
                if tools_param:
                    kwargs["tools"] = tools_param

                logger.debug(
                    "LLM run request: model=%s messages=%s tools=%s request_options=%s",
                    use_model,
                    len(full_messages),
                    len(active_tools),
                    ",".join(sorted(kwargs.keys())),
                )

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
                logger.debug(
                    "LLM requested tool calls: model=%s count=%s names=%s",
                    use_model,
                    len(msg.tool_calls),
                    ",".join(tool_call.function.name for tool_call in msg.tool_calls),
                )
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

            logger.info(
                "LLM run completed: model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s attachments=%s text_preview=%s",
                use_model,
                total_usage.get("prompt_tokens", 0),
                total_usage.get("completion_tokens", 0),
                total_usage.get("total_tokens", 0),
                len(all_attachments),
                self._preview_text(msg.content),
            )
            return AgentResponse(
                text=msg.content or "",
                attachments=all_attachments,
                usage=total_usage,
                tool_calls_made=tool_calls_made,
                model_used=use_model,
                raw=response,
            )

        return AgentResponse(
            error=f"Tool calling exceeded max rounds ({active_max_tool_rounds})",
            model_used=use_model,
        )

    # endregion

    # region complete
    async def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        request_options: dict[str, Any] | None = None,
    ) -> AgentResponse:
        """执行一次不带 tool loop 的 completion.

        Args:
            system_prompt: 本次调用使用的 system prompt.
            messages: 传给 model 的 message list.
            model: 可选的 model override.
            request_options: 当前 run 已解析好的 provider 请求选项.

        Returns:
            一份 AgentResponse.
        """

        completion = self._get_acompletion()
        use_model = str(model or "").strip()
        if not use_model:
            return AgentResponse(error="model is required", model_used="")
        full_messages = self._sanitize_messages(
            [{"role": "system", "content": system_prompt}] + list(messages)
        )
        try:
            kwargs: dict[str, Any] = {"model": use_model, "messages": full_messages}
            kwargs.update(self._normalized_request_options(request_options))
            logger.debug(
                "LLM complete request: model=%s messages=%s request_options=%s",
                use_model,
                len(full_messages),
                ",".join(sorted(kwargs.keys())),
            )
            response = completion(**kwargs)
            if isawaitable(response):
                response = await response
            choice = response.choices[0]
            usage = response.usage
            logger.debug(
                "LLM complete finished: model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s text_preview=%s",
                use_model,
                getattr(usage, "prompt_tokens", 0),
                getattr(usage, "completion_tokens", 0),
                getattr(usage, "total_tokens", 0),
                self._preview_text(choice.message.content),
            )
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

        return list(tools or []), tool_executor

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

    def _resolve_max_tool_rounds(self, value: int | None) -> int:
        """解析本次调用实际使用的 tool loop 上限."""

        if value is None:
            return max(0, int(self.max_tool_rounds))
        return max(0, int(value))

    @staticmethod
    def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把消息列表归一化成对模型请求更安全的形状."""

        sanitized: list[dict[str, Any]] = []
        normalized_count = 0
        for message in messages:
            item = dict(message)
            if "content" not in item or item.get("content") is None:
                item["content"] = ""
                normalized_count += 1
            sanitized.append(item)
        if normalized_count:
            logger.warning("Normalized messages with empty content: count=%s", normalized_count)
        return sanitized

    @staticmethod
    def _normalized_request_options(
        request_options: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """过滤不应覆盖主参数的 request options.
        """

        options = dict(request_options or {})
        options.pop("model", None)
        options.pop("messages", None)
        options.pop("tools", None)
        return options

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
            key: ("" if key == "content" and value is None else value)
            for key, value in raw.items()
            if value is not None or key == "content"
        }
        full_messages.append(assistant_msg)

        for tool_call in msg.tool_calls:
            tool_name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}

            logger.debug(
                "Tool execution requested by LLM: name=%s args=%s",
                tool_name,
                self._preview_json(arguments),
            )

            execution = tool_executor(tool_name, arguments)
            if isawaitable(execution):
                execution = await execution
            if not isinstance(execution, ToolExecutionResult):
                execution = normalize_tool_result(execution)
            all_attachments.extend(execution.attachments)
            logger.debug(
                "Tool execution finished: name=%s attachments=%s content_preview=%s",
                tool_name,
                len(execution.attachments),
                self._preview_text(execution.content),
            )
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

    @staticmethod
    def _preview_text(value: Any, max_len: int = 120) -> str:
        text = str(value or "").replace("\n", " ").strip()
        if len(text) <= max_len:
            return text
        return f"{text[:max_len]}..."

    @staticmethod
    def _preview_json(value: Any, max_len: int = 160) -> str:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            text = str(value)
        if len(text) <= max_len:
            return text
        return f"{text[:max_len]}..."

    # endregion
