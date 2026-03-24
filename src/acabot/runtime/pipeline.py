"""runtime.pipeline 实现 ThreadPipeline.

这一版已经接入:
- retrieval planning
- context compaction
- prompt slot assembly
- user event -> agent runtime -> outbox -> run 收尾
"""

from __future__ import annotations

import logging

from acabot.types import Action, ActionType

from .agent_runtime import AgentRuntime
from .computer import ComputerRuntime
from .memory.context_compactor import ContextCompactor
from .inbound.message_preparation import MessagePreparationService
from .memory.file_backed import StickyNotesSource
from .contracts import (
    AgentRuntimeResult,
    DeliveryResult,
    DispatchReport,
    OutboxItem,
    PlannedAction,
    RetrievalPlan,
    RunContext,
)
from .memory.memory_broker import MemoryBroker, MemoryBrokerResult
from .outbox import Outbox
from .plugin_manager import RuntimeHookPoint, RuntimePluginManager
from .memory.retrieval_planner import RetrievalPlanner
from .soul import SoulSource
from .storage.runs import RunManager
from .tool_broker import ToolBroker
from .storage.threads import ThreadManager

logger = logging.getLogger("acabot.runtime.pipeline")


class ThreadPipeline:
    """一次 run 的最小执行器.

    当前版本已经接入:
    - MemoryBroker retrieval skeleton
    - ToolBroker approval audit 回写
    - RuntimePluginManager hooks
    """

    def __init__(
        self,
        *,
        agent_runtime: AgentRuntime,
        outbox: Outbox,
        run_manager: RunManager,
        thread_manager: ThreadManager,
        memory_broker: MemoryBroker | None = None,
        retrieval_planner: RetrievalPlanner | None = None,
        context_compactor: ContextCompactor | None = None,
        computer_runtime: ComputerRuntime | None = None,
        message_preparation_service: MessagePreparationService | None = None,
        tool_broker: ToolBroker | None = None,
        plugin_manager: RuntimePluginManager | None = None,
        soul_source: SoulSource | None = None,
        sticky_notes_source: StickyNotesSource | None = None,
    ) -> None:
        """初始化 ThreadPipeline.

        Args:
            agent_runtime: 负责生成本次 run 结果的 agent runtime.
            outbox: 统一出站组件.
            run_manager: run 生命周期管理器.
            thread_manager: thread 状态管理器.
            memory_broker: 可选的 MemoryBroker. 用于 retrieval.
            retrieval_planner: 可选的 RetrievalPlanner. 用于 planning 和 prompt assembly.
            context_compactor: 可选的 ContextCompactor. 用于 working memory compaction.
            computer_runtime: 可选的 ComputerRuntime. 用于 workspace 准备和附件 staging.
            message_preparation_service: 可选的 MessagePreparationService. 用于把消息补齐并生成 history/model 输入.
            tool_broker: 可选的 ToolBroker. 用于 approval prompt 的 audit 回写.
            plugin_manager: 可选的 RuntimePluginManager. 用于 runtime hooks.
            soul_source: 可选的 soul 文件真源.
            sticky_notes_source: 可选的 sticky note 文件真源.
        """

        self.agent_runtime = agent_runtime
        self.outbox = outbox
        self.run_manager = run_manager
        self.thread_manager = thread_manager
        self.memory_broker = memory_broker
        self.retrieval_planner = retrieval_planner
        self.context_compactor = context_compactor
        self.computer_runtime = computer_runtime
        self.message_preparation_service = message_preparation_service
        self.tool_broker = tool_broker
        self.plugin_manager = plugin_manager
        self.soul_source = soul_source
        self.sticky_notes_source = sticky_notes_source
    # region execute
    async def execute(self, ctx: RunContext, *, deliver_actions: bool = True) -> None:
        """执行一条最小 runtime 主线.

        Args:
            ctx: 当前 run 的完整执行上下文.
            deliver_actions: 是否把动作真正发到外部平台.
        """
        # 标记 run 状态为 running
        await self.run_manager.mark_running(ctx.run.run_id)
        logger.debug(
            "Pipeline started: run_id=%s thread=%s agent=%s run_mode=%s deliver_actions=%s",
            ctx.run.run_id,
            ctx.thread.thread_id,
            ctx.profile.agent_id,
            ctx.decision.run_mode,
            deliver_actions,
        )
        try:
            await self._run_plugin_hooks(RuntimeHookPoint.ON_EVENT, ctx)
            if self.computer_runtime is not None:
                await self.computer_runtime.prepare_run_context(ctx)
            if self.message_preparation_service is not None:
                await self.message_preparation_service.prepare(ctx)
            # -----------------------------------------------------
            # 准备 compaction
            # -----------------------------------------------------
            compaction_result = None
            compaction_snapshot = None
            # 锁内: 写入用户消息 + 创建 thread 快照
            async with ctx.thread.lock:
                self._append_incoming_message(ctx)
            # -----------------------------------------------------
            # record_only 模式
            # -----------------------------------------------------
            if ctx.decision.run_mode == "record_only":
                logger.info(
                    "Pipeline record_only: run_id=%s thread=%s incoming_messages=%s",
                    ctx.run.run_id,
                    ctx.thread.thread_id,
                    len(ctx.thread.working_messages),
                )
                await self.thread_manager.save(ctx.thread)
                await self.run_manager.mark_completed(ctx.run.run_id)
                return  # 不进入 compaction / retrieval / prompt assembly / LLM
            async with ctx.thread.lock:
                if self.context_compactor is not None:
                    compaction_snapshot = self.context_compactor.snapshot_thread(ctx.thread)
            # -----------------------------------------------------
            # 锁外执行 Context Compaction
            # -----------------------------------------------------
            """NOTE: 
            压缩期间 thread 被修改, 会拒绝回写; 但本次 run 依然使用压缩的结果
                - user:A -> run-1 -> user:A append 到共享 thread -> run-1 snapshot 后开始 compaction
                - user:B -> run-2 -> user:B append 到共享 thread -> run-2 snapshot 后开始 compaction
                - run-1 用自己的 effective_* 结果调用 LLM, append assistant:reply_to_A
                - run-2 用自己的 effective_* 结果调用 LLM, append assistant:reply_to_B
            所以: 
                - 同一个 thread 的 run 之间是并行的
                - 单个 run 的 append_incoming_message, compaction 是阻塞的
                - 虽然 compaction 可能有重复的工作量, 但好处是能并行回复
            TODO: single-flight thread compaction with append-only rebase
            """
            if self.context_compactor is not None and compaction_snapshot is not None:
                compaction_result = await self.context_compactor.compact(
                    ctx,
                    snapshot=compaction_snapshot,
                )
                # 压缩结果存入 ctx.metadata
                ctx.metadata["effective_working_summary"] = compaction_result.summary_text
                ctx.metadata["effective_compacted_messages"] = list(compaction_result.compressed_messages)
                ctx.metadata["effective_dropped_messages"] = list(compaction_result.dropped_messages)
                # 重新获取锁, 将 compaction 结果应用到 thread
                async with ctx.thread.lock:
                    applied = self.context_compactor.apply_to_thread(
                        ctx.thread,
                        snapshot=compaction_snapshot,
                        result=compaction_result,
                        timestamp=ctx.event.timestamp,
                    )
                ctx.metadata["compaction_applied_to_thread"] = applied
                logger.debug(
                    "Compaction finished: run_id=%s applied=%s kept=%s dropped=%s summary_chars=%s",
                    ctx.run.run_id,
                    applied,
                    len(compaction_result.compressed_messages),
                    len(compaction_result.dropped_messages),
                    len(compaction_result.summary_text or ""),
                )
            else:
                ctx.metadata["effective_working_summary"] = ctx.thread.working_summary
                ctx.metadata["effective_compacted_messages"] = list(ctx.thread.working_messages)
                ctx.metadata["effective_dropped_messages"] = []
            # -----------------------------------------------------
            # 准备 Retrieval Plan
            # -----------------------------------------------------
            async with ctx.thread.lock:
                if self.retrieval_planner is not None:
                    # prepare 会读取 ctx.metadata["effective_*"] 字段
                    ctx.retrieval_plan = self.retrieval_planner.prepare(ctx)
                else:
                    ctx.retrieval_plan = self._build_fallback_retrieval_plan(ctx)
            # -----------------------------------------------------
            # 注入记忆, 调用 Agent
            # -----------------------------------------------------
            await self._inject_memories(ctx)
            logger.debug(
                "Memory injected: run_id=%s memory_blocks=%s message_count=%s",
                ctx.run.run_id,
                len(ctx.memory_blocks),
                len(ctx.messages),
            )
            pre_agent_result = await self._run_plugin_hooks(RuntimeHookPoint.PRE_AGENT, ctx)
            if pre_agent_result.action == "skip_agent":
                logger.debug("Agent execution skipped by plugin: run_id=%s", ctx.run.run_id)
                ctx.response = AgentRuntimeResult(
                    status="completed",
                    actions=list(ctx.actions),
                    metadata={"origin": "runtime_plugin_skip_agent"},
                )
            else:
                ctx.response = await self.agent_runtime.execute(ctx)
                ctx.actions = list(ctx.response.actions)
                logger.debug(
                    "Agent runtime returned: run_id=%s status=%s actions=%s pending_approval=%s",
                    ctx.run.run_id,
                    ctx.response.status,
                    len(ctx.actions),
                    bool(ctx.response.pending_approval),
                )
            await self._run_plugin_hooks(RuntimeHookPoint.POST_AGENT, ctx)

            # -----------------------------------------------------
            # 发送回复
            # -----------------------------------------------------
            if deliver_actions:
                await self._run_plugin_hooks(RuntimeHookPoint.BEFORE_SEND, ctx)
                if ctx.actions:
                    # 通过 Outbox 发送
                    ctx.delivery_report = await self.outbox.dispatch(ctx)
                else:
                    ctx.delivery_report = DispatchReport()
                await self._run_plugin_hooks(RuntimeHookPoint.ON_SENT, ctx)
            else:
                ctx.delivery_report = self._build_internal_delivery_report(ctx)
            logger.debug(
                "Delivery prepared: run_id=%s delivered=%s failed=%s",
                ctx.run.run_id,
                len((ctx.delivery_report or DispatchReport()).delivered_items),
                len((ctx.delivery_report or DispatchReport()).failed_action_ids),
            )
            # -----------------------------------------------------
            # 收尾
            # -----------------------------------------------------
            await self._update_thread_after_send(ctx)
            await self._finish_run(ctx)
        except Exception as exc:
            logger.exception("ThreadPipeline crashed: run_id=%s", ctx.run.run_id)
            await self._run_error_hooks(ctx)
            await self._save_thread_safely(ctx)
            await self._mark_failed_safely(
                ctx.run.run_id,
                f"pipeline crashed: {exc}",
            )

    def build_text_reply_action(self, ctx: RunContext, text: str) -> PlannedAction:
        """为当前上下文构造一个最小纯文本回复动作.

        Args:
            ctx: 当前 run 的执行上下文.
            text: 要回复给用户的文本.

        Returns:
            给 Outbox 的 PlannedAction.
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
            metadata={"origin": "assistant_text"},
        )

    def _append_incoming_message(self, ctx: RunContext) -> None:
        """把用户输入写入 thread working memory.

        Args:
            ctx: 当前 run 的执行上下文.
        """

        content = self._build_user_content(ctx)
        ctx.thread.working_messages.append({"role": "user", "content": content})
        ctx.thread.last_event_at = ctx.event.timestamp

    async def _inject_memories(self, ctx: RunContext) -> None:
        """通过 MemoryBroker 检索并注入长期记忆.

        Args:
            ctx: 当前 run 的执行上下文.
        """

        if self.memory_broker is None:
            ctx.memory_broker_result = MemoryBrokerResult()
            ctx.memory_blocks = []
        else:
            ctx.memory_broker_result = await self.memory_broker.retrieve(ctx)
            ctx.memory_blocks = list(ctx.memory_broker_result.blocks)
        logger.debug(
            "Collected memory blocks: run_id=%s retrieved=%s",
            ctx.run.run_id,
            len(ctx.memory_blocks),
        )

    async def _update_thread_after_send(self, ctx: RunContext) -> None:
        """根据实际送达结果更新 thread working memory.

        Args:
            ctx: 当前 run 的执行上下文.
        """

        if ctx.delivery_report is None:
            return

        async with ctx.thread.lock:
            for item in ctx.delivery_report.delivered_items:
                if item.plan.thread_content:
                    ctx.thread.working_messages.append(
                        {"role": "assistant", "content": item.plan.thread_content}
                    )
            await self.thread_manager.save(ctx.thread)

    async def _finish_run(self, ctx: RunContext) -> None:
        """根据 runtime 状态和 delivery 结果收尾 run.

        Args:
            ctx: 当前 run 的执行上下文.
        """

        response = ctx.response
        if response is None:
            await self.run_manager.mark_failed(ctx.run.run_id, "missing runtime response")
            return

        if response.status == "waiting_approval":
            pending = response.pending_approval
            if pending is None:
                await self.run_manager.mark_failed(
                    ctx.run.run_id,
                    "approval requested without pending_approval context",
                )
                return

            delivered_action_ids = {
                item.plan.action_id for item in (ctx.delivery_report or DispatchReport()).delivered_items
            }
            if not set(pending.required_action_ids).issubset(delivered_action_ids):
                if self.tool_broker is not None:
                    await self.tool_broker.fail_pending_approval(
                        pending,
                        error="approval prompt not delivered",
                    )
                await self.run_manager.mark_failed(ctx.run.run_id, "approval prompt not delivered")
                return

            if self.tool_broker is not None:
                await self.tool_broker.confirm_pending_approval(
                    pending,
                    delivery_report=ctx.delivery_report or DispatchReport(),
                )
            logger.debug(
                "Run waiting approval: run_id=%s tool=%s approval_id=%s prompt_actions=%s",
                ctx.run.run_id,
                pending.tool_name,
                pending.approval_id,
                len(pending.required_action_ids),
            )
            await self.run_manager.mark_waiting_approval(
                ctx.run.run_id,
                reason=pending.reason,
                approval_context={
                    "approval_id": pending.approval_id,
                    "tool_call_id": pending.tool_call_id,
                    "tool_name": pending.tool_name,
                    "tool_arguments": pending.tool_arguments,
                    "required_action_ids": pending.required_action_ids,
                    "metadata": pending.metadata,
                },
            )
            return

        if response.status == "failed":
            logger.warning(
                "Run failed from agent runtime: run_id=%s error=%s",
                ctx.run.run_id,
                response.error or "agent runtime failed",
            )
            await self.run_manager.mark_failed(
                ctx.run.run_id,
                response.error or "agent runtime failed",
            )
            return

        if (ctx.delivery_report or DispatchReport()).has_failures:
            logger.warning("Run completed with delivery errors: run_id=%s", ctx.run.run_id)
            await self.run_manager.mark_completed_with_errors(
                ctx.run.run_id,
                error_summary="partial delivery failure",
            )
            return

        logger.info("Run completed cleanly: run_id=%s", ctx.run.run_id)
        await self.run_manager.mark_completed(ctx.run.run_id)

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

    async def _run_plugin_hooks(self, point: RuntimeHookPoint, ctx: RunContext):
        """执行指定切入点的 runtime hooks.

        Args:
            point: 当前 hook 切入点.
            ctx: 当前 run 的执行上下文.

        Returns:
            RuntimePluginManager 聚合后的 RuntimeHookResult.
        """

        if self.plugin_manager is None:
            from .plugin_manager import RuntimeHookResult

            return RuntimeHookResult()
        return await self.plugin_manager.run_hooks(point, ctx)

    async def _run_error_hooks(self, ctx: RunContext) -> None:
        """在 pipeline 异常时尽力触发 error hooks.

        Args:
            ctx: 当前 run 的执行上下文.
        """

        if self.plugin_manager is None:
            return
        try:
            await self.plugin_manager.run_hooks(RuntimeHookPoint.ON_ERROR, ctx)
        except Exception:
            logger.exception("Failed to run runtime error hooks: run_id=%s", ctx.run.run_id)

    async def _save_thread_safely(self, ctx: RunContext) -> None:
        """尽力保存当前 thread 状态.

        Args:
            ctx: 当前 run 的执行上下文.
        """

        try:
            await self.thread_manager.save(ctx.thread)
        except Exception:
            logger.exception("Failed to save thread after crash: thread_id=%s", ctx.thread.thread_id)

    @staticmethod
    def _build_user_content(ctx: RunContext) -> str:
        """构造写入 working memory 的用户内容.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            一条带 actor 标识的用户文本.
        """

        if ctx.message_projection is not None and ctx.message_projection.history_text:
            return str(ctx.message_projection.history_text)
        return str(ctx.memory_user_content or ctx.event.working_memory_text or "")

    @staticmethod
    def _build_fallback_retrieval_plan(ctx: RunContext) -> RetrievalPlan:
        """在没有 RetrievalPlanner 时, 仍然为后续 assembler 准备最小 plan."""

        summary_text = str(
            ctx.metadata.get("effective_working_summary", ctx.thread.working_summary) or ""
        ).strip()
        return RetrievalPlan(
            requested_tags=list(
                ctx.context_decision.retrieval_tags if ctx.context_decision is not None else []
            ),
            sticky_note_scopes=list(
                ctx.context_decision.sticky_note_scopes if ctx.context_decision is not None else []
            ),
            retained_history=list(
                ctx.metadata.get("effective_compacted_messages", ctx.thread.working_messages)
            ),
            dropped_messages=list(ctx.metadata.get("effective_dropped_messages", [])),
            working_summary=summary_text,
            metadata={
                "summary_present": bool(summary_text),
                "token_stats": dict(ctx.metadata.get("token_stats", {}) or {}),
                "context_labels": list(
                    ctx.context_decision.context_labels if ctx.context_decision is not None else []
                ),
            },
        )

    # region 内部发送
    @staticmethod
    def _build_internal_delivery_report(ctx: RunContext) -> DispatchReport:
        """为隔离执行模式构造一份内部送达报告.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            一份把当前动作视为内部已提交的 DispatchReport.
        """

        delivered_items = [
            OutboxItem(
                thread_id=ctx.thread.thread_id,
                run_id=ctx.run.run_id,
                agent_id=ctx.profile.agent_id,
                plan=plan,
                metadata={"delivery_mode": "internal"},
            )
            for plan in ctx.actions
        ]
        return DispatchReport(
            results=[
                DeliveryResult(
                    action_id=item.plan.action_id,
                    ok=True,
                    raw={"internal": True},
                )
                for item in delivered_items
            ],
            delivered_items=delivered_items,
        )
