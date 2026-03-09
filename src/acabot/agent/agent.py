"""LitellmAgent — 基于 litellm 的 Agent 实现, 含 tool calling loop."""

from __future__ import annotations

import json
import logging
from typing import Any

from litellm import acompletion

from .base import BaseAgent
from .response import AgentResponse, Attachment, ToolCallRecord
from .tool import ToolDef

logger = logging.getLogger("acabot.agent")


class LitellmAgent(BaseAgent):
    """litellm.acompletion 实现的 Agent.

    内部维护 tool calling loop: LLM → tool call → tool result → LLM → ... → 最终回复.

    Args:
        default_model: 默认模型名, run() 未指定 model 时使用.
        max_tool_rounds: 最大 tool 调用轮次, 防止无限循环.
    """

    def __init__(self, default_model: str = "gpt-4o-mini", max_tool_rounds: int = 5):
        self.default_model = default_model
        self.max_tool_rounds = max_tool_rounds
        self._tools: dict[str, ToolDef] = {}

    def register_tool(self, tool: ToolDef) -> None:
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

                response = await acompletion(**kwargs)
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
        full_messages.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }
        )

        # 逐个执行 tool 并追加结果
        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                params = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                params = {}

            result_str, attachments = await self._execute_tool(tool_name, params)
            all_attachments.extend(attachments)
            full_messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result_str}
            )
            tool_calls_made.append(
                ToolCallRecord(name=tool_name, arguments=params, result=result_str)
            )

    async def _execute_tool(
        self, tool_name: str, params: dict,
    ) -> tuple[str, list[Attachment]]:
        """执行单个 tool, 返回 (结果 str, attachments).

        handler 可以返回含 "attachments" key 的 dict,
        NOTE: 提取附件并从 result 中移除, 避免在 tool result 中发给 LLM.
        """
        tool_def = self._tools.get(tool_name)
        if not tool_def:
            return json.dumps({"error": f"Unknown tool: {tool_name}"}), []
        try:
            result = await tool_def.handler(params)
            if isinstance(result, dict) and "attachments" in result:
                # 浅拷贝后 pop, 不修改 handler 的原始返回值
                result = dict(result)
                raw_attachments = result.pop("attachments")
                attachments = [
                    Attachment(
                        type=a.get("type", "file"),
                        url=a.get("url", ""),
                        data=a.get("data", ""),
                    )
                    for a in raw_attachments
                ]
                # 空 dict 序列化为 "{}", 避免某些 LLM 拒绝空 tool result
                return json.dumps(result), attachments
            if isinstance(result, str):
                return result, []
            return json.dumps(result), []
        except Exception as e:
            return json.dumps({"error": str(e)}), []

    # endregion
