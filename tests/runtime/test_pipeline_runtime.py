from unittest.mock import AsyncMock, patch

from acabot.agent import ToolSpec
from acabot.runtime import (
    AgentProfile,
    AgentRuntime,
    AgentRuntimeResult,
    ContextCompactionConfig,
    ContextCompactor,
    InMemoryRunManager,
    InMemoryThreadManager,
    InMemoryToolAudit,
    MemoryBlock,
    MemoryBroker,
    ModelAgentRuntime,
    ModelContextSummarizer,
    Outbox,
    PlannedAction,
    PromptAssemblyConfig,
    RouteDecision,
    RunContext,
    RetrievalPlanner,
    StaticPromptLoader,
    ThreadPipeline,
    ToolBroker,
    ToolPolicyDecision,
)
from acabot.types import Action, ActionType, EventAttachment, EventSource, MsgSegment, StandardEvent

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
        request_options=None,
        max_tool_rounds=None,
        tools=None,
        tool_executor=None,
    ):
        _ = system_prompt, messages, model, request_options, max_tool_rounds, tools
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


class RecordingMemoryBroker(MemoryBroker):
    def __init__(self, *, blocks: list[MemoryBlock] | None = None) -> None:
        super().__init__()
        self.blocks = list(blocks or [])
        self.retrieve_calls: list[RunContext] = []
        self.extract_calls: list[RunContext] = []

    async def retrieve(self, ctx: RunContext) -> list[MemoryBlock]:
        self.retrieve_calls.append(ctx)
        return list(self.blocks)

    async def extract_after_run(self, ctx: RunContext) -> None:
        self.extract_calls.append(ctx)


class ExplodingCompactor:
    def snapshot_thread(self, thread) -> None:
        _ = thread
        raise AssertionError("record_only should not snapshot for compaction")


class ExplodingRetrievalPlanner:
    def prepare(self, ctx: RunContext):
        _ = ctx
        raise AssertionError("record_only should not build retrieval plan")

    def assemble(self, ctx: RunContext, *, memory_blocks):
        _ = ctx, memory_blocks
        raise AssertionError("record_only should not assemble prompt")


def _mock_token_counter(model: str = "", messages=None, **kwargs) -> int:
    _ = model, kwargs
    if messages is None:
        return 0
    total = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            total += len(content)
        if "tool_calls" in message:
            total += 20
    return total


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


async def test_thread_pipeline_projects_reply_and_attachment_into_working_memory() -> None:
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

    event = StandardEvent(
        event_id="evt-1",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        segments=[MsgSegment(type="text", data={"text": "请看图"})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role=None,
        reply_to_message_id="msg-0",
        mentioned_user_ids=["20002"],
        attachments=[
            EventAttachment(
                type="image",
                source="https://example.com/cat.jpg",
            )
        ],
    )
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

    assert thread.working_messages[0]["content"] == (
        "[acacia/10001] [reply:msg-0] [mentions:20002] 请看图 [attachments:image]"
    )


async def test_thread_pipeline_injects_memory_blocks_before_agent_runtime() -> None:
    class InspectingAgentRuntime(AgentRuntime):
        def __init__(self) -> None:
            self.captured_messages = []

        async def execute(self, ctx: RunContext) -> AgentRuntimeResult:
            self.captured_messages = list(ctx.messages)
            return AgentRuntimeResult(status="completed", text="hello back")

    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)
    memory_broker = RecordingMemoryBroker(
        blocks=[
            MemoryBlock(
                title="User Profile",
                content="用户喜欢直接回答",
                scope="user",
                metadata={"memory_type": "semantic", "edit_mode": "draft"},
            )
        ]
    )
    agent_runtime = InspectingAgentRuntime()
    pipeline = ThreadPipeline(
        agent_runtime=agent_runtime,
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
        memory_broker=memory_broker,
        retrieval_planner=RetrievalPlanner(PromptAssemblyConfig()),
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

    assert memory_broker.retrieve_calls == [ctx]
    assert ctx.memory_blocks[0].title == "User Profile"
    assert ctx.prompt_slots[0].slot_type == "retrieved_memory"
    assert agent_runtime.captured_messages[0]["role"] == "system"
    assert "User Profile" in str(agent_runtime.captured_messages[0]["content"])


async def test_thread_pipeline_assembles_sticky_summary_and_retrieval_slots() -> None:
    class InspectingAgentRuntime(AgentRuntime):
        def __init__(self) -> None:
            self.captured_messages = []

        async def execute(self, ctx: RunContext) -> AgentRuntimeResult:
            self.captured_messages = list(ctx.messages)
            return AgentRuntimeResult(status="completed", text="ok")

    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    gateway = FakeGateway()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    memory_broker = RecordingMemoryBroker(
        blocks=[
            MemoryBlock(
                title="Rule",
                content="十个月实习只需要成果鉴定",
                scope="channel",
                metadata={"memory_type": "sticky_note", "edit_mode": "readonly"},
            ),
            MemoryBlock(
                title="Relationship Memory",
                content="用户最近在问实习材料",
                scope="relationship",
                metadata={"memory_type": "episodic", "edit_mode": "draft"},
            ),
        ]
    )
    agent_runtime = InspectingAgentRuntime()
    pipeline = ThreadPipeline(
        agent_runtime=agent_runtime,
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
        memory_broker=memory_broker,
        retrieval_planner=RetrievalPlanner(PromptAssemblyConfig()),
    )

    event = _event()
    decision = _decision()
    thread = await thread_manager.get_or_create(
        thread_id=decision.thread_id,
        channel_scope=decision.channel_scope,
        last_event_at=event.timestamp,
    )
    thread.working_summary = "群里最近一直在讨论实习材料"
    run = await run_manager.open(event=event, decision=decision)
    ctx = RunContext(
        run=run,
        event=event,
        decision=decision,
        thread=thread,
        profile=_profile(),
    )

    await pipeline.execute(ctx)

    slot_types = [slot.slot_type for slot in ctx.prompt_slots]
    assert slot_types == ["sticky_notes", "thread_summary", "retrieved_memory"]
    assert "十个月实习只需要成果鉴定" in str(agent_runtime.captured_messages[0]["content"])
    assert agent_runtime.captured_messages[1]["role"] == "user"
    assert "<summary>" in str(agent_runtime.captured_messages[1]["content"])
    assert "群里最近一直在讨论实习材料" in str(agent_runtime.captured_messages[1]["content"])
    assert "Relationship Memory" in str(agent_runtime.captured_messages[2]["content"])


async def test_thread_pipeline_compresses_working_memory_before_model_call() -> None:
    class InspectingAgentRuntime(AgentRuntime):
        def __init__(self) -> None:
            self.captured_messages = []

        async def execute(self, ctx: RunContext) -> AgentRuntimeResult:
            self.captured_messages = list(ctx.messages)
            return AgentRuntimeResult(status="completed", text="ok")

    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    gateway = FakeGateway()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    agent_runtime = InspectingAgentRuntime()
    pipeline = ThreadPipeline(
        agent_runtime=agent_runtime,
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
        context_compactor=ContextCompactor(
            ContextCompactionConfig(
                max_context_ratio=0.02,
                preserve_recent_turns=1,
            )
        ),
        retrieval_planner=RetrievalPlanner(PromptAssemblyConfig()),
    )

    event = _event()
    decision = _decision()
    thread = await thread_manager.get_or_create(
        thread_id=decision.thread_id,
        channel_scope=decision.channel_scope,
        last_event_at=event.timestamp,
    )
    thread.working_messages = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]
    run = await run_manager.open(event=event, decision=decision)
    ctx = RunContext(
        run=run,
        event=event,
        decision=decision,
        thread=thread,
        profile=_profile(),
    )

    with (
        patch(
            "acabot.runtime.context_compactor.token_counter",
            side_effect=_mock_token_counter,
        ),
        patch(
            "acabot.runtime.context_compactor.get_model_info",
            return_value={"max_input_tokens": 1000},
        ),
        ):
            await pipeline.execute(ctx)

    assert ctx.thread.working_summary == ""
    assert len(ctx.retrieval_plan.compressed_messages) == 1
    assert ctx.retrieval_plan.compressed_messages[0]["content"].endswith("hello")
    assert ctx.metadata["token_stats"]["strategy_used"] == "truncate"


async def test_thread_pipeline_uses_compaction_override_when_thread_apply_is_skipped() -> None:
    class InspectingAgentRuntime(AgentRuntime):
        def __init__(self) -> None:
            self.captured_messages = []

        async def execute(self, ctx: RunContext) -> AgentRuntimeResult:
            self.captured_messages = list(ctx.messages)
            return AgentRuntimeResult(status="completed", text="ok")

    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    gateway = FakeGateway()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    agent_runtime = InspectingAgentRuntime()
    summary_agent = AsyncMock()
    summary_agent.complete = AsyncMock(
        return_value=type(
            "Response",
            (),
            {
                "text": "summary override",
                "error": None,
                "usage": {},
                "model_used": "test-model",
            },
        )()
    )
    compactor = ContextCompactor(
        ContextCompactionConfig(
            strategy="summarize",
            max_context_ratio=0.02,
            preserve_recent_turns=1,
        ),
        summarizer=ModelContextSummarizer(
            agent=summary_agent,
            config=ContextCompactionConfig(
                strategy="summarize",
                max_context_ratio=0.02,
                preserve_recent_turns=1,
            ),
        ),
    )
    pipeline = ThreadPipeline(
        agent_runtime=agent_runtime,
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
        context_compactor=compactor,
        retrieval_planner=RetrievalPlanner(PromptAssemblyConfig()),
    )

    event = _event()
    decision = _decision()
    thread = await thread_manager.get_or_create(
        thread_id=decision.thread_id,
        channel_scope=decision.channel_scope,
        last_event_at=event.timestamp,
    )
    thread.working_messages = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]
    run = await run_manager.open(event=event, decision=decision)
    ctx = RunContext(
        run=run,
        event=event,
        decision=decision,
        thread=thread,
        profile=_profile(),
    )

    with (
        patch(
            "acabot.runtime.context_compactor.token_counter",
            side_effect=_mock_token_counter,
        ),
        patch(
            "acabot.runtime.context_compactor.get_model_info",
            return_value={"max_input_tokens": 1000},
        ),
        patch.object(compactor, "apply_to_thread", return_value=False),
    ):
        await pipeline.execute(ctx)

    assert ctx.metadata["compaction_applied_to_thread"] is False
    assert ctx.thread.working_summary == ""
    assert ctx.prompt_slots[0].slot_type == "thread_summary"
    assert "summary override" in str(agent_runtime.captured_messages[0]["content"])


async def test_thread_pipeline_triggers_memory_extraction_after_run() -> None:
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    gateway = FakeGateway()
    store = FakeMessageStore()
    outbox = Outbox(gateway=gateway, store=store)
    memory_broker = RecordingMemoryBroker()
    pipeline = ThreadPipeline(
        agent_runtime=FakeAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
        memory_broker=memory_broker,
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

    assert memory_broker.extract_calls == [ctx]
    assert ctx.run.status == "completed"


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


async def test_thread_pipeline_record_only_skips_compaction_and_retrieval() -> None:
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    gateway = FakeGateway()
    store = FakeMessageStore()
    memory_broker = RecordingMemoryBroker()
    pipeline = ThreadPipeline(
        agent_runtime=FakeAgentRuntime(),
        outbox=Outbox(gateway=gateway, store=store),
        run_manager=run_manager,
        thread_manager=thread_manager,
        memory_broker=memory_broker,
        context_compactor=ExplodingCompactor(),  # type: ignore[arg-type]
        retrieval_planner=ExplodingRetrievalPlanner(),  # type: ignore[arg-type]
    )

    event = _event()
    decision = RouteDecision(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:user:10001",
        run_mode="record_only",
    )
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
    assert memory_broker.retrieve_calls == []
    assert len(memory_broker.extract_calls) == 1
    assert gateway.sent == []
