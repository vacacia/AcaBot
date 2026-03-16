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
from .computer import ComputerRuntime
from .gateway_protocol import GatewayProtocol
from .model_resolution import resolve_model_requests_for_profile
from .model_registry import FileSystemModelRegistryManager, PersistedModelSnapshot, RuntimeModelRequest
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
    ThreadState,
)
from .plugin_manager import RuntimePluginManager
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
        plugin_manager: RuntimePluginManager | None = None,
        model_registry_manager: FileSystemModelRegistryManager | None = None,
        computer_runtime: ComputerRuntime | None = None,
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
            plugin_manager: runtime world 的插件管理器.
            model_registry_manager: 运行时模型注册表管理器.
            computer_runtime: 运行时 computer 基础设施入口.
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
        self.plugin_manager = plugin_manager
        self.model_registry_manager = model_registry_manager
        self.computer_runtime = computer_runtime
        self.last_recovery_report = RecoveryReport()
        self._pending_approvals: dict[str, PendingApprovalRecord] = {}

    def install(self) -> None:
        """把 RuntimeApp 注册到 gateway 事件流上."""

        self.gateway.on_event(self.handle_event)

    async def start(self) -> None:
        """安装事件处理器并启动 gateway."""

        await self.recover_active_runs()
        if self.plugin_manager is not None:
            await self.plugin_manager.ensure_started()
        self.install()
        await self.gateway.start()

    async def stop(self) -> None:
        """停止 gateway."""
        stop_error: Exception | None = None
        try:
            await self.gateway.stop()
        except Exception as exc:
            stop_error = exc
        if self.plugin_manager is not None:
            try:
                await self.plugin_manager.teardown_all()
            except Exception:
                logger.exception("Failed to teardown runtime plugins during shutdown")
                if stop_error is None:
                    raise
        if self.reference_backend is not None:
            try:
                await self.reference_backend.close()
            except Exception:
                logger.exception("Failed to close reference backend during shutdown")
                if stop_error is None:
                    raise
        if stop_error is not None:
            raise stop_error

    async def reload_plugins(self, plugin_names: list[str] | None = None) -> tuple[list[str], list[str]]:
        """按当前配置重载 runtime plugins.

        Args:
            plugin_names: 可选的插件名列表. 缺省时重载全部插件.

        Returns:
            `(loaded_plugins, missing_plugins)` 元组.
        """

        if self.plugin_manager is None:
            return [], list(plugin_names or [])
        return await self.plugin_manager.reload_from_config(plugin_names)

    async def handle_event(self, event: StandardEvent) -> None:
        """处理一条来自 gateway 的标准事件.

        Args:
            event: 平台翻译后的标准事件.
        """
        run_id: str | None = None
        try:
            logger.info(
                "Inbound event: event_id=%s type=%s relation=%s channel=%s user=%s targets_self=%s preview=%s",
                event.event_id,
                event.event_type,
                event.bot_relation,
                event.session_key,
                event.source.user_id,
                event.targets_self,
                self._preview_event(event),
            )
            if self.plugin_manager is not None:
                await self.plugin_manager.ensure_started()
            decision = await self.router.route(event)
            logger.info(
                "Route resolved: event_id=%s agent=%s run_mode=%s thread=%s channel=%s",
                event.event_id,
                decision.agent_id,
                decision.run_mode,
                decision.thread_id,
                decision.channel_scope,
            )
            if decision.run_mode == "silent_drop":
                logger.info("Event dropped by route: event_id=%s", event.event_id)
                return
            # 根据路由决策, 创建或获取当前的对话 Thread
            thread = await self.thread_manager.get_or_create(
                thread_id=decision.thread_id,
                channel_scope=decision.channel_scope,
                last_event_at=event.timestamp,
            )
            # 是否应用 thread 级别的 **agent** override
            decision = self._apply_thread_agent_override(decision, thread)
            try:
                # 先契约, 后执行
                profile = self._load_profile_for_event(decision)
                model_request, model_snapshot, summary_model_request = self._resolve_model_requests(
                    decision=decision,
                    profile=profile,
                )
            except Exception as exc:
                # 路由或配置加载失败, 无法继续正常 run 了. 记录一个 run 来关联这个事件, 并收尾为 failed.
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
                await self._mark_failed_safely(run.run_id, f"runtime app crashed: {exc}")
                logger.exception("Failed before run setup completed: event_id=%s", event.event_id)
                return
            # 这次对话绑定了某个特定的模型凭证
            run = await self.run_manager.open(
                event=event,
                decision=decision,
                model_snapshot=model_snapshot,
            )
            run_id = run.run_id
            if decision.metadata.get("event_persist", True):
                await self.channel_event_store.save(
                    self._build_channel_event_record(
                        event=event,
                        decision=decision,
                        run_id=run.run_id,
                    )
                )
            
            ctx = RunContext(
                run=run,
                event=event,
                decision=decision,
                thread=thread,
                profile=profile,
                model_request=model_request, # 解析出的 model 被打包进 RunContext
                summary_model_request=summary_model_request,
            )
            await self.pipeline.execute(ctx)
            logger.info(
                "Run finished: run_id=%s status=%s agent=%s actions=%s error=%s",
                ctx.run.run_id,
                getattr(ctx.run, "status", ""),
                ctx.run.agent_id,
                len(ctx.actions),
                getattr(ctx.response, "error", "") or "-",
            )
        except Exception as exc:
            logger.exception("Failed to handle event: event_id=%s", event.event_id)
            if run_id is not None:
                await self._mark_failed_safely(run_id, f"runtime app crashed: {exc}")

    @staticmethod
    def _preview_event(event: StandardEvent, max_len: int = 120) -> str:
        text = event.message_preview or event.notice_preview or f"[{event.event_type}]"
        if len(text) <= max_len:
            return text
        return f"{text[:max_len]}..."

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
                default_model="",
            )
        return self.profile_loader(decision)

    def _resolve_model_requests(
        self,
        *,
        decision: RouteDecision,
        profile: AgentProfile,
    ) -> tuple[
        RuntimeModelRequest | None,
        PersistedModelSnapshot | None,
        RuntimeModelRequest | None,
    ]:
        """通过 Router 决定了Agent ID, 并加载该 Agent 的Profile

        从 ModelRegistryManager 解析出本次 **run** 和 summary 使用的模型请求配置.
        
        Returns:
            model_request、model_snapshot、summary_model_request 三元组.

        """

        return resolve_model_requests_for_profile(
            self.model_registry_manager,
            decision=decision,
            profile=profile,
        )

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
            content_text=event.content_preview or f"[{event.event_type}]",
            payload_json=event.to_payload_json(),
            timestamp=event.timestamp,
            run_id=run_id,
            raw_message_id=event.raw_message_id,
            operator_id=event.operator_id,
            target_message_id=event.target_message_id,
            metadata={
                "run_mode": decision.run_mode,
                "agent_id": decision.agent_id,
                "bot_relation": event.bot_relation,
                "target_reasons": list(event.target_reasons),
                "mentions_self": event.mentions_self,
                "reply_targets_self": event.reply_targets_self,
                **dict(decision.metadata),
            },
            raw_event=dict(event.raw_event),
        )

    # region override decision
    @staticmethod
    def _apply_thread_agent_override(
        decision: RouteDecision,
        thread: ThreadState,
    ) -> RouteDecision:
        """把 thread-local agent override 应用到当前 route decision.

        Args:
            decision: router 产出的原始 RouteDecision.
            thread: 当前 run 使用的 ThreadState.

        Returns:
            应用 override 后的 RouteDecision. 未声明 override 时返回原对象.
        """

        # 有没有手动指定的命令
        override_agent_id = str(thread.metadata.get("thread_agent_override", "") or "")
        if not override_agent_id:
            return decision
        # override + 留痕
        return replace(
            decision,
            agent_id=override_agent_id,
            metadata={
                **dict(decision.metadata),
                "binding_kind": "thread_override",
                "binding_rule_id": "",
                "binding_priority": 1_000_000,
                "binding_match_keys": ["thread_id"],
                "binding_override_agent_id": override_agent_id,
            },
        )

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
                "result_metadata": dict(result.metadata),
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
            run = await self.run_manager.get(run_id)
            await self.run_manager.append_step(
                RunStep(
                    step_id=f"step:{uuid.uuid4().hex}",
                    run_id=run_id,
                    thread_id=run.thread_id if run is not None else "",
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
