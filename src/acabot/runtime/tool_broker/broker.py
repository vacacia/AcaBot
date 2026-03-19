"""runtime.tool_broker.broker 提供 runtime 侧的统一工具入口."""

from __future__ import annotations

import json
import uuid
from inspect import isawaitable
from typing import Any

from acabot.agent import ToolDef, ToolExecutionResult, ToolSpec
from acabot.agent.tool import normalize_tool_result
from acabot.types import Action, ActionType

from ..backend.bridge import BackendBridge
from ..backend.contracts import BackendRequest, BackendSourceRef
from ..contracts import AgentProfile, ApprovalRequired, DispatchReport, PendingApproval, PlannedAction, RunContext
from ..model.model_agent_runtime import ToolRuntime, ToolRuntimeState
from ..skills import SkillCatalog
from ..subagents import SubagentExecutorRegistry
from .contracts import (
    RegisteredTool,
    ToolAuditRecord,
    ToolExecutionContext,
    ToolHandler,
    ToolPolicyDecision,
    ToolReplayResult,
    ToolResult,
)
from .policy import AllowAllToolPolicy, InMemoryToolAudit, ToolAudit, ToolPolicy


class ToolBroker:
    """runtime 侧的统一工具入口."""

    def __init__(
        self,
        *,
        policy: ToolPolicy | None = None,
        audit: ToolAudit | None = None,
        skill_catalog: SkillCatalog | None = None,
        subagent_executor_registry: SubagentExecutorRegistry | None = None,
        default_agent_id: str = "",
        backend_bridge: BackendBridge | None = None,
    ) -> None:
        """初始化 ToolBroker.

        Args:
            policy: 可选的工具策略层.
            audit: 可选的工具审计实现.
            skill_catalog: 可选的 skill catalog.
            subagent_executor_registry: 可选的 subagent executor 注册表.
            default_agent_id: 默认主 agent 标识.
            backend_bridge: 可选的后台桥接入口, 用于暴露 frontstage backend bridge tool.
        """

        self._tools: dict[str, RegisteredTool] = {}
        self.policy = policy or AllowAllToolPolicy()
        self.audit = audit or InMemoryToolAudit()
        self.skill_catalog = skill_catalog
        self.subagent_executor_registry = subagent_executor_registry
        self.default_agent_id = str(default_agent_id or "")
        self.backend_bridge = backend_bridge

    def register_tool(
        self,
        spec: ToolSpec,
        handler: ToolHandler,
        *,
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
    ) -> None:
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
        removed: list[str] = []
        for tool_name, registered in list(self._tools.items()):
            if registered.source != source:
                continue
            removed.append(tool_name)
            del self._tools[tool_name]
        return removed

    def list_registered_tools(self) -> list[dict[str, Any]]:
        """列出当前已注册工具的目录视图."""

        items: list[dict[str, Any]] = []
        for tool_name in sorted(self._tools):
            registered = self._tools[tool_name]
            items.append(
                {
                    "name": registered.spec.name,
                    "description": registered.spec.description,
                    "source": registered.source,
                    "parameters": dict(registered.spec.parameters),
                    "metadata": dict(registered.metadata),
                }
            )
        return items

    def visible_tools(self, profile: AgentProfile) -> list[ToolSpec]:
        """按 profile 解析当前模型可见的工具列表."""

        tool_names = self._allowed_tool_names(profile)
        if not tool_names:
            return []

        visible: list[ToolSpec] = []
        for tool_name in tool_names:
            registered = self._tools.get(tool_name)
            if registered is None:
                continue
            visible.append(self._build_visible_spec(profile, registered))
        return visible

    def _build_visible_spec(
        self,
        profile: AgentProfile,
        registered: RegisteredTool,
    ) -> ToolSpec:
        if registered.spec.name == "skill":
            return ToolSpec(
                name=registered.spec.name,
                description=self._skill_tool_description(profile),
                parameters=dict(registered.spec.parameters),
            )
        if registered.spec.name == "ask_backend":
            return ToolSpec(
                name=registered.spec.name,
                description=self._backend_bridge_tool_description(),
                parameters=dict(registered.spec.parameters),
            )
        return ToolSpec(
            name=registered.spec.name,
            description=registered.spec.description,
            parameters=dict(registered.spec.parameters),
        )

    def _allowed_tool_names(self, profile: AgentProfile) -> list[str]:
        tool_names: list[str] = []
        for tool_name in profile.enabled_tools:
            if tool_name in tool_names:
                continue
            tool_names.append(tool_name)
        if self._should_expose_skill_tool(profile) and "skill" not in tool_names:
            tool_names.append("skill")
        if self._should_expose_delegate_tool(profile) and "delegate_subagent" not in tool_names:
            tool_names.append("delegate_subagent")
        if self._should_expose_backend_bridge_tool(profile) and "ask_backend" not in tool_names:
            tool_names.append("ask_backend")
        return tool_names

    def _should_expose_skill_tool(self, profile: AgentProfile) -> bool:
        if self.skill_catalog is None:
            return False
        if "skill" not in self._tools:
            return False
        return bool(self.skill_catalog.visible_skills(profile))

    def _skill_tool_description(self, profile: AgentProfile) -> str:
        base = "Use skill(name=...) to read an assigned skill's SKILL.md."
        visible = self._visible_skills(profile)
        if not visible:
            return base
        details = "; ".join(
            f"{item.skill_name}: {item.description}" for item in visible
        )
        return f"{base} Available skills: {details}"

    def _visible_skills(self, profile: AgentProfile):
        if self.skill_catalog is None:
            return []
        return self.skill_catalog.visible_skills(profile)

    def _visible_skill_summaries(self, profile: AgentProfile) -> list[dict[str, Any]]:
        if self.skill_catalog is None:
            return []
        summaries: list[dict[str, Any]] = []
        for item in self.skill_catalog.visible_skills(profile):
            summaries.append(
                {
                    "skill_name": item.skill_name,
                    "description": item.description,
                    "display_name": item.display_name,
                }
            )
        return summaries

    def _visible_subagent_summaries(self, profile: AgentProfile) -> list[dict[str, Any]]:
        if self.default_agent_id and profile.agent_id != self.default_agent_id:
            return []
        if self.subagent_executor_registry is None:
            return []
        summaries: list[dict[str, Any]] = []
        for item in self.subagent_executor_registry.list_all():
            if item.agent_id == profile.agent_id:
                continue
            summaries.append(
                {
                    "agent_id": item.agent_id,
                    "source": item.source,
                    "profile_name": str(item.metadata.get("profile_name", "") or item.agent_id),
                }
            )
        return summaries

    def _should_expose_backend_bridge_tool(self, profile: AgentProfile) -> bool:
        """判断当前 profile 是否应看到 frontstage backend bridge tool."""

        if self.backend_bridge is None:
            return False
        session_service = getattr(self.backend_bridge, "session", None)
        if session_service is None:
            return False
        is_configured = getattr(session_service, "is_configured", None)
        if not callable(is_configured) or not is_configured():
            return False
        registered = self._tools.get("ask_backend")
        if registered is None:
            return False
        visible_to_default_only = bool(
            registered.metadata.get("visible_to_default_agent_only", False)
        )
        if visible_to_default_only and self.default_agent_id and profile.agent_id != self.default_agent_id:
            return False
        return True

    @staticmethod
    def _backend_bridge_tool_description() -> str:
        """返回前台 backend bridge tool 的说明文本."""

        return (
            "Ask the backend maintainer for a query or a small change. "
            "Only request_kind=query|change is allowed. "
            "The tool only forwards a concise summary plus source reference."
        )

    def _should_expose_delegate_tool(self, profile: AgentProfile) -> bool:
        if "delegate_subagent" not in self._tools:
            return False
        if self.subagent_executor_registry is not None and (
            not self.default_agent_id or profile.agent_id == self.default_agent_id
        ):
            for item in self.subagent_executor_registry.list_all():
                if item.agent_id != profile.agent_id:
                    return True
        return False

    def build_tool_runtime(self, ctx: RunContext) -> ToolRuntime:
        """按当前 RunContext 解析工具可见性与 tool executor."""

        visible_tools = self.visible_tools(ctx.profile)
        state = ToolRuntimeState()
        metadata = {
            "source": "tool_broker",
            "visible_tools": [tool.name for tool in visible_tools],
            "visible_skills": [skill.skill_name for skill in self._visible_skills(ctx.profile)],
            "visible_skill_summaries": self._visible_skill_summaries(ctx.profile),
            "visible_subagent_summaries": self._visible_subagent_summaries(ctx.profile),
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

    async def replay_approved_tool(
        self,
        *,
        pending: PendingApproval,
        ctx: ToolExecutionContext,
    ) -> ToolReplayResult:
        registered = self._tools.get(pending.tool_name)
        existing_record = await self.audit.get(tool_call_id=str(pending.tool_call_id or ""))
        if registered is None:
            result = self._error_result(
                f"Unknown tool: {pending.tool_name}",
                tool_name=pending.tool_name,
                arguments=dict(pending.tool_arguments),
            )
            if existing_record is not None:
                existing_record = await self.audit.fail(
                    existing_record,
                    error=f"Unknown tool: {pending.tool_name}",
                    metadata={
                        "approval_replay": True,
                        "approval_id": pending.approval_id,
                    },
                )
            return ToolReplayResult(
                ok=False,
                result=result,
                audit_record=existing_record,
                status="failed",
            )

        if pending.tool_name not in self._allowed_tool_names(ctx.profile):
            result = self._error_result(
                f"Tool not enabled for profile: {pending.tool_name}",
                tool_name=pending.tool_name,
                arguments=dict(pending.tool_arguments),
            )
            if existing_record is not None:
                existing_record = await self.audit.reject(
                    existing_record,
                    reason=f"Tool not enabled for profile: {pending.tool_name}",
                    metadata={
                        "approval_replay": True,
                        "approval_id": pending.approval_id,
                    },
                )
            return ToolReplayResult(
                ok=False,
                result=result,
                audit_record=existing_record,
                status="rejected",
            )

        decision = await self._allow(
            spec=registered.spec,
            arguments=dict(pending.tool_arguments),
            ctx=ctx,
        )
        if not decision.allowed:
            result = self._error_result(
                decision.reason or f"Tool rejected by policy: {pending.tool_name}",
                tool_name=pending.tool_name,
                arguments=dict(pending.tool_arguments),
                metadata={
                    **dict(decision.metadata),
                    "approval_replay": True,
                    "approval_id": pending.approval_id,
                },
            )
            if existing_record is not None:
                existing_record = await self.audit.reject(
                    existing_record,
                    reason=decision.reason or f"Tool rejected by policy: {pending.tool_name}",
                    metadata={
                        **dict(decision.metadata),
                        "approval_replay": True,
                        "approval_id": pending.approval_id,
                    },
                )
            return ToolReplayResult(
                ok=False,
                result=result,
                audit_record=existing_record,
                status="rejected",
            )

        try:
            raw = registered.handler(dict(pending.tool_arguments), ctx)
            if isawaitable(raw):
                raw = await raw
        except ApprovalRequired:
            result = self._error_result(
                "minimal approval replay does not support nested approval",
                tool_name=pending.tool_name,
                arguments=dict(pending.tool_arguments),
                metadata={
                    "approval_replay": True,
                    "approval_id": pending.approval_id,
                },
            )
            if existing_record is not None:
                existing_record = await self.audit.fail(
                    existing_record,
                    error="minimal approval replay does not support nested approval",
                    metadata={
                        "approval_replay": True,
                        "approval_id": pending.approval_id,
                    },
                )
            return ToolReplayResult(
                ok=False,
                result=result,
                audit_record=existing_record,
                status="failed",
            )
        except Exception as exc:
            result = self._error_result(
                f"Tool execution failed: {exc}",
                tool_name=pending.tool_name,
                arguments=dict(pending.tool_arguments),
                metadata={
                    "approval_replay": True,
                    "approval_id": pending.approval_id,
                },
            )
            if existing_record is not None:
                existing_record = await self.audit.fail(
                    existing_record,
                    error=f"Tool execution failed: {exc}",
                    metadata={
                        "approval_replay": True,
                        "approval_id": pending.approval_id,
                    },
                )
            return ToolReplayResult(
                ok=False,
                result=result,
                audit_record=existing_record,
                status="failed",
            )

        normalized = self._normalize_result(raw)
        normalized.metadata.setdefault("tool_name", pending.tool_name)
        normalized.metadata.setdefault("source", registered.source)
        normalized.metadata.setdefault("approval_replay", True)
        normalized.metadata.setdefault("approval_id", pending.approval_id)
        if ctx.state is not None:
            ctx.state.user_actions.extend(normalized.user_actions)
            ctx.state.artifacts.extend(normalized.artifacts)

        if existing_record is not None:
            existing_record = await self.audit.complete(existing_record, result=normalized)
            self._append_audit(ctx, existing_record)
        return ToolReplayResult(
            ok=True,
            result=normalized,
            audit_record=existing_record,
            status="completed",
        )

    def _build_execution_context(
        self,
        ctx: RunContext,
        *,
        state: ToolRuntimeState | None = None,
    ) -> ToolExecutionContext:
        """把 RunContext 投影成工具执行时使用的最小上下文."""

        return ToolExecutionContext(
            run_id=ctx.run.run_id,
            thread_id=ctx.thread.thread_id,
            actor_id=ctx.decision.actor_id,
            agent_id=ctx.profile.agent_id,
            target=ctx.event.source,
            profile=ctx.profile,
            state=state,
            metadata={
                "backend_bridge": self.backend_bridge,
                "default_agent_id": self.default_agent_id,
                "channel_scope": ctx.decision.channel_scope,
                "event_id": ctx.event.event_id,
                "event_timestamp": ctx.event.timestamp,
                "sender_role": ctx.event.sender_role or "",
                "platform": ctx.event.platform,
                "message_type": ctx.event.source.message_type,
                "workspace_visible_root": (
                    ctx.workspace_state.workspace_visible_root
                    if ctx.workspace_state is not None
                    else ""
                ),
                "workspace_host_path": (
                    ctx.workspace_state.workspace_host_path
                    if ctx.workspace_state is not None
                    else ""
                ),
                "backend_kind": (
                    ctx.workspace_state.backend_kind
                    if ctx.workspace_state is not None
                    else ""
                ),
                "read_only": (
                    bool(ctx.workspace_state.read_only)
                    if ctx.workspace_state is not None
                    else False
                ),
                "allow_write": (
                    bool(ctx.computer_policy_effective.allow_write)
                    if ctx.computer_policy_effective is not None
                    else True
                ),
                "allow_exec": (
                    bool(ctx.computer_policy_effective.allow_exec)
                    if ctx.computer_policy_effective is not None
                    else True
                ),
                "allow_sessions": (
                    bool(ctx.computer_policy_effective.allow_sessions)
                    if ctx.computer_policy_effective is not None
                    else True
                ),
                "network_mode": (
                    str(ctx.computer_policy_effective.network_mode)
                    if ctx.computer_policy_effective is not None
                    else "enabled"
                ),
                "active_session_ids": (
                    list(ctx.workspace_state.active_session_ids)
                    if ctx.workspace_state is not None
                    else []
                ),
                "mirrored_skill_names": (
                    list(ctx.workspace_state.mirrored_skill_names)
                    if ctx.workspace_state is not None
                    else []
                ),
                "staged_attachments": [
                    {
                        "event_id": item.event_id,
                        "attachment_index": item.attachment_index,
                        "type": item.type,
                        "original_source": item.original_source,
                        "source_kind": item.source_kind,
                        "staged_path": item.staged_path,
                        "size_bytes": item.size_bytes,
                        "download_status": item.download_status,
                        "error": item.error,
                    }
                    for item in ctx.attachment_snapshots
                ],
            },
        )

    def _normalize_result(self, raw: Any) -> ToolResult:
        """把 handler 返回值归一化成 ToolResult."""

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
        result = self._error_result(message, tool_name=tool_name, arguments=arguments)
        audit_record = await self.audit.fail(audit_record, error=message)
        self._append_audit(ctx, audit_record)
        return result

    @staticmethod
    def _append_audit(ctx: ToolExecutionContext, record: ToolAuditRecord) -> None:
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


__all__ = ["ToolBroker"]
