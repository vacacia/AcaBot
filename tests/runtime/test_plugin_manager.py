from typing import Any

from acabot.agent import ToolDef
from acabot.config import Config
from acabot.runtime import (
    AgentProfile,
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
    load_runtime_plugins_from_config,
    ThreadPipeline,
    ToolBroker,
)
from acabot.types import Action, ActionType, EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway, FakeMessageStore
# region fake plugin
class ReplyShortcutHook(RuntimeHook):
    """在 PRE_AGENT 阶段直接回消息的最小 hook."""

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
    """用于 runtime plugin 测试的最小插件.

    Attributes:
        name (str): 插件名.
        setup_calls (int): setup 调用次数.
        teardown_calls (int): teardown 调用次数.
        setup_config (dict[str, object]): setup 时读取到的插件配置.
    """

    name = "echo_runtime"

    def __init__(self) -> None:
        """初始化测试插件."""

        self.setup_calls = 0
        self.teardown_calls = 0
        self.setup_config: dict[str, object] = {}

    async def setup(self, runtime: RuntimePluginContext) -> None:
        """记录 setup 调用和配置.

        Args:
            runtime: runtime plugin 上下文.
        """

        self.setup_calls += 1
        self.setup_config = runtime.get_plugin_config(self.name)

    def hooks(self) -> list[tuple[RuntimeHookPoint, RuntimeHook]]:
        """返回测试用 hook 列表.

        Returns:
            一条 PRE_AGENT hook.
        """

        return [(RuntimeHookPoint.PRE_AGENT, ReplyShortcutHook())]

    def tools(self) -> list[ToolDef]:
        """返回测试用 legacy ToolDef.

        Returns:
            一条 `echo_plugin_tool`.
        """

        async def handler(arguments: dict[str, Any]) -> Any:
            return {"echo": arguments.get("text", "")}

        return [
            ToolDef(
                name="echo_plugin_tool",
                description="Echo text from runtime plugin.",
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
                handler=handler,
            )
        ]

    async def teardown(self) -> None:
        """记录 teardown 调用."""

        self.teardown_calls += 1


# endregion


class FailingAgentRuntime:
    async def execute(self, ctx: RunContext):
        _ = ctx
        raise AssertionError("plugin should skip agent runtime")


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
        default_model="test-model",
        enabled_tools=["echo_plugin_tool"],
    )


async def test_runtime_plugin_manager_registers_tools_and_lifecycle() -> None:
    config = Config({"plugins": {"echo_runtime": {"enabled": True, "mode": "test"}}})
    plugin = EchoRuntimePlugin()
    tool_broker = ToolBroker()
    manager = RuntimePluginManager(
        config=config,
        gateway=FakeGateway(),
        tool_broker=tool_broker,
        plugins=[plugin],
    )

    await manager.ensure_started()

    visible = tool_broker.visible_tools(_profile())
    assert plugin.setup_calls == 1
    assert plugin.setup_config == {"enabled": True, "mode": "test"}
    assert [tool.name for tool in visible] == ["echo_plugin_tool"]

    await manager.teardown_all()
    assert plugin.teardown_calls == 1


async def test_thread_pipeline_can_be_short_circuited_by_runtime_plugin() -> None:
    plugin = EchoRuntimePlugin()
    gateway = FakeGateway()
    outbox = Outbox(gateway=gateway, store=FakeMessageStore())
    tool_broker = ToolBroker()
    plugin_manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=tool_broker,
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
    tool_broker = ToolBroker()
    manager = RuntimePluginManager(
        config=config,
        gateway=FakeGateway(),
        tool_broker=tool_broker,
    )
    sample_profile = AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        enabled_tools=["sample_configured_tool"],
    )

    loaded_names = await manager.reload_from_config()
    visible_before = tool_broker.visible_tools(sample_profile)
    loaded_again = await manager.reload_from_config()
    visible_after = tool_broker.visible_tools(sample_profile)

    assert loaded_names == ["sample_configured_runtime"]
    assert loaded_again == ["sample_configured_runtime"]
    assert [tool.name for tool in visible_before] == ["sample_configured_tool"]
    assert [tool.name for tool in visible_after] == ["sample_configured_tool"]
    assert SampleConfiguredRuntimePlugin.setup_calls == 2
    assert SampleConfiguredRuntimePlugin.teardown_calls == 1
