"""runtime.app 实现新的最小应用组装入口.

RuntimeApp 的职责是把 gateway 事件接到正式 runtime 主线上.
"""

from __future__ import annotations

from dataclasses import replace
import logging
import time
import uuid
from typing import Callable

from acabot.types import Action, ActionType, StandardEvent

from .approval_resumer import ApprovalResumer, ApprovalResumeResult, NoopApprovalResumer
from .backend.bridge import BackendBridge
from .backend.contracts import BackendRequest, BackendSourceRef
from .backend.mode_registry import BackendModeRegistry
from .computer import ComputerRuntime
from .gateway_protocol import GatewayProtocol
from .memory.long_term_ingestor import LongTermMemoryIngestor
from .model.model_resolution import resolve_model_requests_for_agent
from .model.model_registry import FileSystemModelRegistryManager, PersistedModelSnapshot, RuntimeModelRequest
from .contracts import (
    ApprovalDecisionResult,
    ChannelEventRecord,
    PendingApprovalRecord,
    RecoveryReport,
    ResolvedAgent,
    RouteDecision,
    RunContext,
    RunRecord,
    RunStep,
    ThreadState,
)
from .plugin_manager import RuntimePluginManager
from .pipeline import ThreadPipeline
from .router import RuntimeRouter
from .storage.runs import RunManager
from .storage.stores import ChannelEventStore
from .storage.threads import ThreadManager

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
        agent_loader: Callable[[RouteDecision], ResolvedAgent] | None = None,
        approval_resumer: ApprovalResumer | None = None,
        plugin_manager: RuntimePluginManager | None = None,
        model_registry_manager: FileSystemModelRegistryManager | None = None,
        computer_runtime: ComputerRuntime | None = None,
        long_term_memory_ingestor: LongTermMemoryIngestor | None = None,
        backend_bridge: BackendBridge | None = None,
        backend_mode_registry: BackendModeRegistry | None = None,
        backend_admin_actor_ids: set[str] | None = None,
    ) -> None:
        """初始化 RuntimeApp.

        Args:
            gateway: 平台网关实现.
            router: event 到 runtime world 的路由器.
            thread_manager: thread 状态管理器.
            run_manager: run 生命周期管理器.
            channel_event_store: inbound event log 持久化组件.
            pipeline: 真正执行一次 run 的 ThreadPipeline.
            agent_loader: 根据 RouteDecision 加载当前 run agent 快照的回调.
            approval_resumer: approval 通过后的续执行器.
            plugin_manager: runtime world 的插件管理器.
            model_registry_manager: 运行时模型注册表管理器.
            computer_runtime: 运行时 computer 基础设施入口.
            long_term_memory_ingestor: 长期记忆写入线入口.
            backend_bridge: 可选的后台桥接入口.
            backend_mode_registry: 可选的管理员后台模式注册表.
            backend_admin_actor_ids: 可直接进入后台入口的管理员 actor 集合.
        """

        self.gateway = gateway
        self.router = router
        self.thread_manager = thread_manager
        self.run_manager = run_manager
        self.channel_event_store = channel_event_store
        self.pipeline = pipeline
        self.agent_loader = agent_loader
        self.approval_resumer = approval_resumer or NoopApprovalResumer()
        self.plugin_manager = plugin_manager
        self.model_registry_manager = model_registry_manager
        self.computer_runtime = computer_runtime
        self.long_term_memory_ingestor = long_term_memory_ingestor
        self.backend_bridge = backend_bridge
        self.backend_mode_registry = backend_mode_registry
        self.backend_admin_actor_ids = set(backend_admin_actor_ids or set())
        self.last_recovery_report = RecoveryReport()
        self._pending_approvals: dict[str, PendingApprovalRecord] = {}

    def install(self) -> None:
        """把 RuntimeApp 注册到 gateway 事件流上."""

        self.gateway.on_event(self.handle_event)

    async def start(self) -> None:
        """安装事件处理器并启动 gateway."""

        await self.recover_active_runs()
        await self._ensure_plugins_started()
        try:
            if self.long_term_memory_ingestor is not None:
                await self.long_term_memory_ingestor.start()
            self.install()
            await self.gateway.start()
        except Exception:
            if self.long_term_memory_ingestor is not None:
                try:
                    await self.long_term_memory_ingestor.stop()
                except Exception:
                    logger.exception("Failed to stop long-term memory ingestor after gateway start failure")
            if self.plugin_manager is not None:
                try:
                    await self.plugin_manager.teardown_all()
                except Exception:
                    logger.exception("Failed to teardown runtime plugins after gateway start failure")
            raise

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
            except Exception as exc:
                logger.exception("Failed to teardown runtime plugins during shutdown")
                if stop_error is None:
                    stop_error = exc
        if self.long_term_memory_ingestor is not None:
            try:
                await self.long_term_memory_ingestor.stop()
            except Exception as exc:
                logger.exception("Failed to stop long-term memory ingestor during shutdown")
                if stop_error is None:
                    stop_error = exc
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
            if await self._handle_backend_entrypoint(event):
                return
            await self._ensure_plugins_started()
            decision = await self.router.route(event)
            logger.debug(
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
            try:
                # 先契约, 后执行
                agent = self._load_agent_for_event(decision)
                model_request, model_snapshot, summary_model_request = self._resolve_model_requests(
                    decision=decision,
                    agent=agent,
                )
                logger.debug(
                    "Agent/model resolved: event_id=%s agent=%s run_model=%s summary_target_model=%s",
                    event.event_id,
                    agent.agent_id,
                    getattr(model_request, "model", "") or "-",
                    getattr(summary_model_request, "model", "") or "-",
                )
            except Exception as exc:
                # 路由或配置加载失败, 无法继续正常 run 了. 记录一个 run 来关联这个事件, 并收尾为 failed.
                run = await self.run_manager.open(event=event, decision=decision)
                run_id = run.run_id
                if self._should_persist_event(decision):
                    await self.channel_event_store.save(
                        self._build_channel_event_record(
                            event=event,
                            decision=decision,
                            run_id=run.run_id,
                        )
                    )
                    self._mark_long_term_memory_dirty(decision.thread_id)
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
            if self._should_persist_event(decision):
                await self.channel_event_store.save(
                    self._build_channel_event_record(
                        event=event,
                        decision=decision,
                        run_id=run.run_id,
                    )
                )
                logger.debug("Channel event persisted: event_id=%s run_id=%s", event.event_id, run.run_id)
                self._mark_long_term_memory_dirty(decision.thread_id)
            
            ctx = RunContext(
                run=run,
                event=event,
                decision=decision,
                thread=thread,
                agent=agent,
                model_request=model_request,
                summary_model_request=summary_model_request,
                event_facts=decision.event_facts,
                surface_resolution=decision.surface_resolution,
                routing_decision=decision.routing_decision,
                admission_decision=decision.admission_decision,
                context_decision=decision.context_decision,
                persistence_decision=decision.persistence_decision,
                extraction_decision=decision.extraction_decision,
                computer_policy_decision=decision.computer_policy_decision,
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

    async def _handle_backend_entrypoint(self, event: StandardEvent) -> bool:
        """在进入正常前台主线前处理后台硬入口.

        Returns:
            True 表示当前事件已由后台入口处理, 不再进入 router/pipeline.
        """

        if self.backend_bridge is None or self.backend_mode_registry is None:
            return False
        session_service = getattr(self.backend_bridge, "session", None)
        if session_service is None:
            return False
        is_configured = getattr(session_service, "is_configured", None)
        if not callable(is_configured) or not is_configured():
            return False
        if event.event_type != "message":
            return False

        text = event.text.strip()
        thread_id = self.router.build_thread_id(event)
        actor_id = self.router.build_actor_id(event)
        if actor_id not in self.backend_admin_actor_ids:
            return False

        if event.is_private and text == "/maintain":
            logger.info("Backend mode entered: actor=%s thread=%s", actor_id, thread_id)
            self.backend_mode_registry.enter_backend_mode(
                thread_id=thread_id,
                actor_id=actor_id,
                entered_at=event.timestamp,
            )
            return True

        if event.is_private and text in {"/maintain off", "/maintain exit"}:
            logger.info("Backend mode exited: actor=%s thread=%s", actor_id, thread_id)
            self.backend_mode_registry.exit_backend_mode(thread_id)
            return True

        if event.is_private and self.backend_mode_registry.is_backend_mode(thread_id):
            logger.debug("Backend direct message: actor=%s thread=%s summary=%s", actor_id, thread_id, text)
            result = await self.backend_bridge.handle_admin_direct(
                self._build_backend_request(
                    event=event,
                    thread_id=thread_id,
                    summary=text,
                )
            )
            await self._send_backend_admin_reply(event=event, result=result)
            return True

        if text.startswith("!"):
            summary = text[1:].strip()
            if summary:
                logger.debug("Backend bang command: actor=%s thread=%s summary=%s", actor_id, thread_id, summary)
                result = await self.backend_bridge.handle_admin_direct(
                    self._build_backend_request(
                        event=event,
                        thread_id=thread_id,
                        summary=summary,
                    )
                )
                await self._send_backend_admin_reply(event=event, result=result)
                return True

        return False

    async def _send_backend_admin_reply(self, *, event: StandardEvent, result: object) -> None:
        """把管理员 backend 直连结果直接回发给当前会话.

        这里故意不走 Outbox:
        - 管理员 backend 直连不是正常前台 run 的产物
        - 不应伪装成带 run 语义的 assistant message 持久化记录
        - 当前只需要一个最小可用的直出回路
        """

        text = self._extract_backend_reply_text(result)
        logger.debug(
            "Backend direct reply: event_id=%s channel=%s preview=%s",
            event.event_id,
            event.session_key,
            text[:120],
        )
        await self.gateway.send(
            Action(
                action_type=ActionType.SEND_TEXT,
                target=event.source,
                payload={"text": text},
                reply_to=event.raw_message_id or None,
            )
        )

    @staticmethod
    def _extract_backend_reply_text(result: object) -> str:
        """从 backend 返回值中提取最适合回发给管理员的文本."""

        if isinstance(result, dict):
            text = str(result.get("text", "")).strip()
            if text:
                return text
            response = result.get("response")
            if isinstance(response, dict):
                nested_text = str(response.get("text", "")).strip()
                if nested_text:
                    return nested_text
        text = str(result).strip()
        if text:
            return text
        return "（backend completed with no text output）"

    def _build_backend_request(
        self,
        *,
        event: StandardEvent,
        thread_id: str,
        summary: str,
    ) -> BackendRequest:
        """把管理员后台入口事件投影成最小 BackendRequest."""

        return BackendRequest(
            request_id=f"backend:{event.event_id}",
            source_kind="admin_direct",
            request_kind="change",
            source_ref=BackendSourceRef(
                thread_id=thread_id,
                channel_scope=self.router.build_channel_scope(event),
                event_id=event.event_id,
            ),
            summary=summary,
            created_at=event.timestamp,
        )

    @staticmethod
    def _preview_event(event: StandardEvent, max_len: int = 120) -> str:
        text = event.message_preview or event.notice_preview or f"[{event.event_type}]"
        if len(text) <= max_len:
            return text
        return f"{text[:max_len]}..."

    # region inbound事件
    def _load_agent_for_event(self, decision: RouteDecision) -> ResolvedAgent:
        """按事件模式加载当前 run 使用的 agent 快照.

        Args:
            decision: 当前事件对应的 RouteDecision.

        Returns:
            一份 ResolvedAgent.
        """

        if decision.run_mode == "record_only":
            return ResolvedAgent(
                agent_id=decision.agent_id,
                prompt_ref="prompt/record_only",
                name=decision.agent_id,
            )
        if self.agent_loader is not None:
            return self.agent_loader(decision)
        raise RuntimeError("agent loader is not configured")

    def _resolve_model_requests(
        self,
        *,
        decision: RouteDecision,
        agent: ResolvedAgent,
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

        return resolve_model_requests_for_agent(
            self.model_registry_manager,
            decision=decision,
            agent=agent,
        )

    def _mark_long_term_memory_dirty(self, thread_id: str) -> None:
        """在事件事实落盘成功后通知长期记忆写入线.

        Args:
            thread_id: 对应的 thread 标识.
        """

        try:
            if self.long_term_memory_ingestor is not None:
                self.long_term_memory_ingestor.mark_dirty(thread_id)
        except Exception:
            logger.exception(
                "Failed to mark long-term memory dirty after event persist: thread=%s",
                thread_id,
            )

    async def _ensure_plugins_started(self) -> None:
        """确保 runtime plugins 已经完成启动.

        合并 启动 plugins + 启动失败时清理现场, 不把 runtime 留在“plugin 半启动”的脏状态
        
        Returns:
            None.
        """

        if self.plugin_manager is None:
            return
        try:
            await self.plugin_manager.ensure_started()
        except Exception:
            try:
                await self.plugin_manager.teardown_all()
            except Exception:
                logger.exception("Failed to teardown runtime plugins after startup failure")
            raise

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
                "actor_display_name": event.sender_nickname or None,
                "bot_relation": event.bot_relation,
                "target_reasons": list(event.target_reasons),
                "mentions_self": event.mentions_self,
                "reply_targets_self": event.reply_targets_self,
                **dict(decision.metadata),
            },
            raw_event=dict(event.raw_event),
        )

    @staticmethod
    def _should_persist_event(decision: RouteDecision) -> bool:
        """判断当前事件是否需要写入 ChannelEventStore.

        Args:
            decision: 当前事件对应的 RouteDecision.

        Returns:
            bool: 需要持久化返回 `True`.
        """

        if decision.persistence_decision is not None:
            return decision.persistence_decision.persist_event
        return bool(decision.metadata.get("event_persist", True))

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
        logger.debug(
            "Recovery completed: interrupted=%s pending_approvals=%s",
            len(report.interrupted_run_ids),
            len(report.pending_approvals),
        )
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
