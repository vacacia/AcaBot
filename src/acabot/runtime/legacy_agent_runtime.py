"""runtime.legacy_agent_runtime 提供旧 agent 形状到新 AgentRuntime 的适配层.

这一层的目标不是长期形态, 而是让新的 runtime 主线先能接上现有 `run(system_prompt, messages, model)` 接口.
"""

from __future__ import annotations

from typing import Any, Protocol

from acabot.types import Action, ActionType

from .agent_runtime import AgentRuntime
from .models import AgentRuntimeResult, PlannedAction, RunContext
from .profile_loader import PromptLoader


class LegacyAgentProtocol(Protocol):
    """旧 agent 需要满足的最小协议."""

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> Any:
        """执行一次旧式 agent run.

        Args:
            system_prompt: 本次调用使用的 system prompt.
            messages: 传给模型的上下文消息列表.
            model: 可选的模型名覆盖.

        Returns:
            一个具备 `text`, `error`, `usage`, `tool_calls_made`, `model_used`, `raw` 等属性的响应对象.
        """

        ...


class LegacyAgentRuntime(AgentRuntime):
    """把旧 agent 适配为新 AgentRuntime 的最小实现.

    只处理文本回复, 不负责 tool schema, tool executor 和附件动作转换.
    """

    def __init__(self, *, agent: LegacyAgentProtocol, prompt_loader: PromptLoader) -> None:
        """初始化旧 agent 适配层.

        Args:
            agent: 满足旧 `run(system_prompt, messages, model)` 形状的 agent.
            prompt_loader: 根据 `prompt_ref` 加载 system prompt 的 loader.
        """

        self.agent = agent
        self.prompt_loader = prompt_loader

    async def execute(self, ctx: RunContext) -> AgentRuntimeResult:
        """执行一次旧 agent 调用, 并转换成 AgentRuntimeResult.

        Args:
            ctx: 当前 run 的完整执行上下文.

        Returns:
            一份符合新 runtime 契约的执行结果.
        """

        ctx.system_prompt = self.prompt_loader.load(ctx.profile.prompt_ref)
        response = await self.agent.run(
            system_prompt=ctx.system_prompt,
            messages=ctx.messages,
            model=ctx.profile.default_model,
        )

        if getattr(response, "error", None):
            return AgentRuntimeResult(
                status="failed",
                text="",
                actions=[],
                artifacts=self._extract_artifacts(response),
                usage=dict(getattr(response, "usage", {}) or {}),
                tool_calls=self._extract_tool_calls(response),
                model_used=str(getattr(response, "model_used", "") or ""),
                error=str(getattr(response, "error", "")),
                raw=getattr(response, "raw", None),
            )

        text = str(getattr(response, "text", "") or "")
        actions = [self._build_text_reply_action(ctx, text)] if text else []
        return AgentRuntimeResult(
            status="completed",
            text=text,
            actions=actions,
            artifacts=self._extract_artifacts(response),
            usage=dict(getattr(response, "usage", {}) or {}),
            tool_calls=self._extract_tool_calls(response),
            model_used=str(getattr(response, "model_used", "") or ""),
            raw=getattr(response, "raw", None),
        )

    @staticmethod
    def _build_text_reply_action(ctx: RunContext, text: str) -> PlannedAction:
        """把一段纯文本回复转换成 PlannedAction.

        Args:
            ctx: 当前 run 的执行上下文.
            text: 要回复给用户的文本.

        Returns:
            一条纯文本回复动作.
        """

        return PlannedAction(
            action_id=f"action:{ctx.run.run_id}:reply",
            action=Action(
                action_type=ActionType.SEND_TEXT,
                target=ctx.event.source,
                payload={"text": text},
            ),
            thread_content=text,
            commit_when="success",
            metadata={"origin": "legacy_agent_text"},
        )

    @staticmethod
    def _extract_artifacts(response: Any) -> list[dict[str, Any]]:
        """从旧响应对象里提取附件信息.

        Args:
            response: 旧 agent 返回的响应对象.

        Returns:
            一个尽量保真的附件信息列表.
        """

        artifacts: list[dict[str, Any]] = []
        for attachment in getattr(response, "attachments", []) or []:
            artifacts.append(
                {
                    "type": getattr(attachment, "type", ""),
                    "url": getattr(attachment, "url", ""),
                    "data": getattr(attachment, "data", ""),
                    "metadata": dict(getattr(attachment, "metadata", {}) or {}),
                }
            )
        return artifacts

    @staticmethod
    def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
        """从旧响应对象里提取 tool call 记录.

        Args:
            response: 旧 agent 返回的响应对象.

        Returns:
            一个面向审计的简单 tool call 列表.
        """

        tool_calls: list[dict[str, Any]] = []
        for call in getattr(response, "tool_calls_made", []) or []:
            tool_calls.append(
                {
                    "name": getattr(call, "name", ""),
                    "arguments": dict(getattr(call, "arguments", {}) or {}),
                    "result": getattr(call, "result", None),
                }
            )
        return tool_calls
