"""runtime.tool_broker 提供 runtime 侧的统一工具入口.

组件关系:

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
          |
          +-- ToolPolicy
          +-- ApprovalRequired
          `-- ToolAudit

这个文件当前负责:
- 工具注册
- 按 profile 过滤可见 tools
- 让 broker 自己成为唯一 tool_executor
- 最小 policy 检查
- 最小 audit 记录
- approval 触发和 prompt 生成
- 把 `ToolResult.user_actions/artifacts` 累积到 run 级别状态
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any, Awaitable, Callable, Literal, Protocol

from acabot.agent import Attachment, ToolDef, ToolExecutionResult, ToolSpec
from acabot.agent.tool import normalize_tool_result
from acabot.types import Action, ActionType, EventSource

from .model_agent_runtime import ToolRuntime, ToolRuntimeState
from .models import (
    AgentProfile,
    ApprovalRequired,
    DispatchReport,
    PendingApproval,
    PlannedAction,
    RunContext,
)
from .skills import SkillRegistry

ToolHandler = Callable[[dict[str, Any], "ToolExecutionContext"], Awaitable[Any] | Any]


# region 数据对象
@dataclass(slots=True)
class ToolPolicyDecision:
    """ToolPolicy 的判定结果.

    Attributes:
        allowed (bool): 当前工具是否允许执行.
        requires_approval (bool): 当前工具是否需要先进入审批.
        reason (str | None): 拒绝或备注原因.
        metadata (dict[str, Any]): policy 附加元数据.
    """

    allowed: bool
    requires_approval: bool = False
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolAuditRecord:
    """一次工具执行的最小审计记录.

    Attributes:
        tool_call_id (str): 当前工具调用的唯一标识.
        run_id (str): 当前 run 标识.
        tool_name (str): 工具名.
        status (Literal["started", "waiting_approval", "completed", "rejected", "failed"]): 当前审计状态.
        arguments (dict[str, Any]): 执行参数.
        result (Any): 执行结果摘要.
        error (str | None): 错误信息.
        metadata (dict[str, Any]): 附加审计元数据.
    """

    tool_call_id: str
    run_id: str
    tool_name: str
    status: Literal["started", "waiting_approval", "completed", "rejected", "failed"]
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """把审计记录转成 runtime 侧可消费的 dict.

        Returns:
            一份适合写入 `AgentRuntimeResult.tool_calls` 的字典.
        """

        return {
            "tool_call_id": self.tool_call_id,
            "run_id": self.run_id,
            "name": self.tool_name,
            "status": self.status,
            "arguments": dict(self.arguments),
            "result": self.result,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ToolExecutionContext:
    """ToolBroker 执行工具时使用的上下文.

    Attributes:
        run_id (str): 当前 run 标识.
        thread_id (str): 当前 thread 标识.
        actor_id (str): 当前消息发送者标识.
        agent_id (str): 当前处理消息的 agent 标识.
        target (EventSource): 当前默认回复目标.
        profile (AgentProfile): 当前 run 命中的 profile.
        state (ToolRuntimeState | None): 当前 run 的 tool 累积状态.
        metadata (dict[str, Any]): 执行阶段附加元数据.
    """

    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    target: EventSource
    profile: AgentProfile
    state: ToolRuntimeState | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    """ToolBroker 的标准化工具返回.

    Attributes:
        llm_content (str | list[dict[str, Any]]): 传回给 LLM 的结果内容.
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


# region policy and audit
class ToolPolicy(Protocol):
    """ToolBroker 的动态策略协议.
    
    根据当前的上下文来返回一个 allowed 或 rejected 的判定
    """

    async def allow(
        self,
        *,
        spec: ToolSpec,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolPolicyDecision:
        """判断当前工具是否允许执行.

        Args:
            spec: 目标工具的 ToolSpec.
            arguments: 本次调用参数.
            ctx: 本次工具执行上下文.

        Returns:
            ToolPolicyDecision.
        """

        ...


class ToolAudit(Protocol):
    """ToolBroker 的最小审计协议."""

    async def start(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolAuditRecord:
        """创建一条 started 审计记录."""

        ...

    async def complete(
        self,
        record: ToolAuditRecord,
        *,
        result: ToolResult,
    ) -> ToolAuditRecord:
        """把审计记录收尾为 completed."""

        ...

    async def reject(
        self,
        record: ToolAuditRecord,
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolAuditRecord:
        """把审计记录收尾为 rejected."""

        ...

    async def waiting_approval(
        self,
        record: ToolAuditRecord,
        *,
        approval_id: str,
        required_action_ids: list[str],
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolAuditRecord:
        """把审计记录切到 waiting_approval."""

        ...

    async def confirm_pending_approval(
        self,
        *,
        tool_call_id: str,
        delivery_report: DispatchReport,
    ) -> ToolAuditRecord | None:
        """回写审批提示已送达."""

        ...

    async def fail(
        self,
        record: ToolAuditRecord,
        *,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolAuditRecord:
        """把审计记录收尾为 failed."""

        ...

    async def fail_pending_approval(
        self,
        *,
        tool_call_id: str,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolAuditRecord | None:
        """把等待审批中的审计记录收尾为 failed."""

        ...


class AllowAllToolPolicy:
    """默认允许所有工具的最小 policy."""

    async def allow(
        self,
        *,
        spec: ToolSpec,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolPolicyDecision:
        """始终返回允许.

        Args:
            spec: 目标工具的 ToolSpec.
            arguments: 本次调用参数.
            ctx: 本次工具执行上下文.

        Returns:
            一份允许执行的 ToolPolicyDecision.
        """

        _ = spec, arguments, ctx
        return ToolPolicyDecision(allowed=True)


class InMemoryToolAudit:
    """内存版 ToolAudit.

    Attributes:
        records (dict[str, ToolAuditRecord]): 已记录的审计项.
    """

    def __init__(self) -> None:
        """初始化空的内存审计表."""

        self.records: dict[str, ToolAuditRecord] = {}

    async def start(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolAuditRecord:
        """创建一条 started 审计记录.

        Args:
            tool_name: 目标工具名.
            arguments: 本次调用参数.
            ctx: 本次工具执行上下文.

        Returns:
            新建的 ToolAuditRecord.
        """

        record = ToolAuditRecord(
            tool_call_id=f"toolcall:{uuid.uuid4().hex[:12]}",
            run_id=ctx.run_id,
            tool_name=tool_name,
            status="started",
            arguments=dict(arguments),
            metadata={
                "thread_id": ctx.thread_id,
                "actor_id": ctx.actor_id,
                "agent_id": ctx.agent_id,
                **dict(ctx.metadata),
            },
        )
        self.records[record.tool_call_id] = record
        return record

    async def complete(
        self,
        record: ToolAuditRecord,
        *,
        result: ToolResult,
    ) -> ToolAuditRecord:
        """把审计记录收尾为 completed.

        Args:
            record: 目标审计记录.
            result: 本次工具执行结果.

        Returns:
            更新后的 ToolAuditRecord.
        """

        record.status = "completed"
        record.result = result.raw if result.raw is not None else result.llm_content
        record.metadata.update(dict(result.metadata))
        self.records[record.tool_call_id] = record
        return record

    async def reject(
        self,
        record: ToolAuditRecord,
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolAuditRecord:
        """把审计记录收尾为 rejected.

        Args:
            record: 目标审计记录.
            reason: 拒绝原因.
            metadata: 附加元数据.

        Returns:
            更新后的 ToolAuditRecord.
        """

        record.status = "rejected"
        record.error = reason
        record.metadata.update(dict(metadata or {}))
        self.records[record.tool_call_id] = record
        return record

    async def waiting_approval(
        self,
        record: ToolAuditRecord,
        *,
        approval_id: str,
        required_action_ids: list[str],
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolAuditRecord:
        """把审计记录切到 waiting_approval.

        Args:
            record: 目标审计记录.
            approval_id: 当前审批 ID.
            required_action_ids: 审批提示动作列表.
            reason: 等待审批原因.
            metadata: 附加元数据.

        Returns:
            更新后的 ToolAuditRecord.
        """

        record.status = "waiting_approval"
        record.error = reason
        record.metadata.update(
            {
                "approval_id": approval_id,
                "required_action_ids": list(required_action_ids),
                "approval_prompt_delivered": False,
                **dict(metadata or {}),
            }
        )
        self.records[record.tool_call_id] = record
        return record

    async def confirm_pending_approval(
        self,
        *,
        tool_call_id: str,
        delivery_report: DispatchReport,
    ) -> ToolAuditRecord | None:
        """回写审批提示已送达.

        Args:
            tool_call_id: 待回写的 tool_call_id.
            delivery_report: 当前审批提示的投递报告.

        Returns:
            更新后的 ToolAuditRecord. 找不到时返回 None.
        """

        record = self.records.get(tool_call_id)
        if record is None:
            return None
        record.metadata["approval_prompt_delivered"] = True
        record.metadata["approval_delivery_results"] = [
            {
                "action_id": item.action_id,
                "ok": item.ok,
                "platform_message_id": item.platform_message_id,
                "error": item.error,
            }
            for item in delivery_report.results
        ]
        self.records[tool_call_id] = record
        return record

    async def fail(
        self,
        record: ToolAuditRecord,
        *,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolAuditRecord:
        """把审计记录收尾为 failed.

        Args:
            record: 目标审计记录.
            error: 失败原因.
            metadata: 附加元数据.

        Returns:
            更新后的 ToolAuditRecord.
        """

        record.status = "failed"
        record.error = error
        record.metadata.update(dict(metadata or {}))
        self.records[record.tool_call_id] = record
        return record

    async def fail_pending_approval(
        self,
        *,
        tool_call_id: str,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolAuditRecord | None:
        """把等待审批中的记录收尾为 failed.

        Args:
            tool_call_id: 待回写的 tool_call_id.
            error: 失败原因.
            metadata: 附加元数据.

        Returns:
            更新后的 ToolAuditRecord. 找不到时返回 None.
        """

        record = self.records.get(tool_call_id)
        if record is None:
            return None
        record.status = "failed"
        record.error = error
        record.metadata.update(dict(metadata or {}))
        self.records[tool_call_id] = record
        return record


# endregion


# region broker
class ToolBroker:
    """runtime 侧的统一工具入口.

    Attributes:
        _tools (dict[str, RegisteredTool]): 当前已注册的工具表.
        policy (ToolPolicy): 当前 broker 使用的动态 policy.
        audit (ToolAudit): 当前 broker 使用的 audit sink.
    """

    def __init__(
        self,
        *,
        policy: ToolPolicy | None = None,
        audit: ToolAudit | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        """初始化 ToolBroker.

        Args:
            policy: 可选的动态 policy.
            audit: 可选的审计 sink.
            skill_registry: 可选的显式 skill 注册表.
        """

        self._tools: dict[str, RegisteredTool] = {}
        self.policy = policy or AllowAllToolPolicy()
        self.audit = audit or InMemoryToolAudit()
        self.skill_registry = skill_registry

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

    def unregister_source(self, source: str) -> list[str]:
        """按 source 删除已注册工具.

        Args:
            source: 注册时使用的 source 标识.

        Returns:
            被删除的工具名列表.
        """

        removed: list[str] = []
        for tool_name, registered in list(self._tools.items()):
            if registered.source != source:
                continue
            removed.append(tool_name)
            del self._tools[tool_name]
        return removed

    def visible_tools(self, profile: AgentProfile) -> list[ToolSpec]:
        """返回当前 profile 可以看到的工具列表.

        Args:
            profile: 当前 run 命中的 AgentProfile.

        Returns:
            一个按 profile 声明顺序过滤后的 ToolSpec 列表.
        """
        tool_names = self._allowed_tool_names(profile)
        if not tool_names:
            return []

        visible: list[ToolSpec] = []
        for tool_name in tool_names:
            registered = self._tools.get(tool_name)
            if registered is None:
                continue
            visible.append(registered.spec)
        return visible

    def _allowed_tool_names(self, profile: AgentProfile) -> list[str]:
        """计算当前 profile 可用的工具名集合.

        Args:
            profile: 当前 run 命中的 AgentProfile.

        Returns:
            去重后且按声明顺序展开的工具名列表.
        """

        tool_names: list[str] = []
        for tool_name in profile.enabled_tools:
            if tool_name in tool_names:
                continue
            tool_names.append(tool_name)
        if self.skill_registry is not None:
            for tool_name in self.skill_registry.visible_tool_names(profile):
                if tool_name in tool_names:
                    continue
                tool_names.append(tool_name)
            if self._should_expose_delegate_tool(profile) and "delegate_skill" not in tool_names:
                tool_names.append("delegate_skill")
        return tool_names

    def _should_expose_delegate_tool(self, profile: AgentProfile) -> bool:
        """判断当前 profile 是否应看到 `delegate_skill`.

        Args:
            profile: 当前 run 命中的 AgentProfile.

        Returns:
            当前 profile 是否存在可自动委派的 skill assignment.
        """

        if self.skill_registry is None:
            return False
        if "delegate_skill" not in self._tools:
            return False
        for item in self.skill_registry.resolve_assignments(profile):
            if item.assignment.delegation_mode in {"prefer_delegate", "must_delegate"}:
                return True
        return False

    def build_tool_runtime(self, ctx: RunContext) -> ToolRuntime:
        """为一次 run 构造 ToolRuntime.

        Args:
            ctx: 当前 run 的完整执行上下文.

        Returns:
            一份交给 ModelAgentRuntime 的 ToolRuntime.
        """

        visible_tools = self.visible_tools(ctx.profile)
        state = ToolRuntimeState()
        metadata = {
            "source": "tool_broker",
            "visible_tools": [tool.name for tool in visible_tools],
            "visible_skills": (
                [skill.skill_name for skill in self.skill_registry.visible_skills(ctx.profile)]
                if self.skill_registry is not None
                else []
            ),
        }
        if not visible_tools:
            return ToolRuntime(state=state, metadata=metadata)

        async def executor(
            tool_name: str,
            arguments: dict[str, Any],
        ) -> ToolExecutionResult:
            result = await self.execute(
                tool_name=tool_name,
                arguments=arguments,
                ctx=self._build_execution_context(ctx, state=state),
            )
            return result.to_execution_result()

        return ToolRuntime(
            tools=visible_tools,
            tool_executor=executor,
            state=state,
            metadata=metadata,
        )

    async def confirm_pending_approval(
        self,
        pending: PendingApproval,
        *,
        delivery_report: DispatchReport,
    ) -> ToolAuditRecord | None:
        """回写审批提示已经真实送达.

        Args:
            pending: 当前待审批上下文.
            delivery_report: 当前审批提示的投递报告.

        Returns:
            更新后的 ToolAuditRecord. 找不到时返回 None.
        """

        if not pending.tool_call_id:
            return None
        return await self.audit.confirm_pending_approval(
            tool_call_id=pending.tool_call_id,
            delivery_report=delivery_report,
        )

    async def fail_pending_approval(
        self,
        pending: PendingApproval,
        *,
        error: str,
    ) -> ToolAuditRecord | None:
        """把审批提示送达失败回写到 tool audit.

        Args:
            pending: 当前待审批上下文.
            error: 失败原因.

        Returns:
            更新后的 ToolAuditRecord. 找不到时返回 None.
        """

        if not pending.tool_call_id:
            return None
        return await self.audit.fail_pending_approval(
            tool_call_id=pending.tool_call_id,
            error=error,
            metadata={"approval_id": pending.approval_id},
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

        audit_record = await self._audit_start(
            tool_name=tool_name,
            arguments=arguments,
            ctx=ctx,
        )

        registered = self._tools.get(tool_name)
        if registered is None:
            return await self._reject(
                message=f"Unknown tool: {tool_name}",
                audit_record=audit_record,
                ctx=ctx,
                tool_name=tool_name,
                arguments=arguments,
            )

        if tool_name not in self._allowed_tool_names(ctx.profile):
            return await self._reject(
                message=f"Tool not enabled for profile: {tool_name}",
                audit_record=audit_record,
                ctx=ctx,
                tool_name=tool_name,
                arguments=arguments,
            )

        decision = await self._allow(
            spec=registered.spec,
            arguments=arguments,
            ctx=ctx,
        )
        if decision.allowed and decision.requires_approval:
            raise await self._raise_approval_required(
                tool_name=tool_name,
                arguments=arguments,
                ctx=ctx,
                audit_record=audit_record,
                metadata=dict(decision.metadata),
                reason=decision.reason or f"Tool requires approval: {tool_name}",
            )
        if not decision.allowed:
            return await self._reject(
                message=decision.reason or f"Tool rejected by policy: {tool_name}",
                audit_record=audit_record,
                ctx=ctx,
                tool_name=tool_name,
                arguments=arguments,
                metadata=dict(decision.metadata),
            )

        try:
            raw = registered.handler(arguments, ctx)
            if isawaitable(raw):
                raw = await raw
        except Exception as exc:
            return await self._fail(
                message=f"Tool execution failed: {exc}",
                audit_record=audit_record,
                ctx=ctx,
                tool_name=tool_name,
                arguments=arguments,
            )

        normalized = self._normalize_result(raw)
        normalized.metadata.setdefault("tool_name", tool_name)
        normalized.metadata.setdefault("source", registered.source)
        if ctx.state is not None:
            ctx.state.user_actions.extend(normalized.user_actions)
            ctx.state.artifacts.extend(normalized.artifacts)

        audit_record = await self.audit.complete(audit_record, result=normalized)
        self._append_audit(ctx, audit_record)
        return normalized

    def _build_execution_context(
        self,
        ctx: RunContext,
        *,
        state: ToolRuntimeState | None = None,
    ) -> ToolExecutionContext:
        """从 RunContext 派生 ToolExecutionContext.

        Args:
            ctx: 当前 run 的完整执行上下文.
            state: 当前 run 的 tool 累积状态.

        Returns:
            一份轻量的 ToolExecutionContext.
        """

        return ToolExecutionContext(
            run_id=ctx.run.run_id,
            thread_id=ctx.thread.thread_id,
            actor_id=ctx.decision.actor_id,
            agent_id=ctx.profile.agent_id,
            target=ctx.event.source,
            profile=ctx.profile,
            state=state,
            metadata={
                "channel_scope": ctx.decision.channel_scope,
                "event_id": ctx.event.event_id,
                "event_timestamp": ctx.event.timestamp,
                "sender_role": ctx.event.sender_role or "",
                "platform": ctx.event.platform,
                "message_type": ctx.event.source.message_type,
            },
        )

    def _normalize_result(self, raw: Any) -> ToolResult:
        """把 handler 返回值统一归一化成 ToolResult.

        Args:
            raw: handler 原始返回值.

        Returns:
            一份标准化后的 ToolResult.
        """

        if isinstance(raw, ToolResult):
            return raw

        normalized = normalize_tool_result(raw)
        return ToolResult(
            llm_content=normalized.content,
            attachments=list(normalized.attachments),
            raw=normalized.raw,
        )

    @staticmethod
    def _build_approval_action(
        *,
        tool_name: str,
        ctx: ToolExecutionContext,
        approval_id: str,
        reason: str,
    ) -> PlannedAction:
        """构造一条审批提示动作.

        Args:
            tool_name: 目标工具名.
            ctx: 当前工具执行上下文.
            approval_id: 当前审批 ID.
            reason: 等待审批原因.

        Returns:
            一条 `commit_when="waiting_approval"` 的审批提示动作.
        """

        return PlannedAction(
            action_id=f"action:{approval_id}:prompt",
            action=Action(
                action_type=ActionType.SEND_TEXT,
                target=ctx.target,
                payload={
                    "text": (
                        f"[审批] 工具 {tool_name} 需要批准.\n"
                        f"原因: {reason}\n"
                        f"approval_id: {approval_id}"
                    )
                },
            ),
            thread_content=f"[审批提示] 工具 {tool_name} 等待批准",
            commit_when="waiting_approval",
            metadata={
                "origin": "approval_prompt",
                "approval_id": approval_id,
                "tool_name": tool_name,
            },
        )

    async def _allow(
        self,
        *,
        spec: ToolSpec,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolPolicyDecision:
        """执行动态 policy 检查.

        Args:
            spec: 目标工具的 ToolSpec.
            arguments: 本次调用参数.
            ctx: 本次工具执行上下文.

        Returns:
            一份 ToolPolicyDecision.
        """

        decision = self.policy.allow(spec=spec, arguments=arguments, ctx=ctx)
        if isawaitable(decision):
            decision = await decision
        return decision

    async def _audit_start(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolAuditRecord:
        """创建一条 started 审计记录.

        Args:
            tool_name: 目标工具名.
            arguments: 本次调用参数.
            ctx: 本次工具执行上下文.

        Returns:
            一条 started 状态的 ToolAuditRecord.
        """

        record = self.audit.start(
            tool_name=tool_name,
            arguments=arguments,
            ctx=ctx,
        )
        if isawaitable(record):
            record = await record
        return record

    async def _raise_approval_required(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
        audit_record: ToolAuditRecord,
        metadata: dict[str, Any],
        reason: str,
    ) -> ApprovalRequired:
        """构造并返回一条 ApprovalRequired.

        Args:
            tool_name: 目标工具名.
            arguments: 本次调用参数.
            ctx: 当前工具执行上下文.
            audit_record: 已创建的审计记录.
            metadata: policy 附加元数据.
            reason: 等待审批原因.

        Returns:
            一条构造完成的 ApprovalRequired.
        """

        approval_id = metadata.get("approval_id")
        if not approval_id:
            approval_id = f"approval:{ctx.run_id}:{tool_name}:{uuid.uuid4().hex[:8]}"

        approval_action = self._build_approval_action(
            tool_name=tool_name,
            ctx=ctx,
            approval_id=str(approval_id),
            reason=reason,
        )
        pending = PendingApproval(
            approval_id=str(approval_id),
            reason=reason,
            tool_name=tool_name,
            tool_call_id=audit_record.tool_call_id,
            tool_arguments=dict(arguments),
            required_action_ids=[approval_action.action_id],
            metadata={
                "tool_name": tool_name,
                **metadata,
            },
        )

        audit_record = await self.audit.waiting_approval(
            audit_record,
            approval_id=pending.approval_id,
            required_action_ids=list(pending.required_action_ids),
            reason=pending.reason,
            metadata={
                "tool_name": tool_name,
                **metadata,
            },
        )
        if ctx.state is not None:
            ctx.state.user_actions.append(approval_action)
            ctx.state.pending_approval = pending
        self._append_audit(ctx, audit_record)
        return ApprovalRequired(pending_approval=pending)

    async def _reject(
        self,
        *,
        message: str,
        audit_record: ToolAuditRecord,
        ctx: ToolExecutionContext,
        tool_name: str,
        arguments: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        """以 rejected 状态收尾一次工具调用.

        Args:
            message: 拒绝原因.
            audit_record: 当前审计记录.
            ctx: 当前工具执行上下文.
            tool_name: 目标工具名.
            arguments: 本次调用参数.
            metadata: 附加元数据.

        Returns:
            一份错误 ToolResult.
        """

        result = self._error_result(
            message,
            tool_name=tool_name,
            arguments=arguments,
            metadata=metadata,
        )
        audit_record = await self.audit.reject(
            audit_record,
            reason=message,
            metadata=metadata,
        )
        self._append_audit(ctx, audit_record)
        return result

    async def _fail(
        self,
        *,
        message: str,
        audit_record: ToolAuditRecord,
        ctx: ToolExecutionContext,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """以 failed 状态收尾一次工具调用.

        Args:
            message: 失败原因.
            audit_record: 当前审计记录.
            ctx: 当前工具执行上下文.
            tool_name: 目标工具名.
            arguments: 本次调用参数.

        Returns:
            一份错误 ToolResult.
        """

        result = self._error_result(message, tool_name=tool_name, arguments=arguments)
        audit_record = await self.audit.fail(audit_record, error=message)
        self._append_audit(ctx, audit_record)
        return result

    @staticmethod
    def _append_audit(ctx: ToolExecutionContext, record: ToolAuditRecord) -> None:
        """把审计记录追加到当前 run 的 tool state.

        Args:
            ctx: 当前工具执行上下文.
            record: 已经收尾的审计记录.
        """

        if ctx.state is None:
            return
        ctx.state.tool_audit.append(record.to_dict())

    @staticmethod
    def _error_result(
        message: str,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        """构造统一的错误 ToolResult.

        Args:
            message: 错误描述.
            tool_name: 目标工具名.
            arguments: 执行参数.
            metadata: 附加元数据.

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
            metadata={
                "error": message,
                "tool_name": tool_name,
                **dict(metadata or {}),
            },
            raw=payload,
        )


# endregion
