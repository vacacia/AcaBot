"""runtime.approval_resumer 定义 approval decision 之后的续执行接口.

RuntimeApp 只管状态和审计，不管业务逻辑

拆解:
- `RuntimeApp` 里的审批决策
- 具体如何继续执行后续逻辑

当前 runtime 没有正式 `ToolBroker`, 先提供一个可插拔接口.后续 tool approval resume 接到这里.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import time
from typing import Any, Literal

from acabot.types import EventSource, StandardEvent

from .computer import ComputerRuntime
from .model.model_agent_runtime import ToolRuntimeState
from .contracts import PendingApproval, RouteDecision, RunContext, RunRecord
from .storage.threads import ThreadManager
from .tool_broker import ToolBroker

ApprovalResumeStatus = Literal[
    "completed",
    "completed_with_errors",
    "failed",
    "waiting_approval",
]


# region result
@dataclass(slots=True)
class ApprovalResumeResult:
    """approval 恢复动作的系统级结果.

    这个结果只描述恢复之后 run 应该进入什么状态.
    最终的 run 状态迁移仍由 `RuntimeApp` 统一完成.
    """

    status: ApprovalResumeStatus = "completed"
    message: str = ""
    approval_context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# endregion


# region protocol
class ApprovalResumer(ABC):
    """approval 通过后的续执行接口."""

    @abstractmethod
    async def resume(
        self,
        *,
        run: RunRecord,
        approval_context: dict[str, Any],
        metadata: dict[str, Any],
    ) -> ApprovalResumeResult:
        """在 approval 通过后继续执行后续流程.

        Args:
            run: 当前 waiting approval 的 RunRecord.
            approval_context: 当前 run 上保存的审批上下文.
            metadata: 这次 approval decision 的附加元数据.

        Returns:
            一份描述恢复结果的 ApprovalResumeResult.
        """

        ...


# endregion


# region default
class NoopApprovalResumer(ApprovalResumer):
    """默认的 approval resumer - 没配置 resumer 默认失败.

    在真正的 tool approval resume 落地之前, 默认实现明确返回 failed.
    这样不会让系统悄悄吞掉一次 approval.
    """

    async def resume(
        self,
        *,
        run: RunRecord,
        approval_context: dict[str, Any],
        metadata: dict[str, Any],
    ) -> ApprovalResumeResult:
        """返回一个明确失败的恢复结果.

        Args:
            run: 当前 waiting approval 的 RunRecord.
            approval_context: 当前 run 的审批上下文.
            metadata: 这次 approval decision 的附加元数据.

        Returns:
            一份 `failed` 的 ApprovalResumeResult.
        """

        return ApprovalResumeResult(
            status="failed",
            message="approval resumer is not configured",
        )


class ToolApprovalResumer(ApprovalResumer):
    """最小 tool-aware approval resumer.

    批准后只重放被打断的工具调用，不恢复原始 LLM tool loop。
    """

    def __init__(
        self,
        *,
        thread_manager: ThreadManager,
        profile_loader,
        tool_broker: ToolBroker,
        computer_runtime: ComputerRuntime | None = None,
    ) -> None:
        self.thread_manager = thread_manager
        self.profile_loader = profile_loader
        self.tool_broker = tool_broker
        self.computer_runtime = computer_runtime

    async def resume(
        self,
        *,
        run: RunRecord,
        approval_context: dict[str, Any],
        metadata: dict[str, Any],
    ) -> ApprovalResumeResult:
        if bool(run.metadata.get("subagent_child_run")) or str(run.metadata.get("run_kind", "") or "") == "subagent":
            return ApprovalResumeResult(
                status="failed",
                message="subagent child runs do not support approval resume",
                approval_context=dict(approval_context),
            )

        pending = self._pending_from_context(approval_context)
        if pending is None:
            return ApprovalResumeResult(
                status="failed",
                message="approval context is missing tool replay data",
                approval_context=dict(approval_context),
            )

        thread = await self.thread_manager.get(run.thread_id)
        if thread is None:
            return ApprovalResumeResult(
                status="failed",
                message="thread not found for approval replay",
                approval_context=dict(approval_context),
                metadata={"tool_name": pending.tool_name},
            )

        decision = RouteDecision(
            thread_id=run.thread_id,
            actor_id=run.actor_id,
            agent_id=run.agent_id,
            channel_scope=thread.channel_scope,
            metadata=dict(run.metadata),
        )
        try:
            profile = self.profile_loader(decision)
        except Exception as exc:
            return ApprovalResumeResult(
                status="failed",
                message=f"failed to load profile for approval replay: {exc}",
                approval_context=dict(approval_context),
                metadata={"tool_name": pending.tool_name},
            )

        ctx = RunContext(
            run=run,
            event=self._build_resume_event(run=run, thread=thread),
            decision=decision,
            thread=thread,
            profile=profile,
            metadata={
                "approval_resume": True,
                "approval_decision_metadata": dict(metadata),
            },
        )
        if self.computer_runtime is not None:
            await self.computer_runtime.prepare_run_context(ctx)

        state = ToolRuntimeState()
        execution_ctx = self.tool_broker._build_execution_context(ctx, state=state)
        execution_ctx.metadata["approval_resume"] = True
        execution_ctx.metadata["approved_tool_call_id"] = str(pending.tool_call_id or "")
        execution_ctx.metadata["approved_approval_id"] = pending.approval_id

        replay = await self.tool_broker.replay_approved_tool(
            pending=pending,
            ctx=execution_ctx,
        )
        replay_error = str(replay.result.metadata.get("error", "") or "")
        if not replay_error and isinstance(replay.result.raw, dict):
            replay_error = str(replay.result.raw.get("error", "") or "")
        replay_metadata = {
            "tool_name": pending.tool_name,
            "tool_call_id": pending.tool_call_id,
            "approval_id": pending.approval_id,
            "audit_record_found": replay.audit_record is not None,
            "undelivered_user_action_count": len(state.user_actions),
            "undelivered_attachment_count": len(replay.result.attachments),
            "artifact_count": len(state.artifacts),
            "decision_metadata": dict(metadata),
        }
        if not replay.ok:
            return ApprovalResumeResult(
                status="failed",
                message=replay_error or "approval replay failed",
                approval_context=dict(approval_context),
                metadata=replay_metadata,
            )

        if state.user_actions or replay.result.attachments:
            return ApprovalResumeResult(
                status="completed_with_errors",
                message="approval replay produced follow-up outputs that were not delivered",
                approval_context=dict(approval_context),
                metadata={
                    **replay_metadata,
                    "undelivered_user_actions": [
                        action.action_id for action in state.user_actions
                    ],
                    "undelivered_attachment_types": [
                        attachment.type for attachment in replay.result.attachments
                    ],
                },
            )

        return ApprovalResumeResult(
            status="completed",
            approval_context=dict(approval_context),
            metadata=replay_metadata,
        )

    @staticmethod
    def _pending_from_context(approval_context: dict[str, Any]) -> PendingApproval | None:
        tool_name = str(approval_context.get("tool_name", "") or "").strip()
        if not tool_name:
            return None
        return PendingApproval(
            approval_id=str(approval_context.get("approval_id", "") or ""),
            reason=str(approval_context.get("reason", "") or "approval replay"),
            tool_name=tool_name,
            tool_call_id=str(approval_context.get("tool_call_id", "") or "") or None,
            tool_arguments=dict(approval_context.get("tool_arguments", {}) or {}),
            required_action_ids=[
                str(item)
                for item in list(approval_context.get("required_action_ids", []) or [])
                if str(item)
            ],
            metadata=dict(approval_context.get("metadata", {}) or {}),
        )

    @staticmethod
    def _build_resume_event(
        *,
        run: RunRecord,
        thread,
    ) -> StandardEvent:
        source = ToolApprovalResumer._build_event_source(
            channel_scope=thread.channel_scope,
            actor_id=run.actor_id,
        )
        return StandardEvent(
            event_id=f"evt:approval-resume:{run.run_id}",
            event_type="message",
            platform=source.platform,
            timestamp=int(time.time()),
            source=source,
            segments=[],
            raw_message_id="",
            sender_nickname="approval-resume",
            sender_role=None,
            metadata={"approval_resume": True},
        )

    @staticmethod
    def _build_event_source(
        *,
        channel_scope: str,
        actor_id: str,
    ) -> EventSource:
        platform, scope_kind, scope_value = (channel_scope.split(":", 2) + ["", "", ""])[:3]
        actor_user_id = actor_id.split(":")[-1]
        if scope_kind == "group":
            return EventSource(
                platform=platform or "runtime",
                message_type="group",
                user_id=actor_user_id,
                group_id=scope_value or None,
            )
        return EventSource(
            platform=platform or "runtime",
            message_type="private",
            user_id=actor_user_id,
            group_id=None,
        )


# endregion
