"""runtime.tool_broker.broker 提供 runtime 侧的统一工具入口."""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
import time
import uuid
from inspect import isawaitable
from typing import Any

import structlog

from acabot.agent import ToolDef, ToolExecutionResult, ToolSpec
from acabot.agent.tool import normalize_tool_result
from acabot.types import Action, ActionType

from ..backend.bridge import BackendBridge
from ..backend.contracts import BackendRequest, BackendSourceRef
from ..contracts import ApprovalRequired, DispatchReport, PendingApproval, PlannedAction, ResolvedAgent, RunContext
from ..control.extension_refresh import SkillRefreshPaths
from ..model.model_agent_runtime import ToolRuntime, ToolRuntimeState
from ..skills import SkillCatalog
from ..subagents import SubagentCatalog
from ..control.log_setup import sanitize_inspection_value
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

logger = logging.getLogger("acabot.runtime.tool_broker")
slog = structlog.get_logger("acabot.runtime.tool_broker")


class ToolBroker:
    """runtime 侧的统一工具入口."""

    def __init__(
        self,
        *,
        policy: ToolPolicy | None = None,
        audit: ToolAudit | None = None,
        skill_catalog: SkillCatalog | None = None,
        subagent_catalog: SubagentCatalog | None = None,
        backend_bridge: BackendBridge | None = None,
        admin_host_maintenance_paths_resolver: Callable[[str], SkillRefreshPaths | dict[str, Any] | None] | None = None,
    ) -> None:
        """初始化 ToolBroker.

        Args:
            policy: 可选的工具策略层.
            audit: 可选的工具审计实现.
            skill_catalog: 可选的 skill catalog.
            subagent_catalog: 可选的 subagent catalog.
            backend_bridge: 可选的后台桥接入口, 用于暴露 frontstage backend bridge tool.
            admin_host_maintenance_paths_resolver: 可选的 admin-host 维护路径解析器.
        """

        self._tools: dict[str, RegisteredTool] = {}
        self.policy = policy or AllowAllToolPolicy()
        self.audit = audit or InMemoryToolAudit()
        self.skill_catalog = skill_catalog
        self.subagent_catalog = subagent_catalog
        self.backend_bridge = backend_bridge
        self.admin_host_maintenance_paths_resolver = admin_host_maintenance_paths_resolver

    def register_tool(
        self,
        spec: ToolSpec,
        handler: ToolHandler,
        *,
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册一条工具定义.

        Args:
            spec: 工具 schema.
            handler: 工具执行入口.
            source: 当前工具来源.
            metadata: 附加元数据.
        """

        existing = self._tools.get(spec.name)
        if existing is not None:
            existing_is_builtin = str(existing.source).startswith("builtin:")
            new_is_builtin = str(source).startswith("builtin:")
            if existing_is_builtin and not new_is_builtin:
                logger.warning(
                    "Ignore tool registration that would shadow builtin tool: name=%s source=%s existing_source=%s",
                    spec.name,
                    source,
                    existing.source,
                )
                return
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

    def visible_tools(self, agent: ResolvedAgent) -> list[ToolSpec]:
        """按 agent 解析当前模型可见的工具列表."""

        return self._visible_tools_from_names(agent, self._allowed_tool_names(agent))

    def _visible_tools_from_names(self, agent: ResolvedAgent, tool_names: list[str]) -> list[ToolSpec]:
        """按工具名列表构造最终可见工具描述.

        Args:
            agent: 当前 agent 快照.
            tool_names: 已经过滤后的工具名列表.

        Returns:
            list[ToolSpec]: 最终可见工具列表.
        """

        if not tool_names:
            return []

        visible: list[ToolSpec] = []
        for tool_name in tool_names:
            registered = self._tools.get(tool_name)
            if registered is None:
                continue
            visible.append(self._build_visible_spec(agent, registered))
        return visible

    def _visible_tools_for_run(self, ctx: RunContext, tool_names: list[str]) -> list[ToolSpec]:
        """按当前 run 的上下文构造最终可见工具描述.

        Args:
            ctx: 当前 run 的执行上下文.
            tool_names: 已经过滤后的工具名列表.

        Returns:
            list[ToolSpec]: 当前 run 真正可见的工具列表.
        """

        if not tool_names:
            return []

        visible: list[ToolSpec] = []
        for tool_name in tool_names:
            registered = self._tools.get(tool_name)
            if registered is None:
                continue
            if registered.spec.name == "Skill":
                visible.append(
                    ToolSpec(
                        name=registered.spec.name,
                        description=self._skill_tool_description_for_run(ctx),
                        parameters=dict(registered.spec.parameters),
                    )
                )
                continue
            visible.append(self._build_visible_spec(ctx.agent, registered))
        return visible

    def _build_visible_spec(
        self,
        agent: ResolvedAgent,
        registered: RegisteredTool,
    ) -> ToolSpec:
        if registered.spec.name == "Skill":
            return ToolSpec(
                name=registered.spec.name,
                description=self._skill_tool_description(agent),
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

    def _allowed_tool_names(self, agent: ResolvedAgent) -> list[str]:
        tool_names: list[str] = []
        for tool_name in agent.enabled_tools:
            if tool_name in tool_names:
                continue
            tool_names.append(tool_name)
        if self._should_expose_skill_tool(agent) and "Skill" not in tool_names:
            tool_names.append("Skill")
        if self._should_expose_backend_bridge_tool(agent) and "ask_backend" not in tool_names:
            tool_names.append("ask_backend")
        return tool_names

    def _allowed_tool_names_for_run(self, ctx: RunContext) -> list[str]:
        """按当前 run 的真实上下文过滤工具名列表.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            list[str]: 当前 run 真正可见的工具名列表.
        """

        tool_names: list[str] = []
        for tool_name in ctx.agent.enabled_tools:
            if tool_name in tool_names:
                continue
            tool_names.append(tool_name)

        run_visible_skills = self._visible_skills_for_run(ctx)
        if run_visible_skills:
            if "Skill" in self._tools and "Skill" not in tool_names:
                tool_names.append("Skill")
        else:
            tool_names = [tool_name for tool_name in tool_names if tool_name != "Skill"]

        run_visible_subagents = self._visible_subagents_for_run(ctx)
        if run_visible_subagents:
            if "delegate_subagent" in self._tools and "delegate_subagent" not in tool_names:
                tool_names.append("delegate_subagent")
        else:
            tool_names = [tool_name for tool_name in tool_names if tool_name != "delegate_subagent"]
        if self._should_expose_backend_bridge_tool(ctx.agent) and "ask_backend" not in tool_names:
            tool_names.append("ask_backend")

        if ctx.workspace_state is None:
            return tool_names
        allowed = set(ctx.workspace_state.available_tools)
        return [
            tool_name
            for tool_name in tool_names
            if tool_name in allowed or tool_name not in {"read", "write", "edit", "bash"}
        ]

    def _should_expose_skill_tool(self, agent: ResolvedAgent) -> bool:
        if self.skill_catalog is None:
            return False
        if "Skill" not in self._tools:
            return False
        return bool(self.skill_catalog.visible_skills(agent))

    def _skill_tool_description(self, agent: ResolvedAgent) -> str:
        """为 agent 视角构造 Skill 工具说明.

        Args:
            agent: 当前 agent 快照.

        Returns:
            str: 给模型看的 Skill 工具说明.
        """

        base = (
            "Use Skill(skill=...) to load an assigned skill by name. "
            "The runtime reads SKILL.md and returns the skill base directory under /skills/."
        )
        visible = self._visible_skills(agent)
        if not visible:
            return base
        details = "; ".join(
            f"{item.skill_name}: {item.description}" for item in visible
        )
        return f"{base} Available skills: {details}"

    def _skill_tool_description_for_run(self, ctx: RunContext) -> str:
        """为当前 run 构造 Skill 工具说明.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            str: 当前 run 使用的 Skill 工具说明.
        """

        base = (
            "Use Skill(skill=...) to load a skill from the current /skills world view. "
            "The runtime reads SKILL.md and returns the skill base directory for follow-up reads."
        )
        visible = self._visible_skills_for_run(ctx)
        if not visible:
            return base
        details = "; ".join(
            f"{item.skill_name}: {item.description}" for item in visible
        )
        return f"{base} Available skills: {details}"

    def _visible_skills(self, agent: ResolvedAgent):
        if self.skill_catalog is None:
            return []
        return self.skill_catalog.visible_skills(agent)

    def _visible_skills_for_run(self, ctx: RunContext):
        """按当前 run 的 world 视图过滤可见 skills.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            list[object]: 当前 run 真正可见的 skill 摘要对象列表.
        """

        if self.skill_catalog is None:
            return []
        if ctx.world_view is None:
            return self.skill_catalog.visible_skills(ctx.agent)
        skills_policy = ctx.world_view.root_policies.get("skills")
        if skills_policy is None or not skills_policy.visible:
            return []
        manifests = []
        for skill_name in ctx.world_view.visible_skill_names:
            manifest = self.skill_catalog.get(skill_name)
            if manifest is None:
                continue
            manifests.append(manifest)
        return manifests

    def _visible_skill_summaries(self, agent: ResolvedAgent) -> list[dict[str, Any]]:
        if self.skill_catalog is None:
            return []
        summaries: list[dict[str, Any]] = []
        for item in self.skill_catalog.visible_skills(agent):
            summaries.append(
                {
                    "skill_name": item.skill_name,
                    "description": item.description,
                    "display_name": item.display_name,
                }
            )
        return summaries

    def _visible_skill_summaries_for_run(self, ctx: RunContext) -> list[dict[str, Any]]:
        """按当前 run 的 world 视图过滤 skill 摘要.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            list[dict[str, Any]]: 当前 run 真正可见的 skill 摘要列表.
        """

        summaries: list[dict[str, Any]] = []
        for item in self._visible_skills_for_run(ctx):
            summaries.append(
                {
                    "skill_name": item.skill_name,
                    "description": item.description,
                    "display_name": item.display_name,
                }
            )
        return summaries

    def _visible_subagents_for_run(self, ctx: RunContext) -> list[object]:
        """按当前 run 的 session allowlist 解析可见 subagent."""

        if self.subagent_catalog is None:
            return []
        if ctx.computer_policy_decision is None:
            return []
        manifests = []
        seen: set[str] = set()
        for subagent_name in list(ctx.computer_policy_decision.visible_subagents or []):
            normalized = str(subagent_name or "").strip()
            if not normalized or normalized in seen:
                continue
            manifest = self.subagent_catalog.get(normalized)
            if manifest is None:
                continue
            manifests.append(manifest)
            seen.add(normalized)
        return manifests

    def _visible_subagent_summaries_for_run(self, ctx: RunContext) -> list[dict[str, Any]]:
        """为当前 run 构造可见 subagent 摘要."""

        summaries: list[dict[str, Any]] = []
        for manifest in self._visible_subagents_for_run(ctx):
            summaries.append(
                {
                    "agent_id": manifest.subagent_name,
                    "description": manifest.description,
                    "source": manifest.scope,
                }
            )
        return summaries

    def _should_expose_backend_bridge_tool(self, agent: ResolvedAgent) -> bool:
        """判断当前 agent 是否应看到 frontstage backend bridge tool.

        只在 backend bridge 已配置且 agent.enabled_tools 包含 ask_backend 时暴露。
        """

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
        # 必须在 agent 的 enabled_tools 里才暴露，遵守 session-owned agent 能力边界
        if "ask_backend" not in agent.enabled_tools:
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

    def build_tool_runtime(self, ctx: RunContext) -> ToolRuntime:
        """按当前 RunContext 解析工具可见性与 tool executor."""

        allowed_tool_names = self._allowed_tool_names_for_run(ctx)
        visible_tools = self._visible_tools_for_run(ctx, allowed_tool_names)
        state = ToolRuntimeState()
        visible_subagents = [item.subagent_name for item in self._visible_subagents_for_run(ctx)]
        metadata = {
            "source": "tool_broker",
            "visible_tools": [tool.name for tool in visible_tools],
            "visible_skills": [skill.skill_name for skill in self._visible_skills_for_run(ctx)],
            "visible_skill_summaries": self._visible_skill_summaries_for_run(ctx),
            "visible_subagent_summaries": self._visible_subagent_summaries_for_run(ctx),
        }
        admin_host_maintenance = self._admin_host_maintenance_metadata(ctx)
        if admin_host_maintenance is not None:
            metadata["admin_host_maintenance"] = admin_host_maintenance
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

    def _admin_host_maintenance_metadata(self, ctx: RunContext) -> dict[str, Any] | None:
        """为前台 admin+host run 解析真实 skill 维护提示所需的路径信息。"""

        if self.admin_host_maintenance_paths_resolver is None:
            return None
        if ctx.event_facts is None or not ctx.event_facts.is_bot_admin:
            return None
        if str(ctx.decision.metadata.get("run_kind", "") or "") == "subagent":
            return None
        backend_kind = str(ctx.computer_backend_kind or "").strip()
        if not backend_kind and ctx.workspace_state is not None:
            backend_kind = str(ctx.workspace_state.backend_kind or "").strip()
        if backend_kind != "host":
            return None
        try:
            resolved = self.admin_host_maintenance_paths_resolver(ctx.decision.channel_scope)
        except Exception:
            logger.exception(
                "Failed to resolve admin host maintenance paths for %s",
                ctx.decision.channel_scope,
            )
            return None
        if resolved is None:
            return None
        if isinstance(resolved, SkillRefreshPaths):
            return {
                "session_id": resolved.session_id,
                "project_skill_root_path": resolved.project_skill_root_path,
                "session_dir_path": resolved.session_dir_path,
                "session_config_path": resolved.session_config_path,
                "agent_config_path": resolved.agent_config_path,
            }
        return dict(resolved)

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
        started_at = time.monotonic()
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
                started_at=started_at,
            )

        if "visible_tools" in ctx.metadata:
            visible_tools = list(ctx.metadata.get("visible_tools", []))
        else:
            visible_tools = self._allowed_tool_names(ctx.agent)
        if tool_name not in visible_tools:
            return await self._reject(
                message=f"Tool not enabled for current run: {tool_name}",
                audit_record=audit_record,
                ctx=ctx,
                tool_name=tool_name,
                arguments=arguments,
                started_at=started_at,
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
                started_at=started_at,
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
                started_at=started_at,
            )

        normalized = self._normalize_result(raw)
        normalized.metadata.setdefault("tool_name", tool_name)
        normalized.metadata.setdefault("source", registered.source)
        if ctx.state is not None:
            ctx.state.user_actions.extend(normalized.user_actions)
            ctx.state.artifacts.extend(normalized.artifacts)

        audit_record = await self.audit.complete(audit_record, result=normalized)
        self._append_audit(ctx, audit_record)
        self._log_tool_success(
            ctx=ctx,
            tool_name=tool_name,
            source=registered.source,
            result=normalized,
            duration_ms=self._duration_ms(started_at),
            arguments=arguments,
        )
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

        if "visible_tools" in ctx.metadata:
            visible_tools = list(ctx.metadata.get("visible_tools", []))
        else:
            visible_tools = self._allowed_tool_names(ctx.agent)
        if pending.tool_name not in visible_tools:
            result = self._error_result(
                f"Tool not enabled for current run: {pending.tool_name}",
                tool_name=pending.tool_name,
                arguments=dict(pending.tool_arguments),
            )
            if existing_record is not None:
                existing_record = await self.audit.reject(
                    existing_record,
                    reason=f"Tool not enabled for current run: {pending.tool_name}",
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
        self._log_tool_success(
            ctx=ctx,
            tool_name=pending.tool_name,
            source=registered.source,
            result=normalized,
            duration_ms=None,
            arguments=dict(pending.tool_arguments),
        )
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

        visible_tools = self._allowed_tool_names_for_run(ctx)
        visible_skills = [skill.skill_name for skill in self._visible_skills_for_run(ctx)]
        visible_subagents = [item.subagent_name for item in self._visible_subagents_for_run(ctx)]
        return ToolExecutionContext(
            run_id=ctx.run.run_id,
            thread_id=ctx.thread.thread_id,
            actor_id=ctx.decision.actor_id,
            agent_id=ctx.agent.agent_id,
            target=ctx.event.source,
            agent=ctx.agent,
            world_view=ctx.world_view,
            state=state,
            visible_subagents=visible_subagents,
            metadata={
                "backend_bridge": self.backend_bridge,
                "visible_tools": visible_tools,
                "visible_skills": visible_skills,
                "visible_subagents": visible_subagents,
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
                        "world_path": item.metadata.get("world_path", ""),
                        "execution_path": item.metadata.get("execution_path", ""),
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
        started_at: float | None = None,
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
        self._log_tool_rejection(
            ctx=ctx,
            tool_name=tool_name,
            reason=message,
            duration_ms=self._duration_ms(started_at),
            arguments=arguments,
        )
        return result

    async def _fail(
        self,
        *,
        message: str,
        audit_record: ToolAuditRecord,
        ctx: ToolExecutionContext,
        tool_name: str,
        arguments: dict[str, Any],
        started_at: float | None = None,
    ) -> ToolResult:
        result = self._error_result(message, tool_name=tool_name, arguments=arguments)
        audit_record = await self.audit.fail(audit_record, error=message)
        self._append_audit(ctx, audit_record)
        self._log_tool_failure(
            ctx=ctx,
            tool_name=tool_name,
            error=message,
            duration_ms=self._duration_ms(started_at),
            arguments=arguments,
        )
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

    @staticmethod
    def _duration_ms(started_at: float | None) -> float | None:
        if started_at is None:
            return None
        return round((time.monotonic() - started_at) * 1000, 1)

    @staticmethod
    def _summarize_result(result: ToolResult, *, limit: int = 160) -> str:
        content = result.llm_content
        if isinstance(content, list):
            try:
                text = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                text = str(content)
        else:
            text = str(content or "")
        text = " ".join(text.split())
        if text:
            return text[:limit]
        if result.attachments:
            return f"{len(result.attachments)} attachment(s)"
        if result.metadata:
            return f"metadata_keys={','.join(sorted(result.metadata))}"
        return "empty result"

    @staticmethod
    def _tool_context_fields(ctx: ToolExecutionContext) -> dict[str, Any]:
        return {
            "run_id": ctx.run_id,
            "thread_id": ctx.thread_id,
            "agent_id": ctx.agent_id,
            "actor_id": ctx.actor_id,
        }

    @staticmethod
    def _tool_result_snapshot(result: ToolResult) -> dict[str, Any]:
        return {
            "llm_content": sanitize_inspection_value(result.llm_content),
            "raw": sanitize_inspection_value(result.raw),
            "metadata": sanitize_inspection_value(dict(result.metadata)),
            "attachment_count": len(result.attachments),
            "artifact_count": len(result.artifacts),
            "user_action_count": len(result.user_actions),
        }

    def _log_tool_success(
        self,
        *,
        ctx: ToolExecutionContext,
        tool_name: str,
        source: str,
        result: ToolResult,
        duration_ms: float | None,
        arguments: dict[str, Any],
    ) -> None:
        payload = {
            **self._tool_context_fields(ctx),
            "tool_name": tool_name,
            "source": source,
            "duration_ms": duration_ms,
            "tool_arguments": sanitize_inspection_value(dict(arguments)),
            "tool_result_snapshot": self._tool_result_snapshot(result),
            "result_summary": self._summarize_result(result),
            "attachment_count": len(result.attachments),
        }
        slog.info("Tool executed", **payload)

    def _log_tool_rejection(
        self,
        *,
        ctx: ToolExecutionContext,
        tool_name: str,
        reason: str,
        duration_ms: float | None,
        arguments: dict[str, Any],
    ) -> None:
        slog.warning(
            "Tool rejected",
            **{
                **self._tool_context_fields(ctx),
                "tool_name": tool_name,
                "reason": reason,
                "duration_ms": duration_ms,
                "tool_arguments": sanitize_inspection_value(dict(arguments)),
            },
        )

    def _log_tool_failure(
        self,
        *,
        ctx: ToolExecutionContext,
        tool_name: str,
        error: str,
        duration_ms: float | None,
        arguments: dict[str, Any],
    ) -> None:
        slog.error(
            "Tool execution failed",
            **{
                **self._tool_context_fields(ctx),
                "tool_name": tool_name,
                "error": error,
                "duration_ms": duration_ms,
                "tool_arguments": sanitize_inspection_value(dict(arguments)),
            },
        )


__all__ = ["ToolBroker"]
