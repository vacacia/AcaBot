"""runtime.subagents.execution 提供本地 child run delegation 服务.

组件关系:

    SubagentDelegationBroker
            |
            v
    LocalSubagentExecutionService
            |
            v
      ThreadPipeline.execute(deliver_actions=False)

目标:
- 用 runtime 自己的 child run 执行 delegated skill
- 复用现有 profile, memory, tool 和 prompt 主线
- 不把 child run 的动作直接发到外部平台

如何把脏活外包给sub agent?
- 在系统内部伪造一条消息事件
- 并为这个子任务开辟一个新的对 Thread 和新的Run 
- 然后把这个子任务扔进 ThreadPipeline
为了让 subagent 也拥有完整的生命周期, 它可以使用 Mem, Tool, 甚至继续外包
subagent 的结果会被截获 返回给 main agent
"""

from __future__ import annotations

import logging
import time
import uuid

from acabot.types import EventSource, MsgSegment, StandardEvent

from ..model.model_resolution import resolve_model_requests_for_profile
from ..model.model_registry import FileSystemModelRegistryManager
from ..contracts import RouteDecision, RunContext, RunRecord, RunStep
from ..pipeline import ThreadPipeline
from ..storage.runs import RunManager
from ..storage.threads import ThreadManager
from .contracts import SubagentDelegationRequest, SubagentDelegationResult

logger = logging.getLogger("acabot.runtime.subagents.execution")


# region service
class LocalSubagentExecutionService:
    """本地 child run delegation 服务.

    Attributes:
        thread_manager (ThreadManager): thread 状态管理器.
        run_manager (RunManager): run 生命周期管理器.
        pipeline (ThreadPipeline): runtime 主线执行器.
        profile_loader: 根据 RouteDecision 加载 AgentProfile 的回调.
    """

    def __init__(
        self,
        *,
        thread_manager: ThreadManager,
        run_manager: RunManager,
        pipeline: ThreadPipeline,
        profile_loader,
        model_registry_manager: FileSystemModelRegistryManager | None = None,
    ) -> None:
        """初始化本地 child run delegation 服务.
        """

        self.thread_manager = thread_manager
        self.run_manager = run_manager
        self.pipeline = pipeline
        self.profile_loader = profile_loader
        self.model_registry_manager = model_registry_manager
    # region execute
    async def execute(self, request: SubagentDelegationRequest) -> SubagentDelegationResult:
        """执行一次本地 child run delegation.

        Args:
            request: 标准化后的 delegation request.

        Returns:
            一份标准化的 SubagentDelegationResult.
        """

        # 伪造一个内部事件
        event = self._build_event(request)
        # 
        decision = self._build_decision(request)
        thread = await self.thread_manager.get_or_create(
            thread_id=decision.thread_id,
            channel_scope=decision.channel_scope,
            thread_kind="subagent",
            last_event_at=event.timestamp,
        )
        thread.metadata.setdefault("parent_run_id", request.parent_run_id)
        thread.metadata.setdefault("delegated_skill", request.skill_name)
        thread.metadata.setdefault("delegate_agent_id", request.delegate_agent_id)

        profile = self.profile_loader(decision)
        model_request, model_snapshot, summary_model_request = resolve_model_requests_for_profile(
            self.model_registry_manager,
            decision=decision,
            profile=profile,
        )
        run = await self.run_manager.open(
            event=event,
            decision=decision,
            model_snapshot=model_snapshot,
        )
        ctx = RunContext(
            run=run,
            event=event,
            decision=decision,
            thread=thread,
            profile=profile,
            model_request=model_request,
            summary_model_request=summary_model_request,
            metadata={
                "delivery_mode": "internal",
                "subagent_child_run": True,
            },
        )

        await self._append_parent_step(
            request.parent_run_id,
            status="started",
            request=request,
            child_run_id=run.run_id,
        )
        # 复用主线执行, 不要把动作发到外部平台
        await self.pipeline.execute(ctx, deliver_actions=False)
        updated = await self.run_manager.get(run.run_id) or run
        result = self._build_result(request, ctx, updated)
        await self._append_parent_step(
            request.parent_run_id,
            status="completed" if result.ok else "failed",
            request=request,
            child_run_id=run.run_id,
            result=result,
        )
        return result

    # region _build_event
    def _build_event(self, request: SubagentDelegationRequest) -> StandardEvent:
        """构造 child run 使用的 synthetic event.

        Args:
            request: 标准化后的 delegation request.

        Returns:
            一份只在 runtime 内部流转的 StandardEvent.
        """

        source = self._build_event_source(request)
        task_text = str(request.payload.get("task", "") or "").strip()
        if not task_text:
            task_text = f"delegate skill {request.skill_name}"
        return StandardEvent(
            event_id=f"evt:subagent:{uuid.uuid4().hex}",
            event_type="message",
            platform=source.platform,
            timestamp=int(time.time()),
            source=source,
            segments=[MsgSegment(type="text", data={"text": task_text})],
            raw_message_id="",
            sender_nickname="subagent-parent",
            sender_role=None,
            metadata={
                "subagent_child_run": True,
                "delegated_skill": request.skill_name,
                "parent_run_id": request.parent_run_id,
                "payload": dict(request.payload),
            },
        )
    # region _build_decision
    def _build_decision(self, request: SubagentDelegationRequest) -> RouteDecision:
        """构造 child run 使用的 RouteDecision.

        Args:
            request: 标准化后的 delegation request.

        Returns:
            一份绑定到 delegate agent 的 RouteDecision.
        """

        return RouteDecision(
            thread_id=f"subagent:{request.parent_run_id}:{request.delegate_agent_id}:{uuid.uuid4().hex[:8]}",
            actor_id=request.actor_id,
            agent_id=request.delegate_agent_id,
            channel_scope=request.channel_scope,
            metadata={
                "run_kind": "subagent",
                "binding_kind": "subagent_child",
                "subagent_child_run": True,
                "parent_run_id": request.parent_run_id,
                "parent_thread_id": request.parent_thread_id,
                "parent_agent_id": request.parent_agent_id,
                "delegated_skill": request.skill_name,
                "delegate_agent_id": request.delegate_agent_id,
            },
        )

    # region _build_event_source
    @staticmethod
    def _build_event_source(request: SubagentDelegationRequest) -> EventSource:
        """从 parent channel_scope 派生 child run 的 EventSource.

        Args:
            request: 标准化后的 delegation request.

        Returns:
            一份 EventSource.
        """

        platform, scope_kind, scope_value = (request.channel_scope.split(":", 2) + ["", "", ""])[:3]
        actor_user_id = request.actor_id.split(":")[-1]
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
    # region _build_result
    @staticmethod
    def _build_result(
        request: SubagentDelegationRequest,
        ctx: RunContext,
        run: RunRecord,
    ) -> SubagentDelegationResult:
        """把 child run 执行结果收口成 delegation result.

        Args:
            request: delegation request.
            ctx: child run 的执行上下文.
            run: child run 的最终 RunRecord.

        Returns:
            一份标准化的 SubagentDelegationResult.
        """

        ok = run.status in {"completed", "completed_with_errors"}
        response = ctx.response
        summary = ""
        artifacts: list[dict[str, object]] = []
        if response is not None:
            summary = str(getattr(response, "text", "") or "")
            artifacts = list(getattr(response, "artifacts", []) or [])
        if not summary:
            assistant_messages = [
                message["content"]
                for message in ctx.thread.working_messages
                if message.get("role") == "assistant"
            ]
            if assistant_messages:
                summary = str(assistant_messages[-1])
        if not summary:
            summary = run.error or ""

        return SubagentDelegationResult(
            skill_name=request.skill_name,
            ok=ok,
            delegated_run_id=run.run_id,
            summary=summary,
            artifacts=artifacts,
            error=run.error or "",
            metadata={
                "parent_run_id": request.parent_run_id,
                "parent_thread_id": request.parent_thread_id,
                "delegate_agent_id": request.delegate_agent_id,
                "child_thread_id": run.thread_id,
                "child_run_status": run.status,
            },
        )
    # region _append_parent_step
    async def _append_parent_step(
        self,
        parent_run_id: str,
        *,
        status: str,
        request: SubagentDelegationRequest,
        child_run_id: str,
        result: SubagentDelegationResult | None = None,
    ) -> None:
        """给 parent run 追加一条 delegation 审计步骤.

        Args:
            parent_run_id: 父 run 标识.
            status: 当前步骤状态.
            request: delegation request.
            child_run_id: child run 标识.
            result: 可选的 delegation result.
        """
        try:
            await self.run_manager.append_step(
                RunStep(
                    step_id=f"step:delegation:{uuid.uuid4().hex}",
                    run_id=parent_run_id,
                    thread_id=request.parent_thread_id,
                    step_type="subagent_delegation",
                    status=status,
                    payload={
                        "skill_name": request.skill_name,
                        "delegate_agent_id": request.delegate_agent_id,
                        "child_run_id": child_run_id,
                        "result_ok": bool(result.ok) if result is not None else None,
                        "result_summary": result.summary if result is not None else "",
                        "result_error": result.error if result is not None else "",
                    },
                    created_at=int(time.time()),
                )
            )
        except Exception:
            logger.exception(
                "Failed to append parent delegation step: parent_run_id=%s child_run_id=%s",
                parent_run_id,
                child_run_id,
            )


# endregion
