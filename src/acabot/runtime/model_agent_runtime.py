"""runtime.model_agent_runtime 把 BaseAgent 接到 runtime 主线上.

组件关系:

    RunContext
        |
        v
    ModelAgentRuntime
      |        |
      |       ToolRuntimeResolver -> ToolSpec + ToolExecutor
      v
    BaseAgent.run()
      |
      v
    AgentResponse -> AgentRuntimeResult


- 负责把 `RunContext` 转成一次 `BaseAgent.run()` 调用.
- 负责把 `AgentResponse` 转成 runtime 认识的 `AgentRuntimeResult`.
- 不负责审批, 不负责 tool 权限, 不负责 memory 检索.

`ToolBroker` 完成时, 只需要把它接到 `ToolRuntimeResolver`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any, Protocol

from acabot.agent import Attachment, BaseAgent, ToolExecutor, ToolSpec
from acabot.types import Action, ActionType

from .agent_runtime import AgentRuntime
from .models import AgentRuntimeResult, PlannedAction, RunContext
from .profile_loader import PromptLoader


# region tool runtime
@dataclass(slots=True)
class ToolRuntime:
    """一次 run 的 tool runtime 视图.

    一次 run 中, 授权给 LLM 的全部能力: 可见的工具列表, 可用的 tool_executor.

    Attributes:
        tools (list[ToolSpec]): 当前暴露给模型的 tool schema 列表.
        tool_executor (ToolExecutor | None): 当前 run 使用的 tool executor.
        metadata (dict[str, Any]): tool runtime 附加元数据.
    """

    tools: list[ToolSpec] = field(default_factory=list)
    tool_executor: ToolExecutor | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolRuntimeResolver(Protocol):
    """按 RunContext 解析 tool runtime 的协议.
    
    接受 RunContext 并异步返回 ToolRuntime 的都是 ToolRuntimeResolver.
    实现执行引擎与插件/权限系统的隔离.
    """

    async def __call__(self, ctx: RunContext) -> ToolRuntime:
        """解析当前 run 的 tool runtime.

        Args:
            ctx: 当前 run 的完整执行上下文.

        Returns:
            一份 ToolRuntime.
        """

        ...


# endregion


# region runtime
class ModelAgentRuntime(AgentRuntime):
    """基于 BaseAgent 的正式 AgentRuntime.

    Attributes:
        agent (BaseAgent): 真正执行模型调用和 tool loop 的 agent.
        prompt_loader (PromptLoader): 负责把 `prompt_ref` 加载成 system prompt.
        tool_runtime_resolver (ToolRuntimeResolver | None): 按 run 解析 tools 和 tool executor 的回调.
    """

    def __init__(
        self,
        *,
        agent: BaseAgent,
        prompt_loader: PromptLoader,
        tool_runtime_resolver: ToolRuntimeResolver | None = None,
    ) -> None:
        """初始化 ModelAgentRuntime.

        Args:
            agent: 满足新 `BaseAgent` 契约的 agent.
            prompt_loader: 根据 `prompt_ref` 加载 system prompt 的 loader.
            tool_runtime_resolver: 可选的 tool runtime 解析器.
        """

        self.agent = agent
        self.prompt_loader = prompt_loader
        self.tool_runtime_resolver = tool_runtime_resolver

    async def execute(self, ctx: RunContext) -> AgentRuntimeResult:
        """执行一次正式的 agent runtime.

        1. 加载 prompt
        2. 获取当前 run 的 tool runtime
        3. 调用底层 BaseAgent
        4. 标准化返回的结果

        Args:
            ctx: 当前 run 的完整执行上下文.

        Returns:
            一份符合 runtime 契约的 AgentRuntimeResult.
        """

        ctx.system_prompt = self.prompt_loader.load(ctx.profile.prompt_ref)
        tool_runtime = await self._resolve_tool_runtime(ctx)
        response = await self._call_agent(ctx, tool_runtime)
        return self._to_runtime_result(ctx, response, tool_runtime)

    async def _resolve_tool_runtime(self, ctx: RunContext) -> ToolRuntime:
        """获取当前 run 的 tool runtime.

        Args:
            ctx: 当前 run 的完整执行上下文.

        Returns:
            一份 ToolRuntime.
        """

        if self.tool_runtime_resolver is None:
            # 不需要传工具参数
            return ToolRuntime()

        # 兼容同步/异步插件
        resolved = self.tool_runtime_resolver(ctx)
        if isawaitable(resolved):
            resolved = await resolved
        return resolved

    async def _call_agent(self, ctx: RunContext, tool_runtime: ToolRuntime):
        """调用底层 BaseAgent.

        Args:
            ctx: 当前 run 的完整执行上下文.
            tool_runtime: 当前 run 的 tool runtime.

        Returns:
            底层 agent 返回的 AgentResponse.
        """

        # 防止幻觉, 适配 API, 省 token
        if not tool_runtime.tools and tool_runtime.tool_executor is None:
            return await self.agent.run(
                system_prompt=ctx.system_prompt,
                messages=ctx.messages,
                model=ctx.profile.default_model,
            )

        return await self.agent.run(
            system_prompt=ctx.system_prompt,
            messages=ctx.messages,
            model=ctx.profile.default_model,
            tools=tool_runtime.tools,
            tool_executor=tool_runtime.tool_executor,
        )

    def _to_runtime_result(
        self,
        ctx: RunContext,
        response: Any,
        tool_runtime: ToolRuntime,
    ) -> AgentRuntimeResult:
        """把 AgentResponse 转成 AgentRuntimeResult.

        将 LLM 原始响应翻译成内部统一格式

        Args:
            ctx: 当前 run 的完整执行上下文.
            response: 底层 agent 返回的响应对象.
            tool_runtime: 当前 run 的 tool runtime.

        Returns:
            一份 AgentRuntimeResult.
        """

        artifacts = self._extract_artifacts(response)
        tool_calls = self._extract_tool_calls(response)
        metadata = dict(tool_runtime.metadata)
        if metadata:
            metadata["tool_count"] = len(tool_runtime.tools)

        if getattr(response, "error", None):
            return AgentRuntimeResult(
                status="failed",
                text="",
                actions=[],
                artifacts=artifacts,
                usage=dict(getattr(response, "usage", {}) or {}),
                tool_calls=tool_calls,
                model_used=str(getattr(response, "model_used", "") or ""),
                error=str(getattr(response, "error", "")),
                metadata=metadata,
                raw=getattr(response, "raw", None),
            )

        text = str(getattr(response, "text", "") or "")
        actions = [self._build_text_reply_action(ctx, text)] if text else []
        return AgentRuntimeResult(
            status="completed",
            text=text,
            actions=actions,
            artifacts=artifacts,
            usage=dict(getattr(response, "usage", {}) or {}),
            tool_calls=tool_calls,
            model_used=str(getattr(response, "model_used", "") or ""),
            metadata=metadata,
            raw=getattr(response, "raw", None),
        )

    @staticmethod
    def _build_text_reply_action(ctx: RunContext, text: str) -> PlannedAction:
        """把文本回复转换成 PlannedAction.

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
            metadata={"origin": "model_agent_text"},
        )

    @staticmethod
    def _extract_artifacts(response: Any) -> list[dict[str, Any]]:
        """从 AgentResponse 里提取 artifact 列表.

        Args:
            response: 底层 agent 返回的响应对象.

        Returns:
            一个尽量保真的 artifact 列表.
        """

        artifacts: list[dict[str, Any]] = []
        for attachment in getattr(response, "attachments", []) or []:
            item = attachment
            if isinstance(item, Attachment):
                artifacts.append(
                    {
                        "type": item.type,
                        "url": item.url,
                        "data": item.data,
                        "metadata": dict(item.metadata),
                    }
                )
                continue

            artifacts.append(
                {
                    "type": getattr(item, "type", ""),
                    "url": getattr(item, "url", ""),
                    "data": getattr(item, "data", ""),
                    "metadata": dict(getattr(item, "metadata", {}) or {}),
                }
            )
        return artifacts

    @staticmethod
    def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
        """从 AgentResponse 里提取 tool call 记录.

        Args:
            response: 底层 agent 返回的响应对象.

        Returns:
            一个面向 runtime 审计的 tool call 列表.
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


# endregion
