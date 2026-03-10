from acabot.runtime import (
    AgentProfile,
    AgentRuntime,
    AgentRuntimeResult,
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


def _broken_profile_loader(decision: RouteDecision) -> AgentProfile:
    raise RuntimeError("profile loader exploded")


class BrokenAgentRuntime(AgentRuntime):
    async def execute(self, ctx):
        raise RuntimeError("agent runtime exploded")


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


async def test_runtime_app_marks_run_failed_when_profile_loader_crashes() -> None:
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
        profile_loader=_broken_profile_loader,
    )

    app.install()
    await gateway.handler(_event())

    run = next(iter(run_manager._runs.values()))
    assert run.status == "failed"
    assert "runtime app crashed" in (run.error or "")


async def test_runtime_app_keeps_failed_run_terminal_when_pipeline_crashes() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    pipeline = ThreadPipeline(
        agent_runtime=BrokenAgentRuntime(),
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
    await gateway.handler(_event())

    run = next(iter(run_manager._runs.values()))
    assert run.status == "failed"
    assert "pipeline crashed" in (run.error or "")
