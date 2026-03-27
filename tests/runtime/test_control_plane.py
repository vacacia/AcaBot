from pathlib import Path

import pytest

from acabot.config import Config
from acabot.runtime import (
    AgentProfile,
    AgentProfileRegistry,
    BackendBridge,
    BackendModeRegistry,
    BackendSessionBindingStore,
    BackendSessionService,
    ComputerPolicy,
    ComputerRuntime,
    ComputerRuntimeConfig,
    FileSystemSkillPackageLoader,
    HostComputerBackend,
    InMemoryChannelEventStore,
    InMemoryRunManager,
    InMemoryThreadManager,
    Outbox,
    RouteDecision,
    RuntimeApp,
    RuntimeControlPlane,
    RuntimePlugin,
    RuntimePluginContext,
    RuntimePluginManager,
    RuntimeRouter,
    SkillCatalog,
    ThreadPipeline,
    ToolBroker,
    build_runtime_components,
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
                skills=["sample_configured_skill"],
            )
        },
        default_agent_id="aca",
    )


def _computer_runtime(tmp_path: Path) -> ComputerRuntime:
    return ComputerRuntime(
        config=ComputerRuntimeConfig(
            root_dir=str(tmp_path / "computer"),
            host_skills_catalog_root_path=str(_fixtures_root()),
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
    assert status.active_runs[0].delegate_agent_id == ""
    assert status.pending_approval_count == 1


async def test_runtime_control_plane_status_exposes_delegate_agent_id() -> None:
    gateway = FakeGateway()
    thread_manager = InMemoryThreadManager()
    run_manager = InMemoryRunManager()
    control_plane = RuntimeControlPlane(
        app=RuntimeApp(
            gateway=gateway,
            router=RuntimeRouter(default_agent_id="aca"),
            thread_manager=thread_manager,
            run_manager=run_manager,
            channel_event_store=InMemoryChannelEventStore(),
            pipeline=ThreadPipeline(
                agent_runtime=FakeAgentRuntime(),
                outbox=Outbox(gateway=gateway, store=FakeMessageStore()),
                run_manager=run_manager,
                thread_manager=thread_manager,
            ),
            profile_loader=_profile_loader,
        ),
        run_manager=run_manager,
    )
    run = await run_manager.open(
        event=_event(),
        decision=RouteDecision(
            thread_id="thread:subagent",
            actor_id="qq:user:10001",
            agent_id="sample_worker",
            channel_scope="qq:user:10001",
            metadata={"run_kind": "subagent", "delegate_agent_id": "sample_worker"},
        ),
    )
    await run_manager.mark_running(run.run_id)

    status = await control_plane.get_status()

    assert status.active_runs[0].delegate_agent_id == "sample_worker"


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
    assert agent_skills[0].has_references is True


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
    )

    mirrored = await control_plane.list_mirrored_skills(thread_id="thread:1")

    assert mirrored == ["sample_configured_skill"]


async def test_runtime_control_plane_reports_backend_status(tmp_path: Path) -> None:
    binding_store = BackendSessionBindingStore(tmp_path / ".acabot-runtime" / "backend" / "session.json")
    binding_store.save(
        backend_id="main",
        transport="rpc",
        pi_session_id="pi-session-1",
        session_file="/tmp/pi-session-1.jsonl",
        created_at=1,
        last_active_at=2,
        status="ready",
    )
    backend_mode_registry = BackendModeRegistry()
    backend_mode_registry.enter_backend_mode(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        entered_at=123,
    )
    app = RuntimeApp(
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
        backend_bridge=BackendBridge(session=BackendSessionService(binding_store)),
        backend_mode_registry=backend_mode_registry,
        backend_admin_actor_ids={"qq:user:10001"},
    )
    control_plane = RuntimeControlPlane(
        app=app,
        run_manager=InMemoryRunManager(),
    )

    status = await control_plane.get_backend_status()

    assert status.configured is False
    assert status.admin_actor_ids == ["qq:user:10001"]
    assert status.session_binding is not None
    assert status.session_binding["pi_session_id"] == "pi-session-1"
    assert status.session_path.endswith(".acabot-runtime/backend/session.json")
    assert status.active_modes[0].thread_id == "qq:user:10001"
    assert await control_plane.get_backend_session_path()
    assert (await control_plane.get_backend_session_binding())["backend_id"] == "main"


async def test_runtime_control_plane_manages_sticky_note_records(tmp_path: Path) -> None:
    components = build_runtime_components(
        Config(
            {
                "agent": {
                    "system_prompt": "You are Aca.",
                },
                "runtime": {
                    "default_agent_id": "aca",
                    "runtime_root": str(tmp_path / ".acabot-runtime"),
                },
            }
        ),
        gateway=FakeGateway(),
        agent=FakeAgentRuntime(),
    )
    control_plane = components.control_plane

    created = await control_plane.create_sticky_note(entity_ref="qq:user:10001")
    saved = await control_plane.save_sticky_note_record(
        entity_ref="qq:user:10001",
        readonly="用户名字叫阿卡西亚",
        editable="喜欢直接结论",
    )
    listed = await control_plane.list_sticky_notes(entity_kind="user")
    loaded = await control_plane.get_sticky_note_record(entity_ref="qq:user:10001")
    deleted = await control_plane.delete_sticky_note(entity_ref="qq:user:10001")

    assert created["entity_ref"] == "qq:user:10001"
    assert saved["readonly"] == "用户名字叫阿卡西亚"
    assert listed["items"][0]["entity_ref"] == "qq:user:10001"
    assert loaded is not None
    assert loaded["editable"] == "喜欢直接结论"
    assert deleted is True


async def test_runtime_control_plane_rejects_invalid_entity_kind_for_sticky_note_list(tmp_path: Path) -> None:
    components = build_runtime_components(
        Config(
            {
                "agent": {
                    "system_prompt": "You are Aca.",
                },
                "runtime": {
                    "default_agent_id": "aca",
                    "runtime_root": str(tmp_path / ".acabot-runtime"),
                },
            }
        ),
        gateway=FakeGateway(),
        agent=FakeAgentRuntime(),
    )

    with pytest.raises(ValueError, match="entity_kind"):
        await components.control_plane.list_sticky_notes(entity_kind="thread")


async def test_computer_runtime_one_shot_exec_persists_backend_state(tmp_path: Path) -> None:
    computer_runtime = _computer_runtime(tmp_path)
    docker_backend = HostComputerBackend(
        stdout_window_bytes=computer_runtime.config.exec_stdout_window_bytes,
        stderr_window_bytes=computer_runtime.config.exec_stderr_window_bytes,
    )
    docker_backend.kind = "docker"  # type: ignore[attr-defined]
    computer_runtime.backends["docker"] = docker_backend
    computer_runtime.workspace_manager.ensure_workspace_layout("thread:1")

    await computer_runtime.exec_once(
        thread_id="thread:1",
        command="printf ok",
        policy=ComputerPolicy(backend="docker"),
    )
    status = await computer_runtime.get_sandbox_status("thread:1")

    assert status.backend_kind == "docker"


