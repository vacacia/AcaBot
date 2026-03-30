"""main.py 测试.

这一组测试只验证新的 RuntimeApp 启动链路.
旧的 Session + Pipeline 组装不再属于默认主路径.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acabot.config import Config
from acabot.main import build_runtime_app, create_message_store, wait_for_shutdown_signal
from acabot.runtime import (
    ComputerRuntime,
    ComputerRuntimeConfig,
    ResolvedAgent,
    ContextAssembler,
    ContextCompactionConfig,
    ContextCompactor,
    FileSystemModelRegistryManager,
    InMemoryChannelEventStore,
    InMemoryMessageStore,
    LocalSubagentExecutionService,
    MemoryBroker,
    NoopApprovalResumer,
    NullReferenceBackend,
    PayloadJsonWriter,
    RetrievalPlanner,
    RouteDecision,
    RuntimeComponents,
    RuntimeControlPlane,
    SkillCatalog,
    SoulSource,
    SQLiteMessageStore,
    StickyNoteFileStore,
    StickyNoteRenderer,
    StickyNoteService,
    SubagentCatalog,
    SubagentDelegationBroker,
    BackendBridge,
    BackendModeRegistry,
    BackendSessionService,
)


class FakeGateway:
    """用于 main 测试的最小 Gateway."""

    def __init__(self) -> None:
        """初始化 fake gateway."""

        self.handler = None

    async def start(self) -> None:
        """模拟启动 Gateway."""

        return None

    async def stop(self) -> None:
        """模拟停止 Gateway."""

        return None

    async def send(self, action: Any) -> dict[str, object] | None:
        """模拟发送动作.

        Args:
            action: 待发送动作.

        Returns:
            一份最小回执.
        """

        _ = action
        return {"message_id": "msg-1"}

    def on_event(self, handler) -> None:
        """注册事件处理器.

        Args:
            handler: 标准事件处理函数.
        """

        self.handler = handler


@dataclass
class FakeAgent:
    """用于 main 测试的最小默认 agent."""

    max_tool_rounds: int

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        request_options=None,
        max_tool_rounds=None,
        tools=None,
        tool_executor=None,
    ) -> Any:
        """模拟执行一次 agent run.

        Args:
            system_prompt: 本次调用使用的 system prompt.
            messages: 上下文消息列表.
            model: 可选的模型名覆盖.
            request_options: 当前 run 解析好的 request options.

        Returns:
            一个最小响应对象.
        """

        _ = request_options, max_tool_rounds, tools, tool_executor
        return type(
            "Response",
            (),
            {
                "text": "ok",
                "attachments": [],
                "error": None,
                "usage": {},
                "tool_calls_made": [],
                "model_used": model or "",
                "raw": {"system_prompt": system_prompt, "messages": messages},
            },
        )()


def test_create_message_store_returns_none_by_default() -> None:
    """create_message_store 默认不覆盖 bootstrap 的 MessageStore 选择."""

    store = create_message_store(Config({}))

    assert store is None


def test_build_runtime_app_uses_factories_and_runtime_config() -> None:
    """build_runtime_app 能把 factory 和 runtime config 正确接到新主线."""

    seen: dict[str, Any] = {}

    def gateway_factory(config: Config) -> FakeGateway:
        """构造 fake gateway.

        Args:
            config: 已加载的 Config 对象.

        Returns:
            一个 fake gateway.
        """

        seen["gateway"] = config.get("gateway", {})
        return FakeGateway()

    def agent_factory(config: Config) -> FakeAgent:
        """构造 fake agent.

        Args:
            config: 已加载的 Config 对象.

        Returns:
            一个 fake agent.
        """

        agent_conf = config.get("agent", {})
        seen["agent"] = agent_conf
        return FakeAgent(
            max_tool_rounds=agent_conf.get("max_tool_rounds", 5),
        )

    config = Config(
        {
            "gateway": {"host": "127.0.0.1", "port": 9100, "timeout": 30.0},
            "agent": {
                "max_tool_rounds": 9,
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_agent_name": "Aca",
                "default_prompt_ref": "prompt/aca",
                "prompts": {
                    "prompt/aca": "You are Aca."
                },
            },
        }
    )

    components = build_runtime_app(
        config,
        gateway_factory=gateway_factory,
        agent_factory=agent_factory,
    )
    profile = components.agent_loader(
        RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        )
    )

    assert seen["gateway"]["port"] == 9100
    assert seen["agent"]["max_tool_rounds"] == 9
    assert components.router.default_agent_id == "aca"
    assert components.prompt_loader.load("prompt/aca") == "You are Aca."
    assert profile.name == "Aca"
    assert isinstance(components.message_store, InMemoryMessageStore)


def test_build_runtime_app_keeps_bootstrap_sqlite_selection(tmp_path) -> None:
    """build_runtime_app 不应短路 bootstrap 的 SQLite MessageStore 选择."""

    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_agent_name": "Aca",
                "default_prompt_ref": "prompt/aca",
                "prompts": {
                    "prompt/aca": "You are Aca."
                },
                "persistence": {
                    "sqlite_path": str(tmp_path / "runtime.sqlite3"),
                },
            },
        }
    )

    components = build_runtime_app(
        config,
        gateway_factory=lambda config: FakeGateway(),
        agent_factory=lambda config: FakeAgent(
            max_tool_rounds=config.get("agent", {}).get("max_tool_rounds", 5),
        ),
    )

    assert isinstance(components.message_store, SQLiteMessageStore)


async def test_run_starts_and_stops_runtime_app(monkeypatch) -> None:
    """_run 会启动 RuntimeApp, 等待 shutdown, 然后停止 RuntimeApp."""

    from acabot import main as main_module

    started: list[str] = []
    stopped: list[str] = []

    class FakeApp:
        """用于 _run 测试的 fake app."""

        async def start(self) -> None:
            """记录 start 调用."""

            started.append("start")

        async def stop(self) -> None:
            """记录 stop 调用."""

            stopped.append("stop")

    monkeypatch.setattr(main_module, "load_dotenv", lambda: None)
    monkeypatch.setattr(main_module.Config, "from_file", classmethod(lambda cls: Config({})))
    monkeypatch.setattr(main_module, "setup_logging", lambda config: None)
    monkeypatch.setattr(
        main_module,
        "build_runtime_app",
        lambda config: _runtime_components_for_main_test(FakeApp()),
    )

    async def fake_wait_for_shutdown_signal() -> None:
        """让 _run 立即结束等待.

        Returns:
            无返回值.
        """

        return None

    monkeypatch.setattr(main_module, "wait_for_shutdown_signal", fake_wait_for_shutdown_signal)

    await main_module._run()

    assert started == ["start"]
    assert stopped == ["stop"]


def _runtime_components_for_main_test(app: Any) -> RuntimeComponents:
    """构造 `_run` 测试使用的最小 RuntimeComponents.

    Args:
        app: 需要被 `_run` 启停的 fake app.

    Returns:
        一份最小 RuntimeComponents.
    """

    skill_catalog = SkillCatalog()
    subagent_catalog = SubagentCatalog()
    sticky_note_store = StickyNoteFileStore(root_dir="/tmp/acabot-test-sticky-notes")

    return RuntimeComponents(
        gateway=FakeGateway(),
        router=None,  # type: ignore[arg-type]
        thread_manager=None,  # type: ignore[arg-type]
        run_manager=None,  # type: ignore[arg-type]
        channel_event_store=InMemoryChannelEventStore(),
        message_store=InMemoryMessageStore(),
        soul_source=SoulSource(root_dir="/tmp/acabot-test-soul"),
        sticky_notes_source=sticky_note_store,
        sticky_notes=StickyNoteService(
            store=sticky_note_store,
            renderer=StickyNoteRenderer(),
        ),
        skill_catalog=skill_catalog,
        subagent_catalog=subagent_catalog,
        subagent_delegator=SubagentDelegationBroker(
            default_agent_id="aca",
        ),
        subagent_execution_service=LocalSubagentExecutionService(
            thread_manager=None,  # type: ignore[arg-type]
            run_manager=None,  # type: ignore[arg-type]
            pipeline=None,  # type: ignore[arg-type]
            agent_loader=lambda decision: None,  # type: ignore[return-value]
        ),
        memory_broker=MemoryBroker(),
        context_compactor=ContextCompactor(ContextCompactionConfig()),
        retrieval_planner=RetrievalPlanner(),
        context_assembler=ContextAssembler(),
        payload_json_writer=PayloadJsonWriter(root_dir=Path("/tmp/acabot-test-payloads")),
        model_registry_manager=FileSystemModelRegistryManager(
            providers_dir="/tmp/acabot-test-models/providers",
            presets_dir="/tmp/acabot-test-models/presets",
            bindings_dir="/tmp/acabot-test-models/bindings",
        ),
        computer_runtime=ComputerRuntime(
            config=ComputerRuntimeConfig(
                root_dir="/tmp/acabot-test-computer",
                host_skills_catalog_root_path="/tmp/acabot-test-computer/catalog/skills",
            )
        ),
        image_context_service=None,  # type: ignore[arg-type]
        message_preparation_service=None,  # type: ignore[arg-type]
        reference_backend=NullReferenceBackend(),
        plugin_manager=None,  # type: ignore[arg-type]
        control_plane=None,  # type: ignore[arg-type]
        config_control_plane=None,  # type: ignore[arg-type]
        prompt_loader=None,  # type: ignore[arg-type]
        agent_loader=lambda decision: None,  # type: ignore[return-value]
        tool_broker=None,  # type: ignore[arg-type]
        agent_runtime=None,  # type: ignore[arg-type]
        approval_resumer=NoopApprovalResumer(),
        outbox=None,  # type: ignore[arg-type]
        pipeline=None,  # type: ignore[arg-type]
        backend_bridge=BackendBridge(session=BackendSessionService()),
        backend_mode_registry=BackendModeRegistry(),
        app=app,
    )


def test_runtime_components_fixture_matches_bootstrap_contract() -> None:
    components = _runtime_components_for_main_test(app=None)

    assert components.context_assembler is not None
    assert components.payload_json_writer is not None


async def test_wait_for_shutdown_signal_returns_when_event_is_set(monkeypatch) -> None:
    """wait_for_shutdown_signal 在 stop_event 被触发后返回."""

    from acabot import main as main_module

    class FakeEvent:
        """用于 wait_for_shutdown_signal 测试的 fake event."""

        def __init__(self) -> None:
            """初始化 fake event."""

            self.was_set = False

        def set(self) -> None:
            """模拟设置 event."""

            self.was_set = True

        async def wait(self) -> None:
            """模拟 wait 立即返回."""

            self.was_set = True

    class FakeLoop:
        """用于 wait_for_shutdown_signal 测试的 fake loop."""

        def __init__(self) -> None:
            """初始化 fake loop."""

            self.handlers: list[Any] = []

        def add_signal_handler(self, sig: Any, callback) -> None:
            """记录 signal handler 注册.

            Args:
                sig: signal 值.
                callback: 注册的回调函数.
            """

            self.handlers.append((sig, callback))

    fake_event = FakeEvent()
    fake_loop = FakeLoop()

    monkeypatch.setattr(main_module.asyncio, "Event", lambda: fake_event)
    monkeypatch.setattr(main_module.asyncio, "get_running_loop", lambda: fake_loop)

    await wait_for_shutdown_signal()

    assert fake_event.was_set is True
    assert len(fake_loop.handlers) == 2
