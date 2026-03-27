from pathlib import Path
from typing import Any

import pytest

from acabot.agent import ToolDef
from acabot.config import Config
from acabot.runtime import (
    AgentProfile,
    ComputerRuntime,
    ComputerRuntimeConfig,
    FileSystemSkillPackageLoader,
    InMemoryRunManager,
    InMemoryThreadManager,
    Outbox,
    PlannedAction,
    RouteDecision,
    RunContext,
    RuntimeHook,
    RuntimeHookPoint,
    RuntimeHookResult,
    RuntimePlugin,
    RuntimePluginContext,
    RuntimePluginManager,
    RuntimePluginModelSlot,
    SkillCatalog,
    SubagentDelegationBroker,
    SubagentExecutorRegistry,
    ThreadPipeline,
    ToolBroker,
    MutableModelTargetCatalog,
    ModelReloadSnapshot,
    load_runtime_plugins_from_config,
)
from acabot.types import Action, ActionType, EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway, FakeMessageStore


def _fixtures_root() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "skills"


def _catalog() -> SkillCatalog:
    catalog = SkillCatalog(FileSystemSkillPackageLoader(_fixtures_root()))
    catalog.reload()
    return catalog


def _computer_runtime(tmp_path: Path) -> ComputerRuntime:
    return ComputerRuntime(
        config=ComputerRuntimeConfig(
            root_dir=str(tmp_path / "computer"),
            host_skills_catalog_root_path=str(_fixtures_root()),
        )
    )


class ReplyShortcutHook(RuntimeHook):
    name = "reply_shortcut"

    async def handle(self, ctx: RunContext) -> RuntimeHookResult:
        ctx.actions = [
            PlannedAction(
                action_id=f"action:{ctx.run.run_id}:plugin",
                action=Action(
                    action_type=ActionType.SEND_TEXT,
                    target=ctx.event.source,
                    payload={"text": "plugin handled"},
                ),
                thread_content="plugin handled",
            )
        ]
        return RuntimeHookResult(action="skip_agent")


class EchoRuntimePlugin(RuntimePlugin):
    name = "echo_runtime"

    def __init__(self) -> None:
        self.setup_calls = 0
        self.teardown_calls = 0
        self.setup_config: dict[str, object] = {}

    async def setup(self, runtime: RuntimePluginContext) -> None:
        self.setup_calls += 1
        self.setup_config = runtime.get_plugin_config(self.name)

    def hooks(self) -> list[tuple[RuntimeHookPoint, RuntimeHook]]:
        return [(RuntimeHookPoint.PRE_AGENT, ReplyShortcutHook())]

    def tools(self) -> list[ToolDef]:
        async def handler(arguments: dict[str, Any]) -> Any:
            return {"echo": arguments.get("text", "")}

        return [
            ToolDef(
                name="echo_plugin_tool",
                description="Echo text from runtime plugin.",
                parameters={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                handler=handler,
            )
        ]

    async def teardown(self) -> None:
        self.teardown_calls += 1


class FailingAgentRuntime:
    async def execute(self, ctx: RunContext):
        _ = ctx
        raise AssertionError("plugin should skip agent runtime")


class BuiltinMarkerPlugin(RuntimePlugin):
    """用于验证 builtin plugin 保留逻辑的最小假插件."""

    name = "builtin_marker"

    async def setup(self, runtime: RuntimePluginContext) -> None:
        """这个测试插件不需要额外初始化.

        Args:
            runtime: 当前 runtime plugin 上下文.
        """

        _ = runtime

    def tools(self) -> list[ToolDef]:
        """返回一条最小 builtin marker 工具.

        Returns:
            list[ToolDef]: 只包含一条 builtin marker 工具.
        """

        async def handler(arguments: dict[str, Any]) -> Any:
            _ = arguments
            return {"ok": True}

        return [
            ToolDef(
                name="builtin_marker",
                description="Builtin marker tool.",
                parameters={"type": "object", "properties": {}},
                handler=handler,
            )
        ]


class SlotPlugin(RuntimePlugin):
    name = "slot_plugin"

    async def setup(self, runtime: RuntimePluginContext) -> None:
        _ = runtime

    def model_slots(self) -> list[RuntimePluginModelSlot]:
        return [
            RuntimePluginModelSlot(
                slot_id="extractor",
                task_kind="chat",
                required=True,
                allow_fallbacks=True,
                description="slot extractor",
            )
        ]


def _event() -> StandardEvent:
    return StandardEvent(
        event_id="evt-plugin",
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
        raw_message_id="msg-plugin",
        sender_nickname="acacia",
        sender_role=None,
    )


def _decision() -> RouteDecision:
    return RouteDecision(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:user:10001",
    )


def _profile() -> AgentProfile:
    return AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        enabled_tools=["echo_plugin_tool"],
    )


async def test_runtime_plugin_manager_registers_tools_and_lifecycle() -> None:
    config = Config({"plugins": {"echo_runtime": {"enabled": True, "mode": "test"}}})
    plugin = EchoRuntimePlugin()
    tool_broker = ToolBroker(skill_catalog=_catalog())
    manager = RuntimePluginManager(
        config=config,
        gateway=FakeGateway(),
        tool_broker=tool_broker,
        skill_catalog=_catalog(),
        plugins=[plugin],
    )

    await manager.ensure_started()

    visible = tool_broker.visible_tools(_profile())
    assert plugin.setup_calls == 1
    assert plugin.setup_config == {"enabled": True, "mode": "test"}
    assert [tool.name for tool in visible] == ["echo_plugin_tool"]

    await manager.teardown_all()
    assert plugin.teardown_calls == 1


async def test_runtime_plugin_manager_registers_plugin_model_targets() -> None:
    catalog = _catalog()
    target_catalog = MutableModelTargetCatalog(system_targets=[])
    manager = RuntimePluginManager(
        config=Config({}),
        gateway=FakeGateway(),
        tool_broker=ToolBroker(skill_catalog=catalog),
        skill_catalog=catalog,
        model_target_catalog=target_catalog,
        plugins=[SlotPlugin()],
    )

    await manager.ensure_started()

    target = target_catalog.get("plugin:slot_plugin:extractor")
    assert target is not None
    assert target.source_kind == "plugin"

    await manager.unload_plugins(["slot_plugin"])
    assert target_catalog.get("plugin:slot_plugin:extractor") is None


async def test_runtime_plugin_manager_rolls_back_plugin_targets_when_registry_reload_fails() -> None:
    class RejectingControlPlane:
        def __init__(self) -> None:
            self.reload_calls = 0

        async def reload_models(self) -> ModelReloadSnapshot:
            self.reload_calls += 1
            return ModelReloadSnapshot(ok=False, error="preset task_kind mismatch")

    catalog = _catalog()
    target_catalog = MutableModelTargetCatalog(system_targets=[])
    control_plane = RejectingControlPlane()
    manager = RuntimePluginManager(
        config=Config({}),
        gateway=FakeGateway(),
        tool_broker=ToolBroker(skill_catalog=catalog),
        skill_catalog=catalog,
        model_target_catalog=target_catalog,
        control_plane=control_plane,  # type: ignore[arg-type]
        plugins=[SlotPlugin()],
    )

    await manager.ensure_started()

    assert control_plane.reload_calls == 2
    assert manager.loaded == []
    assert target_catalog.get("plugin:slot_plugin:extractor") is None


async def test_runtime_plugin_manager_unload_keeps_state_consistent_when_registry_reload_fails() -> None:
    class FlakyControlPlane:
        def __init__(self) -> None:
            self.reload_calls = 0

        async def reload_models(self) -> ModelReloadSnapshot:
            self.reload_calls += 1
            if self.reload_calls == 1:
                return ModelReloadSnapshot(ok=True)
            return ModelReloadSnapshot(ok=False, error="registry reload failed during unload")

    catalog = _catalog()
    target_catalog = MutableModelTargetCatalog(system_targets=[])
    control_plane = FlakyControlPlane()
    manager = RuntimePluginManager(
        config=Config({}),
        gateway=FakeGateway(),
        tool_broker=ToolBroker(skill_catalog=catalog),
        skill_catalog=catalog,
        model_target_catalog=target_catalog,
        control_plane=control_plane,  # type: ignore[arg-type]
        plugins=[SlotPlugin()],
    )

    await manager.ensure_started()

    with pytest.raises(ValueError, match="registry reload failed during unload"):
        await manager.unload_plugins(["slot_plugin"])

    assert control_plane.reload_calls == 2
    assert manager.loaded == []
    assert "slot_plugin" not in manager._names
    assert target_catalog.get("plugin:slot_plugin:extractor") is None


async def test_runtime_plugin_manager_registers_and_unloads_subagent_executors() -> None:
    from tests.runtime.runtime_plugin_samples import SampleDelegationWorkerPlugin

    catalog = _catalog()
    executor_registry = SubagentExecutorRegistry()
    manager = RuntimePluginManager(
        config=Config({}),
        gateway=FakeGateway(),
        tool_broker=ToolBroker(skill_catalog=catalog),
        skill_catalog=catalog,
        subagent_delegator=SubagentDelegationBroker(
            executor_registry=executor_registry,
        ),
        plugins=[SampleDelegationWorkerPlugin()],
    )

    await manager.ensure_started()
    before = [item.agent_id for item in executor_registry.list_all()]
    removed = await manager.unload_plugins(["sample_delegation_worker"])
    after = [item.agent_id for item in executor_registry.list_all()]

    assert before == ["sample_worker"]
    assert removed == ["sample_delegation_worker"]
    assert after == []


async def test_thread_pipeline_can_be_short_circuited_by_runtime_plugin() -> None:
    plugin = EchoRuntimePlugin()
    gateway = FakeGateway()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    tool_broker = ToolBroker(skill_catalog=_catalog())
    plugin_manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=tool_broker,
        skill_catalog=_catalog(),
        plugins=[plugin],
    )
    await plugin_manager.ensure_started()

    pipeline = ThreadPipeline(
        agent_runtime=FailingAgentRuntime(),
        outbox=outbox,
        run_manager=InMemoryRunManager(),
        thread_manager=InMemoryThreadManager(),
        tool_broker=tool_broker,
        plugin_manager=plugin_manager,
    )

    event = _event()
    decision = _decision()
    thread = await pipeline.thread_manager.get_or_create(
        thread_id=decision.thread_id,
        channel_scope=decision.channel_scope,
        last_event_at=event.timestamp,
    )
    run = await pipeline.run_manager.open(event=event, decision=decision)
    ctx = RunContext(
        run=run,
        event=event,
        decision=decision,
        thread=thread,
        profile=_profile(),
    )

    await pipeline.execute(ctx)

    updated = await pipeline.run_manager.get(run.run_id)
    assert updated is not None
    assert updated.status == "completed"
    assert len(gateway.sent) == 1
    assert gateway.sent[0].payload["text"] == "plugin handled"


def test_load_runtime_plugins_from_config_supports_import_paths() -> None:
    from tests.runtime.runtime_plugin_samples import SampleConfiguredRuntimePlugin

    SampleConfiguredRuntimePlugin.reset()
    config = Config(
        {
            "runtime": {
                "plugins": [
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                ],
            },
        }
    )

    plugins = load_runtime_plugins_from_config(config)

    assert len(plugins) == 1
    assert plugins[0].name == "sample_configured_runtime"


async def test_runtime_plugin_manager_reload_clears_old_tools_and_reloads() -> None:
    from tests.runtime.runtime_plugin_samples import SampleConfiguredRuntimePlugin

    SampleConfiguredRuntimePlugin.reset()
    config = Config(
        {
            "runtime": {
                "plugins": [
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                ],
            },
        }
    )
    catalog = _catalog()
    tool_broker = ToolBroker(skill_catalog=catalog)
    manager = RuntimePluginManager(
        config=config,
        gateway=FakeGateway(),
        tool_broker=tool_broker,
        skill_catalog=catalog,
    )
    sample_profile = AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        enabled_tools=["sample_configured_tool"],
    )

    loaded_names, missing = await manager.reload_from_config()
    visible_before = tool_broker.visible_tools(sample_profile)
    loaded_again, missing_again = await manager.reload_from_config()
    visible_after = tool_broker.visible_tools(sample_profile)

    assert loaded_names == ["sample_configured_runtime"]
    assert loaded_again == ["sample_configured_runtime"]
    assert missing == []
    assert missing_again == []
    assert [tool.name for tool in visible_before] == ["sample_configured_tool"]
    assert [tool.name for tool in visible_after] == ["sample_configured_tool"]
    assert SampleConfiguredRuntimePlugin.setup_calls == 2
    assert SampleConfiguredRuntimePlugin.teardown_calls == 1


async def test_runtime_plugin_manager_can_reload_selected_plugins_only() -> None:
    from tests.runtime.runtime_plugin_samples import (
        AnotherConfiguredRuntimePlugin,
        SampleConfiguredRuntimePlugin,
    )

    SampleConfiguredRuntimePlugin.reset()
    AnotherConfiguredRuntimePlugin.reset()
    config = Config(
        {
            "runtime": {
                "plugins": [
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                    "tests.runtime.runtime_plugin_samples:AnotherConfiguredRuntimePlugin",
                ],
            },
        }
    )
    catalog = _catalog()
    manager = RuntimePluginManager(
        config=config,
        gateway=FakeGateway(),
        tool_broker=ToolBroker(skill_catalog=catalog),
        skill_catalog=catalog,
    )

    loaded_names, missing = await manager.reload_from_config()
    reloaded_names, missing_after = await manager.reload_from_config(["sample_configured_runtime"])

    assert loaded_names == ["sample_configured_runtime", "another_configured_runtime"]
    assert missing == []
    assert reloaded_names == ["sample_configured_runtime"]
    assert missing_after == []
    assert SampleConfiguredRuntimePlugin.setup_calls == 2
    assert SampleConfiguredRuntimePlugin.teardown_calls == 1
    assert AnotherConfiguredRuntimePlugin.setup_calls == 1
    assert AnotherConfiguredRuntimePlugin.teardown_calls == 0


async def test_runtime_plugin_manager_selected_reload_updates_failed_import_paths() -> None:
    config = Config(
        {
            "runtime": {
                "plugins": [
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                    "does.not.exist:MissingOne",
                ],
            },
        }
    )
    manager = RuntimePluginManager(
        config=config,
        gateway=FakeGateway(),
        tool_broker=ToolBroker(skill_catalog=_catalog()),
        skill_catalog=_catalog(),
    )

    loaded_names, missing = await manager.reload_from_config()
    assert loaded_names == ["sample_configured_runtime"]
    assert missing == ["does.not.exist:MissingOne"]
    assert manager.failed_plugin_import_paths == ["does.not.exist:MissingOne"]

    config.replace(
        {
            "runtime": {
                "plugins": [
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                    "still.missing:MissingTwo",
                ],
            },
        }
    )
    reloaded_names, missing_after = await manager.reload_from_config(["sample_configured_runtime"])

    assert reloaded_names == ["sample_configured_runtime"]
    assert missing_after == []
    assert manager.failed_plugin_import_paths == ["still.missing:MissingTwo"]


async def test_runtime_plugin_manager_selected_reload_keeps_builtin_plugins(
    tmp_path: Path,
) -> None:
    from tests.runtime.runtime_plugin_samples import SampleConfiguredRuntimePlugin

    SampleConfiguredRuntimePlugin.reset()
    config = Config(
        {
            "runtime": {
                "plugins": [
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                ],
            },
        }
    )
    manager = RuntimePluginManager(
        config=config,
        gateway=FakeGateway(),
        tool_broker=ToolBroker(),
        computer_runtime=_computer_runtime(tmp_path),
        builtin_plugins=[BuiltinMarkerPlugin()],
    )

    loaded_names, missing = await manager.reload_from_config()
    builtin_profile = AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        enabled_tools=["builtin_marker"],
    )
    visible_before = manager.tool_broker.visible_tools(builtin_profile)

    reloaded_names, missing_after = await manager.reload_from_config(
        ["sample_configured_runtime"]
    )
    visible_after = manager.tool_broker.visible_tools(builtin_profile)

    assert "builtin_marker" in loaded_names
    assert "sample_configured_runtime" in loaded_names
    assert missing == []
    assert reloaded_names == ["sample_configured_runtime"]
    assert missing_after == []
    assert [tool.name for tool in visible_before] == ["builtin_marker"]
    assert [tool.name for tool in visible_after] == ["builtin_marker"]
