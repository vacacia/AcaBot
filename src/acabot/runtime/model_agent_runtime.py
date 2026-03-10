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
- 负责把 `AgentResponse` 和 `ApprovalRequired` 转成 runtime 认识的结果.
- 不负责审批策略, 不负责 tool 权限, 不负责 memory 检索.

`ToolBroker` 完成时, 只需要把它接到 `ToolRuntimeResolver`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any, Protocol

from acabot.agent import Attachment, BaseAgent, ToolExecutor, ToolSpec
from acabot.types import Action, ActionType

from .agent_runtime import AgentRuntime
from .models import AgentRuntimeResult, ApprovalRequired, PendingApproval, PlannedAction, RunContext
from .profile_loader import PromptLoader


# region tool runtime
@dataclass(slots=True)
class ToolRuntimeState:
    """一次 run 的 tool 执行累积状态.

    Attributes:
        user_actions (list[PlannedAction]): tool 产出的用户可见动作.
        artifacts (list[dict[str, Any]]): tool 产出的结构化 artifact.
        tool_audit (list[dict[str, Any]]): tool 执行审计记录.
        pending_approval (PendingApproval | None): 当前 run 是否被 tool 中断到审批态.
    """

    user_actions: list[PlannedAction] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    tool_audit: list[dict[str, Any]] = field(default_factory=list)
    pending_approval: PendingApproval | None = None


@dataclass(slots=True)
class ToolRuntime:
    """一次 run 的 tool runtime 视图.

    一次 run 中, 授权给 LLM 的全部能力: 可见的工具列表, 可用的 tool_executor.

    Attributes:
        tools (list[ToolSpec]): 当前暴露给模型的 tool schema 列表.
        tool_executor (ToolExecutor | None): 当前 run 使用的 tool executor.
        state (ToolRuntimeState): 当前 run 的 tool 副产物累积状态.
        metadata (dict[str, Any]): tool runtime 附加元数据.
    """

    tools: list[ToolSpec] = field(default_factory=list)
    tool_executor: ToolExecutor | None = None
    state: ToolRuntimeState = field(default_factory=ToolRuntimeState)
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
        try:
            response = await self._call_agent(ctx, tool_runtime)
        except ApprovalRequired as exc:
            return self._build_waiting_approval_result(tool_runtime, exc)
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
        artifacts.extend(tool_runtime.state.artifacts)
        tool_calls = self._extract_tool_calls(response)
        tool_calls.extend(tool_runtime.state.tool_audit)
        metadata = dict(tool_runtime.metadata)
        if metadata:
            metadata["tool_count"] = len(tool_runtime.tools)
        if tool_runtime.state.tool_audit:
            metadata["tool_audit_count"] = len(tool_runtime.state.tool_audit)

        if getattr(response, "error", None):
            return AgentRuntimeResult(
                status="failed",
                text="",
                actions=self._select_committed_actions(
                    list(tool_runtime.state.user_actions),
                    status="failed",
                ),
                artifacts=artifacts,
                usage=dict(getattr(response, "usage", {}) or {}),
                tool_calls=tool_calls,
                model_used=str(getattr(response, "model_used", "") or ""),
                error=str(getattr(response, "error", "")),
                metadata=metadata,
                raw=getattr(response, "raw", None),
            )

        text = str(getattr(response, "text", "") or "")
        actions = list(tool_runtime.state.user_actions)
        if text:
            actions.append(self._build_text_reply_action(ctx, text))
        return AgentRuntimeResult(
            status="completed",
            text=text,
            actions=self._select_committed_actions(actions, status="completed"),
            artifacts=artifacts,
            usage=dict(getattr(response, "usage", {}) or {}),
            tool_calls=tool_calls,
            model_used=str(getattr(response, "model_used", "") or ""),
            metadata=metadata,
            raw=getattr(response, "raw", None),
        )

    def _build_waiting_approval_result(
        self,
        tool_runtime: ToolRuntime,
        exc: ApprovalRequired,
    ) -> AgentRuntimeResult:
        """把 ApprovalRequired 转成 waiting_approval runtime result.

        Args:
            tool_runtime: 当前 run 的 tool runtime.
            exc: 由 ToolBroker 抛出的 ApprovalRequired.

        Returns:
            一份 waiting_approval 状态的 AgentRuntimeResult.
        """

        metadata = dict(tool_runtime.metadata)
        if metadata:
            metadata["tool_count"] = len(tool_runtime.tools)
        if tool_runtime.state.tool_audit:
            metadata["tool_audit_count"] = len(tool_runtime.state.tool_audit)

        return AgentRuntimeResult(
            status="waiting_approval",
            text="",
            actions=self._select_committed_actions(
                list(tool_runtime.state.user_actions),
                status="waiting_approval",
            ),
            artifacts=list(tool_runtime.state.artifacts),
            tool_calls=list(tool_runtime.state.tool_audit),
            pending_approval=tool_runtime.state.pending_approval or exc.pending_approval,
            metadata=metadata,
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
    def _select_committed_actions(
        actions: list[PlannedAction],
        *,
        status: str,
    ) -> list[PlannedAction]:
        """按 run 终态过滤正式提交的动作.

        Args:
            actions: 待过滤的动作列表.
            status: 当前 runtime 终态.

        Returns:
            当前终态允许正式出站的动作列表.
        """

        allowed = {
            "completed": {"success", "always"},
            "failed": {"failure", "always"},
            "waiting_approval": {"waiting_approval", "always"},
        }[status]
        return [item for item in actions if item.commit_when in allowed]

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
