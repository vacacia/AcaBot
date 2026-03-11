"""runtime.app 实现新的最小应用组装入口.

RuntimeApp 的职责是把 gateway 事件接到新的 runtime 主线上, 不再让旧 Pipeline 直接暴露
"""

from __future__ import annotations

from dataclasses import replace
import logging
import time
import uuid
from typing import Callable

from acabot.types import StandardEvent

from .approval_resumer import ApprovalResumer, ApprovalResumeResult, NoopApprovalResumer
from .gateway_protocol import GatewayProtocol
from .models import (
    ApprovalDecisionResult,
    AgentProfile,
    ChannelEventRecord,
    PendingApprovalRecord,
    RecoveryReport,
    RouteDecision,
    RunContext,
    RunRecord,
    RunStep,
)
from .pipeline import ThreadPipeline
from .reference_backend import ReferenceBackend
from .router import RuntimeRouter
from .runs import RunManager
from .stores import ChannelEventStore
from .threads import ThreadManager

logger = logging.getLogger("acabot.runtime.app")


class RuntimeApp:
    """新的最小 runtime 应用入口.

    负责接线, 不负责具体业务逻辑.
    它只把外部 event 变成 RunContext, 再交给 ThreadPipeline 执行.
    """

    def __init__(
        self,
        *,
        gateway: GatewayProtocol,
        router: RuntimeRouter,
        thread_manager: ThreadManager,
        run_manager: RunManager,
        channel_event_store: ChannelEventStore,
        pipeline: ThreadPipeline,
        profile_loader: Callable[[RouteDecision], AgentProfile],
        approval_resumer: ApprovalResumer | None = None,
        reference_backend: ReferenceBackend | None = None,
    ) -> None:
        """初始化 RuntimeApp.

        Args:
            gateway: 平台网关实现.
            router: event 到 runtime world 的路由器.
            thread_manager: thread 状态管理器.
            run_manager: run 生命周期管理器.
            channel_event_store: inbound event log 持久化组件.
            pipeline: 真正执行一次 run 的 ThreadPipeline.
            profile_loader: 根据 RouteDecision 加载 AgentProfile 的回调.
            approval_resumer: approval 通过后的续执行器.
            reference_backend: `reference / notebook` provider. 默认允许 lazy init.
        """

        self.gateway = gateway
        self.router = router
        self.thread_manager = thread_manager
        self.run_manager = run_manager
        self.channel_event_store = channel_event_store
        self.pipeline = pipeline
        self.profile_loader = profile_loader
        self.approval_resumer = approval_resumer or NoopApprovalResumer()
        self.reference_backend = reference_backend
        self.last_recovery_report = RecoveryReport()
        self._pending_approvals: dict[str, PendingApprovalRecord] = {}

    def install(self) -> None:
        """把 RuntimeApp 注册到 gateway 事件流上."""

        self.gateway.on_event(self.handle_event)

    async def start(self) -> None:
        """安装事件处理器并启动 gateway."""

        await self.recover_active_runs()
        self.install()
        await self.gateway.start()

    async def stop(self) -> None:
        """停止 gateway."""
        stop_error: Exception | None = None
        try:
            await self.gateway.stop()
        except Exception as exc:
            stop_error = exc
        if self.reference_backend is not None:
            try:
                await self.reference_backend.close()
            except Exception:
                logger.exception("Failed to close reference backend during shutdown")
                if stop_error is None:
                    raise
        if stop_error is not None:
            raise stop_error

    async def handle_event(self, event: StandardEvent) -> None:
        """处理一条来自 gateway 的标准事件.

        Args:
            event: 平台翻译后的标准事件.
        """
        run_id: str | None = None
        try:
            decision = await self.router.route(event)
            if decision.run_mode == "silent_drop":
                return
            thread = await self.thread_manager.get_or_create(
                thread_id=decision.thread_id,
                channel_scope=decision.channel_scope,
                last_event_at=event.timestamp,
            )
            run = await self.run_manager.open(event=event, decision=decision)
            run_id = run.run_id
            if decision.metadata.get("event_persist", True):
                await self.channel_event_store.save(
                    self._build_channel_event_record(
                        event=event,
                        decision=decision,
                        run_id=run.run_id,
                    )
                )
            profile = self._load_profile_for_event(decision)
            ctx = RunContext(
                run=run,
                event=event,
                decision=decision,
                thread=thread,
                profile=profile,
            )
            await self.pipeline.execute(ctx)
        except Exception as exc:
            logger.exception("Failed to handle event: event_id=%s", event.event_id)
            if run_id is not None:
                await self._mark_failed_safely(run_id, f"runtime app crashed: {exc}")

    # region inbound事件
    def _load_profile_for_event(self, decision: RouteDecision) -> AgentProfile:
        """按事件模式加载当前 run 使用的 profile.

        Args:
            decision: 当前事件对应的 RouteDecision.

        Returns:
            一份 AgentProfile.
        """

        if decision.run_mode == "record_only":
            return AgentProfile(
                agent_id=decision.agent_id,
                name=decision.agent_id,
                prompt_ref="prompt/record_only",
                default_model="record-only",
            )
        return self.profile_loader(decision)

    @staticmethod
    def _build_channel_event_record(
        *,
        event: StandardEvent,
        decision: RouteDecision,
        run_id: str,
    ) -> ChannelEventRecord:
        """把 StandardEvent 投影成可持久化的 ChannelEventRecord.

        Args:
            event: 当前标准化事件.
            decision: 当前事件对应的 RouteDecision.
            run_id: 关联的 run_id.

        Returns:
            一份 ChannelEventRecord.
        """

        return ChannelEventRecord(
            event_uid=event.event_id,
            thread_id=decision.thread_id,
            actor_id=decision.actor_id,
            channel_scope=decision.channel_scope,
            platform=event.platform,
            event_type=event.event_type,
            message_type=event.source.message_type,
            content_text=RuntimeApp._event_text_projection(event),
            payload_json={
                "source": {
                    "platform": event.source.platform,
                    "message_type": event.source.message_type,
                    "user_id": event.source.user_id,
                    "group_id": event.source.group_id,
                },
                "segments": [
                    {"type": segment.type, "data": dict(segment.data)}
                    for segment in event.segments
                ],
                "reply_to_message_id": event.reply_to_message_id,
                "mentioned_user_ids": list(event.mentioned_user_ids),
                "attachments": [
                    {
                        "type": attachment.type,
                        "source": attachment.source,
                        "name": attachment.name,
                        "mime_type": attachment.mime_type,
                        "metadata": dict(attachment.metadata),
                    }
                    for attachment in event.attachments
                ],
                "sender_nickname": event.sender_nickname,
                "sender_role": event.sender_role,
                "operator_id": event.operator_id,
                "target_message_id": event.target_message_id,
                "metadata": dict(event.metadata),
            },
            timestamp=event.timestamp,
            run_id=run_id,
            raw_message_id=event.raw_message_id,
            operator_id=event.operator_id,
            target_message_id=event.target_message_id,
            metadata={
                "run_mode": decision.run_mode,
                "agent_id": decision.agent_id,
                **dict(decision.metadata),
            },
            raw_event=dict(event.raw_event),
        )

    @staticmethod
    def _event_text_projection(event: StandardEvent) -> str:
        """把 StandardEvent 投影成便于检索的简短文本.

        Args:
            event: 当前标准化事件.

        Returns:
            一条简短的文本投影.
        """

        text = event.message_preview.strip()
        if text:
            return text
        if event.event_type == "poke":
            return "[poke]"
        if event.event_type == "recall":
            return "[recall]"
        return f"[{event.event_type}]"

    # region recovery
    async def recover_active_runs(self) -> RecoveryReport:
        """扫描并收尾重启前遗留的 active runs.

        当前策略:
        - `queued` 和 `running` 无法无缝继续, 统一收尾为 `interrupted`
        - `waiting_approval` 保留原状态, 并暴露为 pending approvals

        Returns:
            本次 recovery 的汇总结果.
        """

        report = RecoveryReport()
        self._pending_approvals = {}
        active_runs = await self.run_manager.list_active()

        for run in active_runs:
            if run.status == "waiting_approval":
                pending = PendingApprovalRecord(
                    run_id=run.run_id,
                    thread_id=run.thread_id,
                    actor_id=run.actor_id,
                    agent_id=run.agent_id,
                    reason=run.error or "waiting approval",
                    approval_context=dict(run.approval_context),
                )
                report.pending_approvals.append(pending)
                self._pending_approvals[run.run_id] = pending
                continue

            await self.run_manager.mark_interrupted(
                run.run_id,
                "process restarted before run finished",
            )
            report.interrupted_run_ids.append(run.run_id)

        self.last_recovery_report = report
        return report

    def list_pending_approvals(self) -> list[PendingApprovalRecord]:
        """返回当前进程已识别出的 pending approvals.

        Returns:
            当前缓存的 pending approval 列表.
        """

        return list(self._pending_approvals.values())

    async def approve_pending_approval(
        self,
        run_id: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> ApprovalDecisionResult:
        """批准一条 waiting approval 并继续执行.

        Args:
            run_id: 目标 waiting approval run_id.
            metadata: 本次审批动作的附加元数据.

        Returns:
            一份 ApprovalDecisionResult.
        """

        run = await self.run_manager.get(run_id)
        if run is None:
            return ApprovalDecisionResult(
                run_id=run_id,
                decision="approved",
                ok=False,
                message="run not found",
            )
        if run.status != "waiting_approval":
            return ApprovalDecisionResult(
                run_id=run_id,
                decision="approved",
                ok=False,
                run_status=run.status,
                message="run is not waiting_approval",
            )

        decision_metadata = dict(metadata or {})
        approval_context = dict(run.approval_context)
        run_snapshot = self._snapshot_run(run)
        await self._append_run_step_safely(
            run_id=run_id,
            step_type="approval_decision",
            status="approved",
            payload={"metadata": decision_metadata},
        )
        self._pending_approvals.pop(run_id, None)
        await self.run_manager.mark_running(run_id)

        try:
            result = await self.approval_resumer.resume(
                run=run_snapshot,
                approval_context=approval_context,
                metadata=decision_metadata,
            )
        except Exception as exc:
            logger.exception("Approval resume failed: run_id=%s", run_id)
            await self.run_manager.mark_failed(run_id, f"approval resume crashed: {exc}")
            return ApprovalDecisionResult(
                run_id=run_id,
                decision="approved",
                ok=False,
                run_status="failed",
                message=f"approval resume crashed: {exc}",
            )

        return await self._apply_approval_resume_result(
            run_id=run_id,
            result=result,
            decision_metadata=decision_metadata,
        )

    async def reject_pending_approval(
        self,
        run_id: str,
        *,
        reason: str = "approval rejected",
        metadata: dict[str, object] | None = None,
    ) -> ApprovalDecisionResult:
        """拒绝一条 waiting approval.

        Args:
            run_id: 目标 waiting approval run_id.
            reason: 拒绝原因.
            metadata: 本次审批动作的附加元数据.

        Returns:
            一份 ApprovalDecisionResult.
        """

        run = await self.run_manager.get(run_id)
        if run is None:
            return ApprovalDecisionResult(
                run_id=run_id,
                decision="rejected",
                ok=False,
                message="run not found",
            )
        if run.status != "waiting_approval":
            return ApprovalDecisionResult(
                run_id=run_id,
                decision="rejected",
                ok=False,
                run_status=run.status,
                message="run is not waiting_approval",
            )

        self._pending_approvals.pop(run_id, None)
        await self._append_run_step_safely(
            run_id=run_id,
            step_type="approval_decision",
            status="rejected",
            payload={
                "reason": reason,
                "metadata": dict(metadata or {}),
            },
        )
        await self.run_manager.mark_cancelled(run_id, reason)
        return ApprovalDecisionResult(
            run_id=run_id,
            decision="rejected",
            ok=True,
            run_status="cancelled",
            message=reason,
        )

    # endregion

    async def _mark_failed_safely(self, run_id: str, error: str) -> None:
        """尽力把 run 收尾为 failed.

        Args:
            run_id: 需要收尾的 run_id.
            error: 要写入 run 的错误摘要.
        """

        try:
            await self.run_manager.mark_failed(run_id, error)
        except Exception:
            logger.exception("Failed to mark run as failed: run_id=%s", run_id)

    # region approval internals
    async def _apply_approval_resume_result(
        self,
        *,
        run_id: str,
        result: ApprovalResumeResult,
        decision_metadata: dict[str, object],
    ) -> ApprovalDecisionResult:
        """把 ApprovalResumeResult 落到正式 run 状态机上.

        Args:
            run_id: 目标 run_id.
            result: approval resume 返回结果.
            decision_metadata: 本次 approval decision 的附加元数据.

        Returns:
            一份 ApprovalDecisionResult.
        """

        await self._append_run_step_safely(
            run_id=run_id,
            step_type="approval_resume",
            status=result.status,
            payload={
                "message": result.message,
                "metadata": decision_metadata,
                "approval_context": dict(result.approval_context),
            },
        )

        if result.status == "completed":
            await self.run_manager.mark_completed(run_id)
            return ApprovalDecisionResult(
                run_id=run_id,
                decision="approved",
                ok=True,
                run_status="completed",
            )

        if result.status == "completed_with_errors":
            message = result.message or "approval resume completed with errors"
            await self.run_manager.mark_completed_with_errors(
                run_id,
                error_summary=message,
            )
            return ApprovalDecisionResult(
                run_id=run_id,
                decision="approved",
                ok=True,
                run_status="completed_with_errors",
                message=message,
            )

        if result.status == "waiting_approval":
            reason = result.message or "waiting approval"
            await self.run_manager.mark_waiting_approval(
                run_id,
                reason=reason,
                approval_context=dict(result.approval_context),
            )
            run = await self.run_manager.get(run_id)
            pending = self._pending_from_run(run)
            if pending is not None:
                self._pending_approvals[run_id] = pending
            return ApprovalDecisionResult(
                run_id=run_id,
                decision="approved",
                ok=True,
                run_status="waiting_approval",
                message=reason,
                pending_approval=pending,
            )

        message = result.message or "approval resume failed"
        await self.run_manager.mark_failed(run_id, message)
        return ApprovalDecisionResult(
            run_id=run_id,
            decision="approved",
            ok=False,
            run_status="failed",
            message=message,
        )

    async def _append_run_step_safely(
        self,
        *,
        run_id: str,
        step_type: str,
        status: str,
        payload: dict[str, object],
    ) -> None:
        """尽力记录一条 run step.

        Args:
            run_id: 目标 run_id.
            step_type: step 类型.
            status: step 状态.
            payload: step 负载.
        """

        try:
            await self.run_manager.append_step(
                RunStep(
                    step_id=f"step:{uuid.uuid4().hex}",
                    run_id=run_id,
                    step_type=step_type,
                    status=status,
                    payload=payload,
                    created_at=int(time.time()),
                )
            )
        except Exception:
            logger.exception(
                "Failed to append run step: run_id=%s step_type=%s",
                run_id,
                step_type,
            )

    @staticmethod
    def _pending_from_run(run: RunRecord | None) -> PendingApprovalRecord | None:
        """从 waiting approval 的 RunRecord 派生 PendingApprovalRecord.

        Args:
            run: 当前 run 记录.

        Returns:
            对应的 PendingApprovalRecord. 不可派生时返回 None.
        """

        if run is None or run.status != "waiting_approval":
            return None
        return PendingApprovalRecord(
            run_id=run.run_id,
            thread_id=run.thread_id,
            actor_id=run.actor_id,
            agent_id=run.agent_id,
            reason=run.error or "waiting approval",
            approval_context=dict(run.approval_context),
        )

    @staticmethod
    def _snapshot_run(run: RunRecord) -> RunRecord:
        """构造一份用于 approval resume 的 RunRecord snapshot.

        防止 ApprovalResumer 的实现意外修改原始 RunRecord,
        防止污染 RuntimeApp 内部的 run 对象.
        
        Args:
            run: 当前运行中的 RunRecord.

        Returns:
            一份浅拷贝后的 RunRecord.
        """

        return replace(
            run,
            approval_context=dict(run.approval_context),
            metadata=dict(run.metadata),
        )

    # endregion
