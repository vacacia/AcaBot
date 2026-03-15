from pathlib import Path

from acabot.config import Config
from acabot.runtime import (
    AgentProfile,
    AgentProfileRegistry,
    ComputerRuntime,
    ComputerRuntimeConfig,
    ComputerRuntimeOverride,
    FileSystemModelRegistryManager,
    InMemoryChannelEventStore,
    InMemoryMemoryStore,
    InMemoryRunManager,
    InMemoryThreadManager,
    MemoryItem,
    ModelBinding,
    ModelProvider,
    ModelPreset,
    OpenAICompatibleProviderConfig,
    Outbox,
    RouteDecision,
    RunContext,
    SubagentDelegationBroker,
    SubagentExecutorRegistry,
    RuntimeApp,
    RuntimeControlPlane,
    RuntimePlugin,
    RuntimePluginContext,
    RuntimePluginManager,
    RuntimeRouter,
    SkillAssignment,
    SkillRegistry,
    SkillSpec,
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

    def skills(self) -> list[SkillSpec]:
        return [
            SkillSpec(
                skill_name="status_runtime_skill",
                skill_type="capability",
                title="Status Runtime Skill",
                description="用于控制面状态测试的样例 skill.",
                tool_names=[],
            )
        ]


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
    skill_registry = SkillRegistry()
    plugin_manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(skill_registry=skill_registry),
        skill_registry=skill_registry,
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
        skill_registry=plugin_manager.skill_registry,
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
    assert status.loaded_skills == ["status_runtime_skill"]
    assert status.interrupted_run_ids == [running.run_id]
    assert status.active_run_count == 1
    assert status.active_runs[0].run_id == waiting.run_id
    assert status.active_runs[0].run_kind == "user"
    assert status.active_runs[0].parent_run_id == ""
    assert status.active_runs[0].delegated_skill == ""
    assert status.pending_approval_count == 1
    assert status.pending_approvals[0].approval_context["approval_id"] == "approval:1"


async def test_runtime_control_plane_reports_child_run_metadata() -> None:
    gateway = FakeGateway()
    run_manager = InMemoryRunManager()
    skill_registry = SkillRegistry()
    plugin_manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(skill_registry=skill_registry),
        skill_registry=skill_registry,
    )
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=InMemoryThreadManager(),
        run_manager=run_manager,
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=Outbox(gateway=gateway, store=FakeMessageStore()),
            run_manager=run_manager,
            thread_manager=InMemoryThreadManager(),
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

    run = await run_manager.open(
        event=_event(),
        decision=RouteDecision(
            thread_id="subagent:run:parent:worker:abcd1234",
            actor_id="qq:user:10001",
            agent_id="worker",
            channel_scope="qq:user:10001",
            metadata={
                "run_kind": "subagent",
                "parent_run_id": "run:parent",
                "delegated_skill": "excel_processing",
            },
        ),
    )
    await run_manager.mark_running(run.run_id)

    status = await control_plane.get_status()

    assert status.active_run_count == 1
    assert status.active_runs[0].run_kind == "subagent"
    assert status.active_runs[0].parent_run_id == "run:parent"
    assert status.active_runs[0].delegated_skill == "excel_processing"


async def test_runtime_control_plane_can_reload_plugins() -> None:
    from tests.runtime.runtime_plugin_samples import SampleConfiguredRuntimePlugin

    SampleConfiguredRuntimePlugin.reset()
    gateway = FakeGateway()
    skill_registry = SkillRegistry()
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
        tool_broker=ToolBroker(skill_registry=skill_registry),
        skill_registry=skill_registry,
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
        skill_registry=plugin_manager.skill_registry,
    )

    result = await control_plane.reload_plugins()

    assert result.loaded_plugins == ["sample_configured_runtime"]
    assert result.missing_plugins == []


async def test_runtime_control_plane_can_reload_selected_plugins() -> None:
    from tests.runtime.runtime_plugin_samples import (
        AnotherConfiguredRuntimePlugin,
        SampleConfiguredRuntimePlugin,
    )

    SampleConfiguredRuntimePlugin.reset()
    AnotherConfiguredRuntimePlugin.reset()
    gateway = FakeGateway()
    skill_registry = SkillRegistry()
    plugin_manager = RuntimePluginManager(
        config=Config(
            {
                "runtime": {
                    "plugins": [
                        "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                        "tests.runtime.runtime_plugin_samples:AnotherConfiguredRuntimePlugin",
                    ],
                },
            }
        ),
        gateway=gateway,
        tool_broker=ToolBroker(skill_registry=skill_registry),
        skill_registry=skill_registry,
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
        skill_registry=plugin_manager.skill_registry,
    )

    await control_plane.reload_plugins()
    result = await control_plane.reload_plugins(["sample_configured_runtime", "missing_plugin"])

    assert result.requested_plugins == ["sample_configured_runtime", "missing_plugin"]
    assert result.loaded_plugins == ["sample_configured_runtime"]
    assert result.missing_plugins == ["missing_plugin"]


async def test_runtime_control_plane_can_list_skills() -> None:
    gateway = FakeGateway()
    skill_registry = SkillRegistry()
    plugin_manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(skill_registry=skill_registry),
        skill_registry=skill_registry,
        plugins=[StatusRuntimePlugin()],
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
        skill_registry=skill_registry,
    )
    await plugin_manager.ensure_started()

    skills = await control_plane.list_skills()

    assert len(skills) == 1
    assert skills[0].skill_name == "status_runtime_skill"


async def test_runtime_control_plane_can_list_agent_skills() -> None:
    gateway = FakeGateway()
    skill_registry = SkillRegistry()
    plugin_manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(skill_registry=skill_registry),
        skill_registry=skill_registry,
        plugins=[StatusRuntimePlugin()],
    )
    profile_registry = AgentProfileRegistry(
        profiles={
            "aca": AgentProfile(
                agent_id="aca",
                name="Aca",
                prompt_ref="prompt/default",
                default_model="test-model",
                skill_assignments=[
                    SkillAssignment(
                        skill_name="status_runtime_skill",
                        delegation_mode="prefer_delegate",
                        delegate_agent_id="status_worker",
                    )
                ],
            )
        },
        default_agent_id="aca",
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
        profile_registry=profile_registry,
        plugin_manager=plugin_manager,
        skill_registry=skill_registry,
    )
    await plugin_manager.ensure_started()

    skills = await control_plane.list_agent_skills("aca")

    assert len(skills) == 1
    assert skills[0].skill_name == "status_runtime_skill"
    assert skills[0].delegation_mode == "prefer_delegate"
    assert skills[0].delegate_agent_id == "status_worker"


async def test_runtime_control_plane_can_list_subagent_executors() -> None:
    from tests.runtime.runtime_plugin_samples import SampleDelegationWorkerPlugin

    gateway = FakeGateway()
    skill_registry = SkillRegistry()
    executor_registry = SubagentExecutorRegistry()
    plugin_manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=ToolBroker(skill_registry=skill_registry),
        skill_registry=skill_registry,
        subagent_delegator=SubagentDelegationBroker(
            skill_registry=skill_registry,
            executor_registry=executor_registry,
        ),
        plugins=[SampleDelegationWorkerPlugin()],
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
        subagent_executor_registry=executor_registry,
    )
    await plugin_manager.ensure_started()

    items = await control_plane.list_subagent_executors()

    assert len(items) == 1
    assert items[0].agent_id == "sample_worker"
    assert items[0].source == "plugin:sample_delegation_worker"


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


async def test_runtime_control_plane_can_manage_models(tmp_path: Path) -> None:
    manager = FileSystemModelRegistryManager(
        providers_dir=tmp_path / "models/providers",
        presets_dir=tmp_path / "models/presets",
        bindings_dir=tmp_path / "models/bindings",
        legacy_global_default_model="legacy-global",
    )
    profile_registry = AgentProfileRegistry(
        profiles={
            "aca": AgentProfile(
                agent_id="aca",
                name="Aca",
                prompt_ref="prompt/default",
                default_model="profile-model",
                config={},
            ),
        },
        default_agent_id="aca",
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
        profile_registry=profile_registry,
        model_registry_manager=manager,
    )

    provider_result = await control_plane.upsert_model_provider(
        ModelProvider(
            provider_id="openai-main",
            kind="openai_compatible",
            config=OpenAICompatibleProviderConfig(
                base_url="https://llm.example.com/v1",
                api_key_env="OPENAI_API_KEY",
            ),
        )
    )
    preset_result = await control_plane.upsert_model_preset(
        ModelPreset(
            preset_id="preset-main",
            provider_id="openai-main",
            model="gpt-main",
            context_window=128000,
        )
    )
    binding_result = await control_plane.upsert_model_binding(
        ModelBinding(
            binding_id="binding:aca",
            target_type="agent",
            target_id="aca",
            preset_id="preset-main",
            timeout_sec=12,
        )
    )
    preview = await control_plane.preview_effective_agent_model("aca")
    impact = await control_plane.get_model_provider_impact("openai-main")
    status = await control_plane.get_model_registry_status()
    bindings = await control_plane.list_model_bindings()

    assert provider_result.ok is True
    assert preset_result.ok is True
    assert binding_result.ok is True
    assert preview.request is not None
    assert preview.request.model == "gpt-main"
    assert preview.request.execution_params["timeout"] == 12
    assert impact.preset_ids == ["preset-main"]
    assert impact.binding_ids == ["binding:aca"]
    assert impact.agent_ids == ["aca"]
    assert status.provider_count == 1
    assert len(bindings) == 1


async def test_runtime_control_plane_can_list_workspaces(tmp_path: Path) -> None:
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
    )
    computer_runtime = ComputerRuntime(
        config=ComputerRuntimeConfig(
            root_dir=str(tmp_path / "workspaces"),
            skill_catalog_dir=str(tmp_path / "workspaces/catalog/skills"),
        )
    )
    thread = await app.thread_manager.get_or_create(
        thread_id="qq:user:10001",
        channel_scope="qq:user:10001",
    )
    ctx = RunContext(
        run=await app.run_manager.open(
            event=_event(),
            decision=RouteDecision(
                thread_id="qq:user:10001",
                actor_id="qq:user:10001",
                agent_id="aca",
                channel_scope="qq:user:10001",
            ),
        ),
        event=_event(),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
        thread=thread,
        profile=_profile_loader(
            RouteDecision(
                thread_id="qq:user:10001",
                actor_id="qq:user:10001",
                agent_id="aca",
                channel_scope="qq:user:10001",
            )
        ),
    )
    await computer_runtime.prepare_run_context(ctx)
    control_plane = RuntimeControlPlane(
        app=app,
        run_manager=app.run_manager,
        thread_manager=app.thread_manager,
        computer_runtime=computer_runtime,
    )

    items = await control_plane.list_workspaces()

    assert len(items) == 1
    assert items[0].thread_id == "qq:user:10001"

    attachments = await control_plane.list_workspace_attachments(thread_id="qq:user:10001")
    sandbox = await control_plane.get_sandbox_status(thread_id="qq:user:10001")

    assert attachments == []
    assert sandbox.backend_kind == "host"


async def test_runtime_control_plane_lists_workspace_activity_from_exec_steps(
    tmp_path: Path,
) -> None:
    run_manager = InMemoryRunManager()
    app = RuntimeApp(
        gateway=FakeGateway(),
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=InMemoryThreadManager(),
        run_manager=run_manager,
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=Outbox(gateway=FakeGateway(), store=FakeMessageStore()),
            run_manager=run_manager,
            thread_manager=InMemoryThreadManager(),
        ),
        profile_loader=_profile_loader,
    )
    computer_runtime = ComputerRuntime(
        config=ComputerRuntimeConfig(
            root_dir=str(tmp_path / "workspaces"),
            skill_catalog_dir=str(tmp_path / "workspaces/catalog/skills"),
        ),
        run_manager=run_manager,
    )
    thread = await app.thread_manager.get_or_create(
        thread_id="qq:user:10001",
        channel_scope="qq:user:10001",
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
    ctx = RunContext(
        run=run,
        event=_event(),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
        thread=thread,
        profile=_profile_loader(
            RouteDecision(
                thread_id="qq:user:10001",
                actor_id="qq:user:10001",
                agent_id="aca",
                channel_scope="qq:user:10001",
            )
        ),
    )
    await computer_runtime.prepare_run_context(ctx)
    await computer_runtime.exec_once(
        thread_id=thread.thread_id,
        run_id=run.run_id,
        command="printf 'activity'",
        policy=ctx.computer_policy_effective,
    )
    control_plane = RuntimeControlPlane(
        app=app,
        run_manager=run_manager,
        computer_runtime=computer_runtime,
    )

    items = await control_plane.list_workspace_activity(
        thread_id="qq:user:10001",
        step_types=["exec"],
    )

    assert len(items) == 1
    assert items[0].thread_id == "qq:user:10001"
    assert items[0].payload["command"] == "printf 'activity'"


async def test_runtime_control_plane_prune_workspace_force_cancels_active_run(
    tmp_path: Path,
) -> None:
    run_manager = InMemoryRunManager()
    thread_manager = InMemoryThreadManager()
    app = RuntimeApp(
        gateway=FakeGateway(),
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=Outbox(gateway=FakeGateway(), store=FakeMessageStore()),
            run_manager=run_manager,
            thread_manager=thread_manager,
        ),
        profile_loader=_profile_loader,
    )
    computer_runtime = ComputerRuntime(
        config=ComputerRuntimeConfig(
            root_dir=str(tmp_path / "workspaces"),
            skill_catalog_dir=str(tmp_path / "workspaces/catalog/skills"),
        ),
        run_manager=run_manager,
    )
    thread = await thread_manager.get_or_create(
        thread_id="qq:user:10001",
        channel_scope="qq:user:10001",
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
    await run_manager.mark_running(run.run_id)
    ctx = RunContext(
        run=run,
        event=_event(),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
        thread=thread,
        profile=_profile_loader(
            RouteDecision(
                thread_id="qq:user:10001",
                actor_id="qq:user:10001",
                agent_id="aca",
                channel_scope="qq:user:10001",
            )
        ),
    )
    await computer_runtime.prepare_run_context(ctx)
    session = await computer_runtime.open_session(
        thread_id=thread.thread_id,
        run_id=run.run_id,
        agent_id="aca",
        policy=ctx.computer_policy_effective,
    )
    control_plane = RuntimeControlPlane(
        app=app,
        run_manager=run_manager,
        thread_manager=thread_manager,
        computer_runtime=computer_runtime,
    )

    result = await control_plane.prune_workspace(
        thread_id=thread.thread_id,
        force=True,
    )
    updated = await run_manager.get(run.run_id)
    items = await control_plane.list_workspace_activity(
        thread_id=thread.thread_id,
        step_types=["workspace_prune"],
    )

    assert result.ok is True
    assert updated is not None
    assert updated.status == "cancelled"
    assert session.session_id not in computer_runtime.list_session_ids(thread.thread_id)
    assert len(items) == 1


async def test_runtime_control_plane_rejects_active_thread_computer_override_without_force(
    tmp_path: Path,
) -> None:
    run_manager = InMemoryRunManager()
    thread_manager = InMemoryThreadManager()
    app = RuntimeApp(
        gateway=FakeGateway(),
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=ThreadPipeline(
            agent_runtime=FakeAgentRuntime(),
            outbox=Outbox(gateway=FakeGateway(), store=FakeMessageStore()),
            run_manager=run_manager,
            thread_manager=thread_manager,
        ),
        profile_loader=_profile_loader,
    )
    computer_runtime = ComputerRuntime(
        config=ComputerRuntimeConfig(
            root_dir=str(tmp_path / "workspaces"),
            skill_catalog_dir=str(tmp_path / "workspaces/catalog/skills"),
        ),
        run_manager=run_manager,
    )
    thread = await thread_manager.get_or_create(
        thread_id="qq:user:10001",
        channel_scope="qq:user:10001",
    )
    run = await run_manager.open(
        event=_event(),
        decision=RouteDecision(
            thread_id=thread.thread_id,
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
    )
    await run_manager.mark_running(run.run_id)
    control_plane = RuntimeControlPlane(
        app=app,
        run_manager=run_manager,
        thread_manager=thread_manager,
        computer_runtime=computer_runtime,
    )

    result = await control_plane.set_thread_computer_override(
        thread_id=thread.thread_id,
        override=ComputerRuntimeOverride(backend="docker"),
    )

    assert result.ok is False
    assert result.message == "thread in use"
