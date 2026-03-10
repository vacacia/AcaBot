from acabot.agent import ToolSpec
from acabot.runtime import (
    AgentProfile,
    AgentRuntime,
    AgentRuntimeResult,
    InMemoryRunManager,
    InMemoryThreadManager,
    InMemoryToolAudit,
    ModelAgentRuntime,
    Outbox,
    PlannedAction,
    RouteDecision,
    RunContext,
    StaticPromptLoader,
    ThreadPipeline,
    ToolBroker,
    ToolPolicyDecision,
)
from acabot.types import Action, ActionType, EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway, FakeMessageStore


class FakeAgentRuntime(AgentRuntime):
    async def execute(self, ctx: RunContext) -> AgentRuntimeResult:
        return AgentRuntimeResult(
            status="completed",
            text="hello back",
            actions=[
                PlannedAction(
                    action_id="action:reply",
                    action=Action(
                        action_type=ActionType.SEND_TEXT,
                        target=ctx.event.source,
                        payload={"text": "hello back"},
                    ),
                    thread_content="hello back",
                )
            ],
        )


class FailingAgentRuntime(AgentRuntime):
    async def execute(self, ctx: RunContext) -> AgentRuntimeResult:
        raise RuntimeError("agent runtime exploded")


class FailureActionAgentRuntime(AgentRuntime):
    async def execute(self, ctx: RunContext) -> AgentRuntimeResult:
        return AgentRuntimeResult(
            status="failed",
            error="tool flow failed",
            actions=[
                PlannedAction(
                    action_id="action:failure",
                    action=Action(
                        action_type=ActionType.SEND_TEXT,
                        target=ctx.event.source,
                        payload={"text": "failure action"},
                    ),
                    thread_content="failure action",
                    commit_when="failure",
                )
            ],
        )


class ApprovalToolAgent:
    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, object]],
        model: str | None = None,
        *,
        tools=None,
        tool_executor=None,
    ):
        _ = system_prompt, messages, model, tools
        if tool_executor is not None:
            await tool_executor("restricted", {"danger": True})
        raise AssertionError("approval interrupt should stop the agent loop")


class CountingThreadManager(InMemoryThreadManager):
    def __init__(self) -> None:
        super().__init__()
        self.save_calls = 0

    async def save(self, thread) -> None:
        self.save_calls += 1
        await super().save(thread)


class NoAckGateway(FakeGateway):
    async def send(self, action: Action) -> dict[str, object] | None:
        self.sent.append(action)
        return None


def _event(event_type: str = "message") -> StandardEvent:
    return StandardEvent(
        event_id="evt-1",
        event_type=event_type,
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        segments=[MsgSegment(type="text", data={"text": "hello"})] if event_type == "message" else [],
        raw_message_id="msg-1" if event_type == "message" else "",
        sender_nickname="acacia",
        sender_role=None,
        target_message_id="msg-42" if event_type == "recall" else None,
    )


def _profile() -> AgentProfile:
    return AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
    )


def _decision() -> RouteDecision:
    return RouteDecision(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:user:10001",
    )


async def test_thread_pipeline_runs_minimal_text_flow() -> None:
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)
    pipeline = ThreadPipeline(
        agent_runtime=FakeAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
    )

    event = _event()
    decision = _decision()
    thread = await thread_manager.get_or_create(
        thread_id=decision.thread_id,
        channel_scope=decision.channel_scope,
        last_event_at=event.timestamp,
    )
    run = await run_manager.open(event=event, decision=decision)
    ctx = RunContext(
        run=run,
        event=event,
        decision=decision,
        thread=thread,
        profile=_profile(),
    )

    await pipeline.execute(ctx)

    updated_run = await run_manager.get(run.run_id)
    assert updated_run is not None
    assert updated_run.status == "completed"
    assert len(gateway.sent) == 1
    assert thread.working_messages[0]["role"] == "user"
    assert thread.working_messages[1]["content"] == "hello back"


async def test_thread_pipeline_marks_run_failed_when_agent_runtime_crashes() -> None:
    thread_manager = CountingThreadManager()
    run_manager = InMemoryRunManager()
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)
    pipeline = ThreadPipeline(
        agent_runtime=FailingAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
    )

    event = _event()
    decision = _decision()
    thread = await thread_manager.get_or_create(
        thread_id=decision.thread_id,
        channel_scope=decision.channel_scope,
        last_event_at=event.timestamp,
    )
    run = await run_manager.open(event=event, decision=decision)
    ctx = RunContext(
        run=run,
        event=event,
        decision=decision,
        thread=thread,
        profile=_profile(),
    )

    await pipeline.execute(ctx)

    updated_run = await run_manager.get(run.run_id)
    assert updated_run is not None
    assert updated_run.status == "failed"
    assert "pipeline crashed" in (updated_run.error or "")
    assert gateway.sent == []
    assert thread_manager.save_calls == 1
    assert thread.working_messages[0]["role"] == "user"


async def test_thread_pipeline_projects_notice_event_into_working_memory() -> None:
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)
    pipeline = ThreadPipeline(
        agent_runtime=FakeAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
    )

    event = _event("poke")
    decision = _decision()
    thread = await thread_manager.get_or_create(
        thread_id=decision.thread_id,
        channel_scope=decision.channel_scope,
        last_event_at=event.timestamp,
    )
    run = await run_manager.open(event=event, decision=decision)
    ctx = RunContext(
        run=run,
        event=event,
        decision=decision,
        thread=thread,
        profile=_profile(),
    )

    await pipeline.execute(ctx)

    assert thread.working_messages[0]["content"] == "[acacia/10001] [notice:poke]"


async def test_thread_pipeline_dispatches_failure_actions_before_marking_failed() -> None:
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)
    pipeline = ThreadPipeline(
        agent_runtime=FailureActionAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
    )

    event = _event()
    decision = _decision()
    thread = await thread_manager.get_or_create(
        thread_id=decision.thread_id,
        channel_scope=decision.channel_scope,
        last_event_at=event.timestamp,
    )
    run = await run_manager.open(event=event, decision=decision)
    ctx = RunContext(
        run=run,
        event=event,
        decision=decision,
        thread=thread,
        profile=_profile(),
    )

    await pipeline.execute(ctx)

    updated_run = await run_manager.get(run.run_id)
    assert updated_run is not None
    assert updated_run.status == "failed"
    assert len(gateway.sent) == 1
    assert gateway.sent[0].payload["text"] == "failure action"


async def test_thread_pipeline_enters_waiting_approval_after_prompt_delivery() -> None:
    class ApprovalPolicy:
        async def allow(self, *, spec, arguments, ctx) -> ToolPolicyDecision:
            _ = spec, arguments, ctx
            return ToolPolicyDecision(
                allowed=True,
                requires_approval=True,
                reason="needs admin approval",
                metadata={"risk_level": "dangerous"},
            )

    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)
    audit = InMemoryToolAudit()
    broker = ToolBroker(policy=ApprovalPolicy(), audit=audit)

    async def restricted(arguments: dict[str, object], ctx) -> dict[str, object]:
        _ = arguments, ctx
        return {"ok": True}

    broker.register_tool(
        ToolSpec(
            name="restricted",
            description="Restricted tool",
            parameters={"type": "object", "properties": {}},
        ),
        restricted,
    )
    pipeline = ThreadPipeline(
        agent_runtime=ModelAgentRuntime(
            agent=ApprovalToolAgent(),
            prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
            tool_runtime_resolver=broker.build_tool_runtime,
        ),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
        tool_broker=broker,
    )

    event = _event()
    decision = _decision()
    thread = await thread_manager.get_or_create(
        thread_id=decision.thread_id,
        channel_scope=decision.channel_scope,
        last_event_at=event.timestamp,
    )
    run = await run_manager.open(event=event, decision=decision)
    ctx = RunContext(
        run=run,
        event=event,
        decision=decision,
        thread=thread,
        profile=_profile(),
    )
    ctx.profile.enabled_tools = ["restricted"]

    await pipeline.execute(ctx)

    updated_run = await run_manager.get(run.run_id)
    assert updated_run is not None
    assert updated_run.status == "waiting_approval"
    assert len(gateway.sent) == 1
    record = next(iter(audit.records.values()))
    assert record.status == "waiting_approval"
    assert record.metadata["approval_prompt_delivered"] is True


async def test_thread_pipeline_fails_when_approval_prompt_not_delivered() -> None:
    class ApprovalPolicy:
        async def allow(self, *, spec, arguments, ctx) -> ToolPolicyDecision:
            _ = spec, arguments, ctx
            return ToolPolicyDecision(
                allowed=True,
                requires_approval=True,
                reason="needs admin approval",
            )

    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    gateway = NoAckGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)
    audit = InMemoryToolAudit()
    broker = ToolBroker(policy=ApprovalPolicy(), audit=audit)

    async def restricted(arguments: dict[str, object], ctx) -> dict[str, object]:
        _ = arguments, ctx
        return {"ok": True}

    broker.register_tool(
        ToolSpec(
            name="restricted",
            description="Restricted tool",
            parameters={"type": "object", "properties": {}},
        ),
        restricted,
    )
    pipeline = ThreadPipeline(
        agent_runtime=ModelAgentRuntime(
            agent=ApprovalToolAgent(),
            prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
            tool_runtime_resolver=broker.build_tool_runtime,
        ),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
        tool_broker=broker,
    )

    event = _event()
    decision = _decision()
    thread = await thread_manager.get_or_create(
        thread_id=decision.thread_id,
        channel_scope=decision.channel_scope,
        last_event_at=event.timestamp,
    )
    run = await run_manager.open(event=event, decision=decision)
    ctx = RunContext(
        run=run,
        event=event,
        decision=decision,
        thread=thread,
        profile=_profile(),
    )
    ctx.profile.enabled_tools = ["restricted"]

    await pipeline.execute(ctx)

    updated_run = await run_manager.get(run.run_id)
    assert updated_run is not None
    assert updated_run.status == "failed"
    record = next(iter(audit.records.values()))
    assert record.status == "failed"
    assert record.error == "approval prompt not delivered"
