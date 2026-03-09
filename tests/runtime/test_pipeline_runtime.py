from acabot.runtime import (
    AgentProfile,
    AgentRuntime,
    AgentRuntimeResult,
    InMemoryRunManager,
    InMemoryThreadManager,
    Outbox,
    PlannedAction,
    RouteDecision,
    RunContext,
    ThreadPipeline,
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


def _event() -> StandardEvent:
    return StandardEvent(
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
        segments=[MsgSegment(type="text", data={"text": "hello"})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role=None,
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
