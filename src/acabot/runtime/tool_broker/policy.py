"""runtime.tool_broker.policy 定义 tool policy 与 audit."""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from acabot.agent import ToolSpec

from ..contracts import DispatchReport
from .contracts import ToolAuditRecord, ToolExecutionContext, ToolPolicyDecision, ToolResult


class ToolPolicy(Protocol):
    """ToolBroker 的动态策略协议."""

    async def allow(
        self,
        *,
        spec: ToolSpec,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolPolicyDecision:
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
        ...

    async def complete(
        self,
        record: ToolAuditRecord,
        *,
        result: ToolResult,
    ) -> ToolAuditRecord:
        ...

    async def reject(
        self,
        record: ToolAuditRecord,
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolAuditRecord:
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
        ...

    async def confirm_pending_approval(
        self,
        *,
        tool_call_id: str,
        delivery_report: DispatchReport,
    ) -> ToolAuditRecord | None:
        ...

    async def fail(
        self,
        record: ToolAuditRecord,
        *,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolAuditRecord:
        ...

    async def fail_pending_approval(
        self,
        *,
        tool_call_id: str,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolAuditRecord | None:
        ...

    async def get(self, *, tool_call_id: str) -> ToolAuditRecord | None:
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
        _ = spec, arguments, ctx
        return ToolPolicyDecision(allowed=True)


class InMemoryToolAudit:
    """内存版 ToolAudit."""

    def __init__(self) -> None:
        self.records: dict[str, ToolAuditRecord] = {}

    async def start(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolAuditRecord:
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
        record = self.records.get(tool_call_id)
        if record is None:
            return None
        record.status = "failed"
        record.error = error
        record.metadata.update(dict(metadata or {}))
        self.records[tool_call_id] = record
        return record

    async def get(self, *, tool_call_id: str) -> ToolAuditRecord | None:
        return self.records.get(tool_call_id)


__all__ = [
    "AllowAllToolPolicy",
    "InMemoryToolAudit",
    "ToolAudit",
    "ToolPolicy",
]
