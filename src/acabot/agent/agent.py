"""LitellmAgent — 基于 litellm 的 Agent 实现, 含 tool calling loop."""

from __future__ import annotations

import json
import logging
from inspect import isawaitable
from typing import Any

from .base import BaseAgent
from .response import AgentResponse, Attachment, ToolCallRecord
from .tool import ToolDef

try:
    from litellm import acompletion as _litellm_acompletion
except ImportError:
    _litellm_acompletion = None

acompletion = _litellm_acompletion

logger = logging.getLogger("acabot.agent")


class LitellmAgent(BaseAgent):
    """litellm.acompletion 实现的 Agent.

    内部维护 tool calling loop: LLM → tool call → tool result → LLM → ... → 最终回复.

    Args:
        default_model: 默认模型名, run() 未指定 model 时使用.
        max_tool_rounds: 最大 tool 调用轮次, 防止无限循环.
    """

    def __init__(self, default_model: str = "gpt-4o-mini", max_tool_rounds: int = 5):
        """初始化 LitellmAgent.

        Args:
            default_model: 默认使用的 model name.
            max_tool_rounds: 最多允许多少轮 tool calling.
        """

        self.default_model = default_model
        self.max_tool_rounds = max_tool_rounds
        self._tools: dict[str, ToolDef] = {}

    def register_tool(self, tool: ToolDef) -> None:
        """注册一个 ToolDef.

        Args:
            tool: 要注册的 ToolDef.
        """

        self._tools[tool.name] = tool

    def _build_tools_param(self) -> list[dict] | None:
        """把 ToolDef 转成 OpenAI function calling 格式.
        litellm.acompletion 的 tools 参数要求这种固定格式
        """
        if not self._tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    # region 核心: run + tool calling loop

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> AgentResponse:
        """执行一次完整的 agent run.

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
        tools_param = self._build_tools_param()
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        tool_calls_made: list[ToolCallRecord] = []
        all_attachments: list[Attachment] = []

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
                for k in total_usage:
                    total_usage[k] += getattr(usage, k, 0)

                msg = choice.message

                # LLM 请求调用工具 → 执行后继续循环
                if msg.tool_calls:
                    await self._handle_tool_calls(
                        msg,
                        full_messages,
                        tool_calls_made,
                        all_attachments,
                    )
                    continue

                # 没有 tool call → 最终回复
                return AgentResponse(
                    text=msg.content or "",
                    attachments=all_attachments,
                    usage=total_usage,
                    tool_calls_made=tool_calls_made,
                    model_used=use_model,
                    raw=response,
                )
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                return AgentResponse(error=str(e), model_used=use_model)

        return AgentResponse(
            error=f"Tool calling exceeded max rounds ({self.max_tool_rounds})",
            model_used=use_model,
        )

    # endregion

    # region 单次 completion (不带 tools)

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
            # 不传 tools, 不进 loop, 只做一次 completion
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
        except Exception as e:
            logger.error("LLM complete failed: %s", e)
            return AgentResponse(error=str(e), model_used=use_model)

    # endregion

    # region tool call 处理

    async def _handle_tool_calls(
        self,
        msg: Any,
        full_messages: list[dict[str, Any]],
        tool_calls_made: list[ToolCallRecord],
        all_attachments: list[Attachment],
    ) -> None:
        """处理一轮 tool calls: 把 assistant 消息和 tool 结果追加到 messages.

        Args:
            msg: LLM 返回的 message 对象(含 tool_calls).
            full_messages: 对话历史, 就地追加.
            tool_calls_made: tool call 记录列表, 就地追加.
            all_attachments: 累积的附件列表, 就地追加.
        """
        # 追加 assistant 的 tool_call 请求
        # 用 model_dump() 保留 provider-specific 字段(如 Gemini 的 thought_signature),
        # 过滤 None 值减少冗余, 但保留 content(即使为 None, 某些 provider 要求字段存在)
        raw = msg.model_dump()
        assistant_msg = {
            k: v for k, v in raw.items() if v is not None or k == "content"
        }
        full_messages.append(assistant_msg)

        # 逐个执行 tool 并追加结果
        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                params = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                params = {}

            result_content, attachments = await self._execute_tool(tool_name, params)
            all_attachments.extend(attachments)
            # content 可以是 str 或 list[dict](content blocks, 含图片)
            full_messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result_content}
            )
            tool_calls_made.append(
                ToolCallRecord(name=tool_name, arguments=params, result=result_content)
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

    async def _execute_tool(
        self, tool_name: str, params: dict,
    ) -> tuple[str, list[Attachment]]:
        """执行单个 tool, 返回 (tool result str, attachments).

        handler 返回 dict 时支持特殊 key "attachments": 提取后发给用户(Pipeline 处理).
        """
        tool_def = self._tools.get(tool_name)
        if not tool_def:
            return json.dumps({"error": f"Unknown tool: {tool_name}"}), []
        try:
            result = await tool_def.handler(params)
            if not isinstance(result, dict):
                return (result if isinstance(result, str) else json.dumps(result)), []

            # 浅拷贝, 不修改 handler 的原始返回值
            result = dict(result)

            # 提取 attachments(发给用户)
            attachments: list[Attachment] = []
            if "attachments" in result:
                raw_attachments = result.pop("attachments")
                attachments = [
                    Attachment(
                        type=a.get("type", "file"),
                        url=a.get("url", ""),
                        data=a.get("data", ""),
                    )
                    for a in raw_attachments
                ]

            return json.dumps(result), attachments
        except Exception as e:
            return json.dumps({"error": str(e)}), []

    # endregion
