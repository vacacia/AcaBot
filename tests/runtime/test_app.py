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


class TrackingGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.started = False

    async def start(self) -> None:
        self.started = True


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


async def test_runtime_app_recovery_interrupts_stale_running_runs_on_start() -> None:
    gateway = TrackingGateway()
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
    run = await run_manager.open(event=_event(), decision=RouteDecision(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:user:10001",
    ))
    await run_manager.mark_running(run.run_id)

    await app.start()

    restored = await run_manager.get(run.run_id)
    assert restored is not None
    assert restored.status == "interrupted"
    assert app.last_recovery_report.interrupted_run_ids == [run.run_id]
    assert gateway.started is True


async def test_runtime_app_recovery_keeps_pending_approval_visible() -> None:
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
    run = await run_manager.open(event=_event(), decision=RouteDecision(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:user:10001",
    ))
    await run_manager.mark_waiting_approval(
        run.run_id,
        reason="tool needs approval",
        approval_context={
            "approval_id": "approval:1",
            "tool_name": "shell.exec",
            "tool_arguments": {"cmd": "ls"},
            "required_action_ids": ["action:approval"],
        },
    )

    report = await app.recover_active_runs()

    restored = await run_manager.get(run.run_id)
    assert restored is not None
    assert restored.status == "waiting_approval"
    assert len(report.pending_approvals) == 1
    assert report.pending_approvals[0].run_id == run.run_id
    assert report.pending_approvals[0].approval_context["approval_id"] == "approval:1"
    assert app.list_pending_approvals()[0].run_id == run.run_id
