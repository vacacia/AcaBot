"""runtime.tool_broker 提供 runtime 侧的统一工具入口.

    Plugin / Bootstrap
          |
          v
      ToolBroker.register_*
          |
          v
      ToolBroker.build_tool_runtime()
          |
          v
      ModelAgentRuntime -> BaseAgent.run(tools, tool_executor)
          |
          v
      ToolBroker.execute()

- 工具注册
- 按 profile 过滤可见 tools
- 让 broker 自己成为唯一 tool_executor

暂时不把 approval 状态机做进来.
先把执行权从 agent 身上拿走, 后面再把审批和审计叠上来.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any, Awaitable, Callable

from acabot.agent import Attachment, ToolDef, ToolExecutionResult, ToolSpec
from acabot.agent.tool import normalize_tool_result

from .model_agent_runtime import ToolRuntime
from .models import AgentProfile, PlannedAction, RunContext

ToolHandler = Callable[[dict[str, Any], "ToolExecutionContext"], Awaitable[Any] | Any]


# region 数据对象
@dataclass(slots=True)
class ToolExecutionContext:
    """ToolBroker 执行工具时使用的上下文.

    Attributes:
        run_id (str): 当前 run 标识.
        thread_id (str): 当前 thread 标识.
        actor_id (str): 当前消息发送者标识.
        agent_id (str): 当前处理消息的 agent 标识.
        profile (AgentProfile): 当前 run 命中的 profile.
        metadata (dict[str, Any]): 执行阶段附加元数据.
    """

    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    profile: AgentProfile
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    """ToolBroker 的标准化工具返回.

    Attributes:
        llm_content (str | list[dict[str, Any]]): 传回给 LLM 上下文的内容, 让模型知道执行结果.
        attachments (list[Attachment]): 工具产出的附件列表.
        user_actions (list[PlannedAction]): 工具建议的用户可见动作.
        artifacts (list[dict[str, Any]]): 工具产出的结构化 artifact.
        metadata (dict[str, Any]): 额外元数据.
        raw (Any): 原始执行结果, 便于审计或调试.
    """

    llm_content: str | list[dict[str, Any]] = ""
    attachments: list[Attachment] = field(default_factory=list)
    user_actions: list[PlannedAction] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def to_execution_result(self) -> ToolExecutionResult:
        """把 ToolResult 转成 agent 侧的 ToolExecutionResult.
        
        剔除 artifacts 和 user_actions
        
        Returns:
            交给 BaseAgent 的 ToolExecutionResult, 包含,llm_content, attachments, raw/metadata
        """

        return ToolExecutionResult(
            content=self.llm_content,
            attachments=list(self.attachments),
            raw=self.raw if self.raw is not None else dict(self.metadata),
        )


@dataclass(slots=True)
class RegisteredTool:
    """ToolBroker 内部持有的注册工具.

    Attributes:
        spec (ToolSpec): 模型可见的 tool schema.
        handler (ToolHandler): 真正执行工具的 handler.
        source (str): 工具来源, 便于调试和未来审计.
        metadata (dict[str, Any]): 工具注册时的附加元数据.
    """

    spec: ToolSpec
    handler: ToolHandler
    source: str = "runtime"
    metadata: dict[str, Any] = field(default_factory=dict)


# endregion


# region broker
class ToolBroker:
    """runtime 侧的统一工具入口.

    Attributes:
        _tools (dict[str, RegisteredTool]): 当前已注册的工具表.
    """

    def __init__(self) -> None:
        """初始化空的 ToolBroker."""

        self._tools: dict[str, RegisteredTool] = {}

    def register_tool(
        self,
        spec: ToolSpec,
        handler: ToolHandler,
        *,
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册一条正式工具.

        Args:
            spec: 模型可见的 ToolSpec.
            handler: 真实执行逻辑.
            source: 工具来源标识.
            metadata: 注册附加元数据.
        """

        self._tools[spec.name] = RegisteredTool(
            spec=spec,
            handler=handler,
            source=source,
            metadata=dict(metadata or {}),
        )

    def register_legacy_tool(
        self,
        tool: ToolDef,
        *,
        source: str = "legacy_tool_def",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """把 legacy ToolDef 注册到 ToolBroker.

        Args:
            tool: 旧的 ToolDef 定义.
            source: 工具来源标识.
            metadata: 注册附加元数据.
        """

        async def legacy_handler(
            arguments: dict[str, Any],
            ctx: ToolExecutionContext,
        ) -> Any:
            _ = ctx
            result = tool.handler(arguments)
            if isawaitable(result):
                result = await result
            return result

        self.register_tool(
            tool.to_spec(),
            legacy_handler,
            source=source,
            metadata=metadata,
        )

    def visible_tools(self, profile: AgentProfile) -> list[ToolSpec]:
        """返回当前 profile 可以看到的工具列表.

        Args:
            profile: 当前 run 命中的 AgentProfile.

        Returns:
            一个按注册顺序过滤后的 ToolSpec 列表.
        """

        if not profile.enabled_tools:
            return []

        visible: list[ToolSpec] = []
        for tool_name in profile.enabled_tools:
            registered = self._tools.get(tool_name)
            if registered is None:
                continue
            visible.append(registered.spec)
        return visible

    def build_tool_runtime(self, ctx: RunContext) -> ToolRuntime:
        """为一次 run 构造 ToolRuntime.

        Args:
            ctx: 当前 run 的完整执行上下文.

        Returns:
            一份交给 ModelAgentRuntime 的 ToolRuntime.
        """
        
        # 筛选出当前 bot 有权使用的工具
        visible_tools = self.visible_tools(ctx.profile)
        metadata = {
            "source": "tool_broker",
            "visible_tools": [tool.name for tool in visible_tools],
        }
        if not visible_tools:
            return ToolRuntime(metadata=metadata)

        async def executor(
            tool_name: str,
            arguments: dict[str, Any],
        ) -> ToolExecutionResult:
            # LLM 契约要求 executor 只能接收 (tool_name, arguments) 两个参数
            # 为了带上背景信息使用闭包: 内层函数引用了外层的 ctx
            result = await self.execute(
                tool_name=tool_name,
                arguments=arguments,
                ctx=self._build_execution_context(ctx),
            )
            return result.to_execution_result()

        return ToolRuntime(
            tools=visible_tools,
            tool_executor=executor,
            metadata=metadata,
        )

    async def execute(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """执行一次工具调用.

        Args:
            tool_name: 目标工具名.
            arguments: LLM 传入的参数.
            ctx: 本次工具执行上下文.

        Returns:
            一份标准化后的 ToolResult.
        """
        # 工具存在?
        registered = self._tools.get(tool_name)
        if registered is None:
            return self._error_result(
                f"Unknown tool: {tool_name}",
                tool_name=tool_name,
                arguments=arguments,
            )
        # 工具有权限?
        if tool_name not in ctx.profile.enabled_tools:
            return self._error_result(
                f"Tool not enabled for profile: {tool_name}",
                tool_name=tool_name,
                arguments=arguments,
            )
        # 执行
        raw = registered.handler(arguments, ctx)
        if isawaitable(raw):
            raw = await raw
        # 标注化为 ToolResult
        normalized = self._normalize_result(raw)
        normalized.metadata.setdefault("tool_name", tool_name)
        normalized.metadata.setdefault("source", registered.source)
        return normalized

    def _build_execution_context(self, ctx: RunContext) -> ToolExecutionContext:
        """从 RunContext 派生 ToolExecutionContext.

        Args:
            ctx: 当前 run 的完整执行上下文.

        Returns:
            一份轻量的 ToolExecutionContext.
        """

        return ToolExecutionContext(
            run_id=ctx.run.run_id,
            thread_id=ctx.thread.thread_id,
            actor_id=ctx.decision.actor_id,
            agent_id=ctx.profile.agent_id,
            profile=ctx.profile,
            metadata={
                "channel_scope": ctx.decision.channel_scope,
                "event_id": ctx.event.event_id,
            },
        )

    def _normalize_result(self, raw: Any) -> ToolResult:
        """把 handler 返回值统一归一化成 ToolResult.

        Args:
            raw: handler 原始返回值.

        Returns:
            一份标准化后的 ToolResult.
        """
        # 1. 返回标准的 ToolResult, 直接通过
        if isinstance(raw, ToolResult):
            return raw

        # 2. 强制转换为 ToolExecutionResult
        normalized = normalize_tool_result(raw)
        return ToolResult(
            llm_content=normalized.content,
            attachments=list(normalized.attachments),
            raw=normalized.raw,
        )

    @staticmethod
    def _error_result(
        message: str,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """构造统一的错误 ToolResult.

        Args:
            message: 错误描述.
            tool_name: 目标工具名.
            arguments: 执行参数.

        Returns:
            一份用于返回给 LLM 的错误结果.
        """

        payload = {
            "error": message,
            "tool_name": tool_name,
            "arguments": arguments,
        }
        return ToolResult(
            llm_content=json.dumps(payload, ensure_ascii=False),
            metadata={"error": message, "tool_name": tool_name},
            raw=payload,
        )


# endregion
