from acabot.runtime import (
    AgentProfile,
    InMemoryRunManager,
    InMemoryThreadManager,
    Outbox,
    RouteDecision,
    RuntimeApp,
    RuntimeRouter,
    ThreadPipeline,
)
from acabot.types import EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway, FakeMessageStore
from .test_pipeline_runtime import FakeAgentRuntime


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


def _profile_loader(decision: RouteDecision) -> AgentProfile:
    return AgentProfile(
        agent_id=decision.agent_id,
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
    )


async def test_runtime_app_installs_handler_and_processes_event() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    pipeline = ThreadPipeline(
        agent_runtime=FakeAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
    )
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=thread_manager,
        run_manager=run_manager,
        pipeline=pipeline,
        profile_loader=_profile_loader,
    )

    app.install()
    assert gateway.handler is not None
    await gateway.handler(_event())

    active = await run_manager.list_active()
    assert active == []
    assert len(gateway.sent) == 1
