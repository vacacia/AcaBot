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

from ..agent_runtime import AgentRuntime
from ..context_assembly import ContextAssembler, PayloadJsonWriter
from ..contracts import AgentRuntimeResult, ApprovalRequired, PendingApproval, PlannedAction, RunContext
from ..control.profile_loader import PromptLoader


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
        context_assembler: ContextAssembler | None = None,
        payload_json_writer: PayloadJsonWriter | None = None,
    ) -> None:
        """初始化 ModelAgentRuntime.

        Args:
            agent: 满足新 `BaseAgent` 契约的 agent.
            prompt_loader: 根据 `prompt_ref` 加载 system prompt 的 loader.
            tool_runtime_resolver: 可选的 tool runtime 解析器.
            context_assembler: 可选的正式上下文组装器.
            payload_json_writer: 可选的 payload json 写入器.
        """

        self.agent = agent
        self.prompt_loader = prompt_loader
        self.tool_runtime_resolver = tool_runtime_resolver
        self.context_assembler = context_assembler or ContextAssembler()
        self.payload_json_writer = payload_json_writer

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

        tool_runtime = await self._resolve_tool_runtime(ctx)
        assembled = self.context_assembler.assemble(
            ctx,
            base_prompt=self.prompt_loader.load(ctx.profile.prompt_ref),
            tool_runtime=tool_runtime,
        )
        ctx.system_prompt = assembled.system_prompt
        ctx.messages = assembled.messages
        capability_error = self._validate_model_capabilities(ctx, tool_runtime)
        if capability_error is not None:
            return capability_error
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

        # 从 RunContext.model_request 中提取出模型名字符串: model_request -> resolved_model 
        resolved_model = (
            ctx.model_request.model
            if ctx.model_request is not None and ctx.model_request.model
            else ctx.profile.default_model
        )
        request_options = (
            ctx.model_request.to_request_options()
            if ctx.model_request is not None
            else None
        )
        max_tool_rounds = self._resolve_max_tool_rounds(ctx)
        self._write_payload_json(
            ctx,
            tool_runtime=tool_runtime,
            resolved_model=resolved_model,
            request_options=request_options,
            max_tool_rounds=max_tool_rounds,
        )
        # 防止幻觉, 适配 API, 省 token
        if not tool_runtime.tools and tool_runtime.tool_executor is None:
            return await self.agent.run(
                system_prompt=ctx.system_prompt,
                messages=ctx.messages,
                model=resolved_model,
                request_options=request_options,
                max_tool_rounds=max_tool_rounds,
            )

        return await self.agent.run(
            system_prompt=ctx.system_prompt,
            messages=ctx.messages,
            model=resolved_model,
            request_options=request_options,
            max_tool_rounds=max_tool_rounds,
            tools=tool_runtime.tools,
            tool_executor=tool_runtime.tool_executor,
        )

    def _write_payload_json(
        self,
        ctx: RunContext,
        *,
        tool_runtime: ToolRuntime,
        resolved_model: str,
        request_options: dict[str, Any] | None,
        max_tool_rounds: int | None,
    ) -> None:
        """在真正调模型前写出最终 payload json.

        Args:
            ctx: 当前 run 的执行上下文.
            tool_runtime: 当前 run 的 tool runtime.
            resolved_model: 当前真正要调用的模型名.
            request_options: 当前请求选项.
            max_tool_rounds: 当前 tool loop 上限.
        """

        if self.payload_json_writer is None:
            return
        self.payload_json_writer.write(
            run_id=ctx.run.run_id,
            payload={
                "model": resolved_model,
                "system_prompt": ctx.system_prompt,
                "messages": ctx.messages,
                "tools": [self._serialize_tool_spec(item) for item in tool_runtime.tools],
                "has_tool_executor": tool_runtime.tool_executor is not None,
                "tool_executor": tool_runtime.tool_executor,
                "request_options": dict(request_options or {}),
                "max_tool_rounds": max_tool_rounds,
            },
        )

    @staticmethod
    def _serialize_tool_spec(spec: ToolSpec) -> dict[str, Any]:
        """把 ToolSpec 收成可写入 json 的结构.

        Args:
            spec: 当前 tool schema.

        Returns:
            一份可写入 json 的工具定义.
        """

        return {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        }

    @staticmethod
    def _validate_model_capabilities(
        ctx: RunContext,
        tool_runtime: ToolRuntime,
    ) -> AgentRuntimeResult | None:
        """在真正调用模型前执行最小 capability 检查."""

        request = ctx.model_request
        if request is None:
            return None
        # request.supports_tools 是模型能力的声明
        if (tool_runtime.tools or tool_runtime.tool_executor is not None) and not request.supports_tools:
            return AgentRuntimeResult(
                status="failed",
                error=f"model does not support tools: {request.model}",
                metadata={
                    "provider_kind": request.provider_kind,
                    "binding_id": request.binding_id,
                    "preset_id": request.preset_id,
                },
            )
        return None

    @staticmethod
    def _resolve_max_tool_rounds(ctx: RunContext) -> int | None:
        """按当前 profile 解析本次 run 的 tool loop 上限."""

        raw = ctx.profile.config.get("max_tool_rounds")
        if raw not in {None, ""}:
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None
        return None

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
        actions.extend(self._attachment_to_actions(ctx, getattr(response, "attachments", []) or []))
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
    def _attachment_to_actions(
        ctx: RunContext,
        attachments: list[Attachment | Any],
    ) -> list[PlannedAction]:
        """把 attachment 列表转换成 SEND_SEGMENTS 动作.

        Args:
            ctx: 当前 run 的执行上下文.
            attachments: model 返回的附件列表.

        Returns:
            一组可直接交给 Outbox 的 PlannedAction.
        """

        actions: list[PlannedAction] = []
        for index, item in enumerate(attachments):
            plan = ModelAgentRuntime._attachment_to_action(ctx, item, index=index)
            if plan is not None:
                actions.append(plan)
        return actions

    @staticmethod
    def _attachment_to_action(
        ctx: RunContext,
        attachment: Attachment | Any,
        *,
        index: int,
    ) -> PlannedAction | None:
        """把单个 attachment 转成一条 PlannedAction.

        Args:
            ctx: 当前 run 的执行上下文.
            attachment: 单个附件对象.
            index: 当前附件在结果中的顺序.

        Returns:
            转换后的 PlannedAction. 无法表达时返回 None.
        """

        att_type = str(getattr(attachment, "type", "") or "")
        att_url = str(getattr(attachment, "url", "") or "")
        att_data = str(getattr(attachment, "data", "") or "")

        if att_type == "image":
            if att_url:
                file_value = att_url
            elif att_data:
                file_value = f"base64://{att_data}"
            else:
                return None
            segments = [{"type": "image", "data": {"file": file_value}}]
            thread_content = "[图片]"
        else:
            placeholder = f"[{att_type or 'file'}: {att_url or '(no url)'}]"
            segments = [{"type": "text", "data": {"text": placeholder}}]
            thread_content = placeholder

        return PlannedAction(
            action_id=f"action:{ctx.run.run_id}:attachment:{index}",
            action=Action(
                action_type=ActionType.SEND_SEGMENTS,
                target=ctx.event.source,
                payload={"segments": segments},
            ),
            thread_content=thread_content,
            commit_when="success",
            metadata={
                "origin": "model_attachment",
                "attachment_type": att_type or "file",
            },
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
