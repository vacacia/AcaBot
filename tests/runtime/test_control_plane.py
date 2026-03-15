from pathlib import Path

from acabot.config import Config
from acabot.runtime import (
    AgentProfile,
    AgentProfileRegistry,
    ComputerRuntime,
    ComputerRuntimeConfig,
    FileSystemSkillPackageLoader,
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
    SkillAssignment,
    SkillCatalog,
    ThreadPipeline,
    ToolBroker,
)
from acabot.types import EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway, FakeMessageStore
from .test_pipeline_runtime import FakeAgentRuntime


def _fixtures_root() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "skills"


def _catalog() -> SkillCatalog:
    catalog = SkillCatalog(FileSystemSkillPackageLoader(_fixtures_root()))
    catalog.reload()
    return catalog


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


def _profile_registry() -> AgentProfileRegistry:
    return AgentProfileRegistry(
        profiles={
            "aca": AgentProfile(
                agent_id="aca",
                name="Aca",
                prompt_ref="prompt/default",
                default_model="test-model",
                skill_assignments=[
                    SkillAssignment(
                        skill_name="sample_configured_skill",
                        delegation_mode="prefer_delegate",
                        delegate_agent_id="sample_worker",
                    )
                ],
            )
        },
        default_agent_id="aca",
    )


def _computer_runtime(tmp_path: Path) -> ComputerRuntime:
    return ComputerRuntime(
        config=ComputerRuntimeConfig(
            root_dir=str(tmp_path / "computer"),
            skill_catalog_dir=str(_fixtures_root()),
        )
    )


async def test_runtime_control_plane_reports_status_snapshot(tmp_path: Path) -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    channel_event_store = InMemoryChannelEventStore()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    skill_catalog = _catalog()
    plugin_manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(skill_catalog=skill_catalog),
        skill_catalog=skill_catalog,
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
        skill_catalog=skill_catalog,
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
    assert status.loaded_skills == ["excel_processing", "sample_configured_skill"]
    assert status.interrupted_run_ids == [running.run_id]
    assert status.active_run_count == 1
    assert status.active_runs[0].run_id == waiting.run_id
    assert status.pending_approval_count == 1


async def test_runtime_control_plane_lists_catalog_skills_and_agent_assignments(tmp_path: Path) -> None:
    skill_catalog = _catalog()
    profile_registry = _profile_registry()
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
        profile_registry=profile_registry,
        skill_catalog=skill_catalog,
    )

    skills = await control_plane.list_skills()
    agent_skills = await control_plane.list_agent_skills("aca")

    assert [item.skill_name for item in skills] == [
        "excel_processing",
        "sample_configured_skill",
    ]
    assert skills[0].has_references is True
    assert agent_skills[0].skill_name == "sample_configured_skill"
    assert agent_skills[0].delegation_mode == "prefer_delegate"
    assert agent_skills[0].delegate_agent_id == "sample_worker"


async def test_runtime_control_plane_lists_mirrored_skills(tmp_path: Path) -> None:
    skill_catalog = _catalog()
    computer_runtime = _computer_runtime(tmp_path)
    computer_runtime.mark_skill_loaded("thread:1", "sample_configured_skill")
    await computer_runtime.ensure_loaded_skills_mirrored("thread:1", skill_catalog)

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
        skill_catalog=skill_catalog,
        computer_runtime=computer_runtime,
        memory_store=InMemoryMemoryStore(),
    )

    mirrored = await control_plane.list_mirrored_skills(thread_id="thread:1")

    assert mirrored == ["sample_configured_skill"]


async def test_runtime_control_plane_show_memory_returns_items() -> None:
    store = InMemoryMemoryStore()
    item = MemoryItem(
        memory_id="mem:1",
        scope="channel",
        scope_key="qq:group:1",
        memory_type="sticky_note",
        content="群规",
    )
    await store.upsert(item)
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
        memory_store=store,
    )

    result = await control_plane.show_memory(scope="channel", scope_key="qq:group:1")

    assert len(result.items) == 1
    assert result.items[0].content == "群规"
