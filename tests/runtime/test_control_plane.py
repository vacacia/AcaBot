from acabot.config import Config
from acabot.runtime import (
    AgentProfile,
    AgentProfileRegistry,
    InMemoryChannelEventStore,
    InMemoryMemoryStore,
    InMemoryRunManager,
    InMemoryThreadManager,
    MemoryItem,
    Outbox,
    RouteDecision,
    RuntimeApp,
    RuntimeControlPlane,
    RuntimePlugin,
    RuntimePluginContext,
    RuntimePluginManager,
    RuntimeRouter,
    ThreadPipeline,
    ToolBroker,
)
from acabot.types import EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway, FakeMessageStore
from .test_pipeline_runtime import FakeAgentRuntime


def _profile_loader(decision: RouteDecision) -> AgentProfile:
    return AgentProfile(
        agent_id=decision.agent_id,
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
    )


class StatusRuntimePlugin(RuntimePlugin):
    name = "status_runtime"

    async def setup(self, runtime: RuntimePluginContext) -> None:
        _ = runtime


def _event(*, event_id: str = "evt-1") -> StandardEvent:
    return StandardEvent(
        event_id=event_id,
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
        raw_message_id=f"msg-{event_id}",
        sender_nickname="acacia",
        sender_role=None,
    )


async def test_runtime_control_plane_reports_status_snapshot() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    plugin_manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(),
        plugins=[StatusRuntimePlugin()],
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
            plugin_manager=plugin_manager,
        ),
        profile_loader=_profile_loader,
        plugin_manager=plugin_manager,
    )
    control_plane = RuntimeControlPlane(
        app=app,
        run_manager=run_manager,
        plugin_manager=plugin_manager,
    )
    await plugin_manager.ensure_started()

    running = await run_manager.open(
        event=_event(),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
    )
    await run_manager.mark_running(running.run_id)
    waiting = await run_manager.open(
        event=_event(event_id="evt-2"),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
    )
    await run_manager.mark_waiting_approval(
        waiting.run_id,
        reason="tool needs approval",
        approval_context={"approval_id": "approval:1"},
    )
    await app.recover_active_runs()

    status = await control_plane.get_status()

    assert status.loaded_plugins == ["status_runtime"]
    assert status.interrupted_run_ids == [running.run_id]
    assert status.active_run_count == 1
    assert status.active_runs[0].run_id == waiting.run_id
    assert status.pending_approval_count == 1
    assert status.pending_approvals[0].approval_context["approval_id"] == "approval:1"


async def test_runtime_control_plane_can_reload_plugins() -> None:
    from tests.runtime.runtime_plugin_samples import SampleConfiguredRuntimePlugin

    SampleConfiguredRuntimePlugin.reset()
    gateway = FakeGateway()
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
        profile_loader=_profile_loader,
        plugin_manager=plugin_manager,
    )
    control_plane = RuntimeControlPlane(
        app=app,
        run_manager=app.run_manager,
        plugin_manager=plugin_manager,
    )

    result = await control_plane.reload_plugins()

    assert result.loaded_plugins == ["sample_configured_runtime"]


async def test_runtime_control_plane_can_switch_thread_agent_override() -> None:
    thread_manager = InMemoryThreadManager()
    profile_registry = AgentProfileRegistry(
        profiles={
            "aca": AgentProfile(
                agent_id="aca",
                name="Aca",
                prompt_ref="prompt/default",
                default_model="test-model",
            ),
            "ops": AgentProfile(
                agent_id="ops",
                name="Ops",
                prompt_ref="prompt/ops",
                default_model="ops-model",
            ),
        },
        default_agent_id="aca",
    )
    thread = await thread_manager.get_or_create(
        thread_id="qq:user:10001",
        channel_scope="qq:user:10001",
    )
    app = RuntimeApp(
        gateway=FakeGateway(),
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=thread_manager,
        run_manager=InMemoryRunManager(),
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=Outbox(gateway=FakeGateway(), store=FakeMessageStore()),
            run_manager=InMemoryRunManager(),
            thread_manager=thread_manager,
        ),
        profile_loader=_profile_loader,
    )
    control_plane = RuntimeControlPlane(
        app=app,
        run_manager=app.run_manager,
        thread_manager=thread_manager,
        profile_registry=profile_registry,
    )

    result = await control_plane.switch_thread_agent(
        thread_id=thread.thread_id,
        agent_id="ops",
    )
    restored = await thread_manager.get(thread.thread_id)

    assert result.ok is True
    assert restored is not None
    assert restored.metadata["thread_agent_override"] == "ops"


async def test_runtime_control_plane_can_show_memory() -> None:
    memory_store = InMemoryMemoryStore()
    await memory_store.upsert(
        MemoryItem(
            memory_id="mem:1",
            scope="user",
            scope_key="qq:user:10001",
            memory_type="sticky_note",
            content="用户名字叫阿卡西亚",
            edit_mode="readonly",
        )
    )
    control_plane = RuntimeControlPlane(
        app=RuntimeApp(
            gateway=FakeGateway(),
            router=RuntimeRouter(default_agent_id="aca"),
            thread_manager=InMemoryThreadManager(),
            run_manager=InMemoryRunManager(),
            channel_event_store=InMemoryChannelEventStore(),
            pipeline=ThreadPipeline(
                agent_runtime=FakeAgentRuntime(),
                outbox=Outbox(gateway=FakeGateway(), store=FakeMessageStore()),
                run_manager=InMemoryRunManager(),
                thread_manager=InMemoryThreadManager(),
            ),
            profile_loader=_profile_loader,
        ),
        run_manager=InMemoryRunManager(),
        memory_store=memory_store,
    )

    result = await control_plane.show_memory(
        scope="user",
        scope_key="qq:user:10001",
        memory_types=["sticky_note"],
    )

    assert result.scope == "user"
    assert result.scope_key == "qq:user:10001"
    assert len(result.items) == 1
    assert result.items[0].content == "用户名字叫阿卡西亚"
