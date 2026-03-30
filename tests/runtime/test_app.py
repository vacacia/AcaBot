from pathlib import Path

from acabot.config import Config
from acabot.runtime import (
    AgentRuntime,
    AgentRuntimeResult,
    ApprovalResumeResult,
    ApprovalResumer,
    InMemoryChannelEventStore,
    InMemoryRunManager,
    InMemoryThreadManager,
    Outbox,
    PlannedAction,
    RouteDecision,
    ResolvedAgent,
    RuntimeApp,
    RuntimeHook,
    RuntimeHookPoint,
    RuntimeHookResult,
    RuntimePlugin,
    RuntimePluginContext,
    RuntimePluginManager,
    RuntimeRouter,
    SessionConfigLoader,
    SessionRuntime,
    ThreadPipeline,
    ToolBroker,
)
from acabot.types import Action, ActionType, EventSource, MsgSegment, StandardEvent

from .test_outbox import ExplodingIngestor, FakeGateway, FakeMessageStore, RecordingIngestor
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


def _agent_loader(decision: RouteDecision) -> ResolvedAgent:
    return ResolvedAgent(
        agent_id=decision.agent_id,
        prompt_ref="prompt/default",
    )


def _broken_agent_loader(decision: RouteDecision) -> ResolvedAgent:
    raise RuntimeError("agent loader exploded")


def _session_router(
    tmp_path: Path,
    session_body: str,
    *,
    agent_body: str = """
agent_id: aca
prompt_ref: prompt/default
visible_tools:
  - read
visible_skills: []
visible_subagents: []
""",
) -> RuntimeRouter:
    bundle_dir = tmp_path / "sessions/qq/user/10001"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(session_body.strip(), encoding="utf-8")
    (bundle_dir / "agent.yaml").write_text(agent_body.strip(), encoding="utf-8")
    return RuntimeRouter(
        default_agent_id="aca",
        session_runtime=SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions")),
    )


class BrokenAgentRuntime(AgentRuntime):
    async def execute(self, ctx):
        raise RuntimeError("agent runtime exploded")


async def test_runtime_router_silent_drops_unconfigured_session(tmp_path: Path) -> None:
    router = RuntimeRouter(
        default_agent_id="aca",
        session_runtime=SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions")),
    )

    decision = await router.route(_event())

    assert decision.run_mode == "silent_drop"
    assert decision.metadata["route_source"] == "unconfigured_session"
    assert "warning" in decision.metadata["drop_reason"]


class TrackingGateway(FakeGateway):
    def __init__(self) -> None:
        super().__init__()
        self.started = False

    async def start(self) -> None:
        self.started = True


class BrokenStartGateway(FakeGateway):
    async def start(self) -> None:
        raise RuntimeError("gateway start exploded")


class FakeApprovalResumer(ApprovalResumer):
    def __init__(self, result: ApprovalResumeResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def resume(
        self,
        *,
        run,
        approval_context,
        metadata,
    ) -> ApprovalResumeResult:
        self.calls.append(
            {
                "run_id": run.run_id,
                "approval_context": dict(approval_context),
                "metadata": dict(metadata),
            }
        )
        return self.result


class TrackingReferenceBackend:
    """用于 stop 测试的 reference backend fake.

    Attributes:
        closed (bool): 是否调用过 close.
    """

    def __init__(self) -> None:
        """初始化 TrackingReferenceBackend."""

        self.closed = False

    async def close(self) -> None:
        """记录 close 调用."""

        self.closed = True


class AppShortcutHook(RuntimeHook):
    name = "app_shortcut"

    async def handle(self, ctx) -> RuntimeHookResult:
        ctx.actions = [
            PlannedAction(
                action_id=f"action:{ctx.run.run_id}:plugin",
                action=Action(
                    action_type=ActionType.SEND_TEXT,
                    target=ctx.event.source,
                    payload={"text": "from plugin"},
                ),
                thread_content="from plugin",
            )
        ]
        return RuntimeHookResult(action="skip_agent")


class TrackingRuntimePlugin(RuntimePlugin):
    name = "tracking_runtime"

    def __init__(self) -> None:
        self.setup_calls = 0
        self.teardown_calls = 0

    async def setup(self, runtime: RuntimePluginContext) -> None:
        _ = runtime
        self.setup_calls += 1

    def hooks(self):
        return [(RuntimeHookPoint.PRE_AGENT, AppShortcutHook())]

    async def teardown(self) -> None:
        self.teardown_calls += 1


class ExplodingTeardownRuntimePlugin(TrackingRuntimePlugin):
    async def teardown(self) -> None:
        await super().teardown()
        raise RuntimeError("plugin teardown exploded")


class ExplodingPluginManager(RuntimePluginManager):
    async def teardown_all(self) -> None:
        raise RuntimeError("plugin manager teardown exploded")


class BrokenEnsureStartedPluginManager(RuntimePluginManager):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.ensure_started_calls = 0
        self.teardown_calls = 0

    async def ensure_started(self) -> None:
        self.ensure_started_calls += 1
        raise RuntimeError("plugin ensure_started exploded")

    async def teardown_all(self) -> None:
        self.teardown_calls += 1


class ExplodingStartIngestor(RecordingIngestor):
    async def start(self) -> None:
        await super().start()
        raise RuntimeError("ltm ingestor start exploded")


async def test_runtime_app_installs_handler_and_processes_event() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
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
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_agent_loader,
    )

    app.install()
    assert gateway.handler is not None
    await gateway.handler(_event())

    active = await run_manager.list_active()
    assert active == []
    assert len(gateway.sent) == 1
    saved = await channel_event_store.get_thread_events("qq:user:10001")
    assert saved[0].event_type == "message"
    assert saved[0].content_text == "hello"


async def test_runtime_app_marks_ltm_dirty_after_channel_event_persist() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    pipeline = ThreadPipeline(
        agent_runtime=FakeAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
    )
    ltm = RecordingIngestor()
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_agent_loader,
        long_term_memory_ingestor=ltm,
    )

    app.install()
    await gateway.handler(_event())

    saved = await channel_event_store.get_thread_events("qq:user:10001")

    assert saved[0].metadata["actor_display_name"] == "acacia"
    assert ltm.marked_threads == ["qq:user:10001"]


async def test_runtime_app_mark_dirty_failure_does_not_break_event_processing() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
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
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_agent_loader,
        long_term_memory_ingestor=ExplodingIngestor(),
    )

    app.install()
    await gateway.handler(_event())

    saved = await channel_event_store.get_thread_events("qq:user:10001")

    assert len(saved) == 1
    assert saved[0].content_text == "hello"


async def test_runtime_app_skips_silent_drop_events(tmp_path: Path) -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    pipeline = ThreadPipeline(
        agent_runtime=FakeAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
    )
    app = RuntimeApp(
        gateway=gateway,
        router=_session_router(
            tmp_path,
            """
session:
  id: qq:user:10001
  template: qq_user
frontstage:
  agent_id: aca
surfaces:
  message.private:
    admission:
      default:
        mode: silent_drop
""",
        ),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_agent_loader,
    )

    app.install()
    await gateway.handler(_event())

    assert run_manager._runs == {}
    assert gateway.sent == []
    assert await channel_event_store.get_thread_events("qq:user:10001") == []


async def test_runtime_app_records_record_only_event_without_loading_agent_snapshot(tmp_path: Path) -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    pipeline = ThreadPipeline(
        agent_runtime=FakeAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
    )
    app = RuntimeApp(
        gateway=gateway,
        router=_session_router(
            tmp_path,
            """
session:
  id: qq:user:10001
  template: qq_user
frontstage:
  agent_id: aca
surfaces:
  message.private:
    admission:
      default:
        mode: record_only
""",
        ),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_broken_agent_loader,
    )

    app.install()
    await gateway.handler(_event())

    run = next(iter(run_manager._runs.values()))
    assert run.status == "completed"
    assert gateway.sent == []
    saved = await channel_event_store.get_thread_events("qq:user:10001")
    assert saved[0].metadata["run_mode"] == "record_only"


async def test_runtime_app_skips_event_log_when_persistence_is_disabled(tmp_path: Path) -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    pipeline = ThreadPipeline(
        agent_runtime=FakeAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
    )
    app = RuntimeApp(
        gateway=gateway,
        router=_session_router(
            tmp_path,
            """
session:
  id: qq:user:10001
  template: qq_user
frontstage:
  agent_id: aca
surfaces:
  message.private:
    admission:
      default:
        mode: respond
    persistence:
      default:
        persist_event: false
    extraction:
      default:
        tags: [ephemeral]
""",
        ),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_agent_loader,
    )

    app.install()
    await gateway.handler(_event())

    run = next(iter(run_manager._runs.values()))
    assert {
        key: value
        for key, value in run.metadata.items()
        if key.startswith("event_")
    } == {
        "event_persist": False,
        "event_tags": ["ephemeral"],
    }
    assert await channel_event_store.get_thread_events("qq:user:10001") == []


async def test_runtime_app_marks_run_failed_when_agent_loader_crashes() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
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
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_broken_agent_loader,
    )

    app.install()
    await gateway.handler(_event())

    run = next(iter(run_manager._runs.values()))
    assert run.status == "failed"
    assert "runtime app crashed" in (run.error or "")


async def test_runtime_app_marks_ltm_dirty_when_agent_loader_crashes_after_event_persist() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    pipeline = ThreadPipeline(
        agent_runtime=FakeAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
    )
    ltm = RecordingIngestor()
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_broken_agent_loader,
        long_term_memory_ingestor=ltm,
    )

    app.install()
    await gateway.handler(_event())

    saved = await channel_event_store.get_thread_events("qq:user:10001")

    assert len(saved) == 1
    assert ltm.marked_threads == ["qq:user:10001"]


async def test_runtime_app_stops_ltm_ingestor_when_gateway_start_crashes() -> None:
    gateway = BrokenStartGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    pipeline = ThreadPipeline(
        agent_runtime=FakeAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
    )
    ltm = RecordingIngestor()
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_agent_loader,
        long_term_memory_ingestor=ltm,
    )

    try:
        await app.start()
    except RuntimeError as exc:
        assert str(exc) == "gateway start exploded"
    else:
        raise AssertionError("expected gateway start failure")

    assert ltm.started == 1
    assert ltm.stopped == 1


async def test_runtime_app_tears_down_plugins_when_gateway_start_crashes() -> None:
    gateway = BrokenStartGateway()
    plugin = TrackingRuntimePlugin()
    plugin_manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(),
        plugins=[plugin],
    )
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=InMemoryThreadManager(),
        run_manager=InMemoryRunManager(),
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=Outbox(gateway=gateway, store=FakeMessageStore()),
            run_manager=InMemoryRunManager(),
            thread_manager=InMemoryThreadManager(),
            plugin_manager=plugin_manager,
        ),
        agent_loader=_agent_loader,
        plugin_manager=plugin_manager,
    )

    try:
        await app.start()
    except RuntimeError as exc:
        assert str(exc) == "gateway start exploded"
    else:
        raise AssertionError("expected gateway start failure")

    assert plugin.setup_calls == 1
    assert plugin.teardown_calls == 1


async def test_runtime_app_tears_down_plugins_when_plugin_start_fails() -> None:
    gateway = TrackingGateway()
    plugin_manager = BrokenEnsureStartedPluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(),
    )
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=InMemoryThreadManager(),
        run_manager=InMemoryRunManager(),
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=Outbox(gateway=gateway, store=FakeMessageStore()),
            run_manager=InMemoryRunManager(),
            thread_manager=InMemoryThreadManager(),
        ),
        agent_loader=_agent_loader,
        plugin_manager=plugin_manager,
    )

    try:
        await app.start()
    except RuntimeError as exc:
        assert str(exc) == "plugin ensure_started exploded"
    else:
        raise AssertionError("expected plugin startup failure")

    assert plugin_manager.ensure_started_calls == 1
    assert plugin_manager.teardown_calls == 1


async def test_runtime_app_tears_down_plugins_when_ltm_start_fails() -> None:
    gateway = TrackingGateway()
    plugin = TrackingRuntimePlugin()
    plugin_manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(),
        plugins=[plugin],
    )
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=InMemoryThreadManager(),
        run_manager=InMemoryRunManager(),
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=Outbox(gateway=gateway, store=FakeMessageStore()),
            run_manager=InMemoryRunManager(),
            thread_manager=InMemoryThreadManager(),
            plugin_manager=plugin_manager,
        ),
        agent_loader=_agent_loader,
        plugin_manager=plugin_manager,
        long_term_memory_ingestor=ExplodingStartIngestor(),
    )

    try:
        await app.start()
    except RuntimeError as exc:
        assert str(exc) == "ltm ingestor start exploded"
    else:
        raise AssertionError("expected ltm start failure")

    assert plugin.setup_calls == 1
    assert plugin.teardown_calls == 1


async def test_runtime_app_keeps_failed_run_terminal_when_pipeline_crashes() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
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
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_agent_loader,
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
    channel_event_store = InMemoryChannelEventStore()
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
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_agent_loader,
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
    channel_event_store = InMemoryChannelEventStore()
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
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_agent_loader,
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


async def test_runtime_app_approve_pending_approval_completes_run() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    resumer = FakeApprovalResumer(ApprovalResumeResult(status="completed"))
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=channel_event_store,
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=outbox,
            run_manager=run_manager,
            thread_manager=thread_manager,
        ),
        agent_loader=_agent_loader,
        approval_resumer=resumer,
    )
    run = await run_manager.open(
        event=_event(),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
    )
    await run_manager.mark_waiting_approval(
        run.run_id,
        reason="tool needs approval",
        approval_context={
            "approval_id": "approval:1",
            "tool_name": "shell.exec",
            "tool_arguments": {"cmd": "ls"},
        },
    )
    await app.recover_active_runs()

    result = await app.approve_pending_approval(
        run.run_id,
        metadata={"approved_by": "qq:user:42"},
    )

    restored = await run_manager.get(run.run_id)
    assert result.ok is True
    assert result.run_status == "completed"
    assert restored is not None
    assert restored.status == "completed"
    assert resumer.calls[0]["approval_context"]["approval_id"] == "approval:1"
    assert resumer.calls[0]["metadata"]["approved_by"] == "qq:user:42"
    assert app.list_pending_approvals() == []


async def test_runtime_app_approve_pending_approval_can_reenter_waiting_state() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    resumer = FakeApprovalResumer(
        ApprovalResumeResult(
            status="waiting_approval",
            message="need second approval",
            approval_context={
                "approval_id": "approval:2",
                "tool_name": "shell.exec",
                "tool_arguments": {"cmd": "rm -rf /tmp/demo"},
            },
        )
    )
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=channel_event_store,
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=outbox,
            run_manager=run_manager,
            thread_manager=thread_manager,
        ),
        agent_loader=_agent_loader,
        approval_resumer=resumer,
    )
    run = await run_manager.open(
        event=_event(),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
    )
    await run_manager.mark_waiting_approval(
        run.run_id,
        reason="tool needs approval",
        approval_context={"approval_id": "approval:1"},
    )
    await app.recover_active_runs()

    result = await app.approve_pending_approval(run.run_id)

    restored = await run_manager.get(run.run_id)
    assert result.ok is True
    assert result.run_status == "waiting_approval"
    assert result.pending_approval is not None
    assert result.pending_approval.approval_context["approval_id"] == "approval:2"
    assert restored is not None
    assert restored.status == "waiting_approval"
    assert app.list_pending_approvals()[0].approval_context["approval_id"] == "approval:2"


async def test_runtime_app_reject_pending_approval_cancels_run() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=channel_event_store,
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=outbox,
            run_manager=run_manager,
            thread_manager=thread_manager,
        ),
        agent_loader=_agent_loader,
    )
    run = await run_manager.open(
        event=_event(),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
    )
    await run_manager.mark_waiting_approval(
        run.run_id,
        reason="tool needs approval",
        approval_context={"approval_id": "approval:1"},
    )
    await app.recover_active_runs()

    result = await app.reject_pending_approval(
        run.run_id,
        reason="operator denied shell access",
    )

    restored = await run_manager.get(run.run_id)
    assert result.ok is True
    assert result.run_status == "cancelled"
    assert restored is not None
    assert restored.status == "cancelled"
    assert restored.error == "operator denied shell access"
    assert app.list_pending_approvals() == []


async def test_runtime_app_stop_closes_reference_backend() -> None:
    gateway = TrackingGateway()
    reference_backend = TrackingReferenceBackend()
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=InMemoryThreadManager(),
        run_manager=InMemoryRunManager(),
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=Outbox(gateway=gateway, store=FakeMessageStore()),
            run_manager=InMemoryRunManager(),
            thread_manager=InMemoryThreadManager(),
        ),
        agent_loader=_agent_loader,
        reference_backend=reference_backend,
    )

    await app.stop()

    assert reference_backend.closed is True


async def test_runtime_app_lazily_starts_plugins_on_first_event() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    pipeline = ThreadPipeline(
        agent_runtime=BrokenAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
    )
    plugin = TrackingRuntimePlugin()
    plugin_manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(),
        plugins=[plugin],
    )
    pipeline.plugin_manager = plugin_manager
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_agent_loader,
        plugin_manager=plugin_manager,
    )

    app.install()
    await gateway.handler(_event())

    assert plugin.setup_calls == 1
    assert len(gateway.sent) == 1
    assert gateway.sent[0].payload["text"] == "from plugin"


async def test_runtime_app_stop_tears_down_runtime_plugins() -> None:
    gateway = TrackingGateway()
    plugin = TrackingRuntimePlugin()
    plugin_manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(),
        plugins=[plugin],
    )
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=InMemoryThreadManager(),
        run_manager=InMemoryRunManager(),
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=Outbox(gateway=gateway, store=FakeMessageStore()),
            run_manager=InMemoryRunManager(),
            thread_manager=InMemoryThreadManager(),
        ),
        agent_loader=_agent_loader,
        plugin_manager=plugin_manager,
    )

    await app.start()
    await app.stop()

    assert plugin.setup_calls == 1
    assert plugin.teardown_calls == 1


async def test_runtime_app_stop_still_stops_ltm_after_plugin_teardown_failure() -> None:
    gateway = TrackingGateway()
    plugin_manager = ExplodingPluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(),
    )
    ltm = RecordingIngestor()
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=InMemoryThreadManager(),
        run_manager=InMemoryRunManager(),
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=Outbox(gateway=gateway, store=FakeMessageStore()),
            run_manager=InMemoryRunManager(),
            thread_manager=InMemoryThreadManager(),
            plugin_manager=plugin_manager,
        ),
        agent_loader=_agent_loader,
        plugin_manager=plugin_manager,
        long_term_memory_ingestor=ltm,
    )

    await app.start()

    try:
        await app.stop()
    except RuntimeError as exc:
        assert str(exc) == "plugin manager teardown exploded"
    else:
        raise AssertionError("expected plugin teardown failure")

    assert ltm.stopped == 1


async def test_runtime_app_tears_down_plugins_when_lazy_plugin_start_fails_on_event() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    pipeline = ThreadPipeline(
        agent_runtime=FakeAgentRuntime(),
        outbox=outbox,
        run_manager=run_manager,
        thread_manager=thread_manager,
    )
    plugin_manager = BrokenEnsureStartedPluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(),
    )
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=channel_event_store,
        pipeline=pipeline,
        agent_loader=_agent_loader,
        plugin_manager=plugin_manager,
    )

    app.install()
    await gateway.handler(_event())

    assert plugin_manager.ensure_started_calls == 1
    assert plugin_manager.teardown_calls == 1


async def test_runtime_app_can_reload_plugins_from_config() -> None:
    from tests.runtime.runtime_plugin_samples import SampleConfiguredRuntimePlugin

    SampleConfiguredRuntimePlugin.reset()
    gateway = TrackingGateway()
    plugin_manager = RuntimePluginManager(
        config=Config(
            {
                "runtime": {
                    "plugins": [
                        "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                    ],
                },
            }
        ),
        gateway=gateway,
        tool_broker=ToolBroker(),
    )
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=InMemoryThreadManager(),
        run_manager=InMemoryRunManager(),
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=Outbox(gateway=gateway, store=FakeMessageStore()),
            run_manager=InMemoryRunManager(),
            thread_manager=InMemoryThreadManager(),
            plugin_manager=plugin_manager,
        ),
        agent_loader=_agent_loader,
        plugin_manager=plugin_manager,
    )

    loaded, missing = await app.reload_plugins()

    assert loaded == ["sample_configured_runtime"]
    assert missing == []
    assert SampleConfiguredRuntimePlugin.setup_calls == 1
