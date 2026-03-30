from pathlib import Path

from acabot.config import Config
from acabot.runtime import build_runtime_components
from acabot.runtime.app import RuntimeApp
from acabot.runtime.backend.contracts import BackendRequest
from acabot.runtime.backend.mode_registry import BackendModeRegistry
from acabot.runtime.contracts import AgentProfile, RouteDecision
from acabot.runtime.router import RuntimeRouter
from acabot.runtime.storage.event_store import InMemoryChannelEventStore
from acabot.runtime.storage.runs import InMemoryRunManager
from acabot.runtime.storage.threads import InMemoryThreadManager
from acabot.types import ActionType, EventSource, MsgSegment, StandardEvent

from ._agent_fakes import FakeAgent, FakeAgentResponse
from .test_outbox import FakeGateway


class _ConfiguredSession:
    def is_configured(self) -> bool:
        return True


class TrackingPipeline:
    def __init__(self) -> None:
        self.execute_calls: list[object] = []

    async def execute(self, ctx) -> None:
        self.execute_calls.append(ctx)


class FakeBackendBridge:
    def __init__(self, result: object | None = None) -> None:
        self.admin_requests: list[BackendRequest] = []
        self.session = _ConfiguredSession()
        self.result = {"ok": True} if result is None else result

    async def handle_admin_direct(self, request: BackendRequest) -> object:
        self.admin_requests.append(request)
        return self.result

    async def handle_frontstage_request(self, request: BackendRequest) -> object:
        raise AssertionError("frontstage bridge should not be used in task 6")


def _profile_loader(decision: RouteDecision) -> AgentProfile:
    return AgentProfile(
        agent_id=decision.agent_id,
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
    )


def _event(*, user_id: str, text: str) -> StandardEvent:
    return StandardEvent(
        event_id=f"evt-{user_id}-{text}",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="private",
            user_id=user_id,
            group_id=None,
        ),
        segments=[MsgSegment(type="text", data={"text": text})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role=None,
    )


def _build_app(
    *,
    backend_bridge: FakeBackendBridge,
    backend_mode_registry: BackendModeRegistry,
    backend_admin_actor_ids: set[str],
) -> tuple[RuntimeApp, TrackingPipeline]:
    gateway = FakeGateway()
    pipeline = TrackingPipeline()
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="aca"),
        thread_manager=InMemoryThreadManager(),
        run_manager=InMemoryRunManager(),
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=pipeline,
        profile_loader=_profile_loader,
        backend_bridge=backend_bridge,
        backend_mode_registry=backend_mode_registry,
        backend_admin_actor_ids=backend_admin_actor_ids,
    )
    return app, pipeline


async def test_admin_bang_message_routes_to_backend() -> None:
    backend_bridge = FakeBackendBridge(result={"text": "backend says hi"})
    backend_mode_registry = BackendModeRegistry()
    app, pipeline = _build_app(
        backend_bridge=backend_bridge,
        backend_mode_registry=backend_mode_registry,
        backend_admin_actor_ids={"qq:user:10001"},
    )

    await app.handle_event(_event(user_id="10001", text="!查询当前配置"))

    assert len(backend_bridge.admin_requests) == 1
    request = backend_bridge.admin_requests[0]
    assert request.source_kind == "admin_direct"
    assert request.request_kind == "change"
    assert request.summary == "查询当前配置"
    assert pipeline.execute_calls == []
    assert len(app.gateway.sent) == 1
    assert app.gateway.sent[0].action_type == ActionType.SEND_TEXT
    assert app.gateway.sent[0].payload["text"] == "backend says hi"
    assert app.gateway.sent[0].target.user_id == "10001"


async def test_admin_private_maintain_mode_routes_followup_messages_to_backend() -> None:
    backend_bridge = FakeBackendBridge(result={"text": "maintain reply"})
    backend_mode_registry = BackendModeRegistry()
    app, pipeline = _build_app(
        backend_bridge=backend_bridge,
        backend_mode_registry=backend_mode_registry,
        backend_admin_actor_ids={"qq:user:10001"},
    )

    await app.handle_event(_event(user_id="10001", text="/maintain"))

    assert backend_mode_registry.is_backend_mode("qq:user:10001") is True
    assert backend_bridge.admin_requests == []
    assert pipeline.execute_calls == []

    await app.handle_event(_event(user_id="10001", text="继续检查配置"))

    assert len(backend_bridge.admin_requests) == 1
    request = backend_bridge.admin_requests[0]
    assert request.summary == "继续检查配置"
    assert request.request_kind == "change"
    assert pipeline.execute_calls == []
    assert len(app.gateway.sent) == 1
    assert app.gateway.sent[0].action_type == ActionType.SEND_TEXT
    assert app.gateway.sent[0].payload["text"] == "maintain reply"
    assert app.gateway.sent[0].target.user_id == "10001"


async def test_admin_private_maintain_exit_exits_backend_mode() -> None:
    backend_bridge = FakeBackendBridge()
    backend_mode_registry = BackendModeRegistry()
    app, pipeline = _build_app(
        backend_bridge=backend_bridge,
        backend_mode_registry=backend_mode_registry,
        backend_admin_actor_ids={"qq:user:10001"},
    )

    await app.handle_event(_event(user_id="10001", text="/maintain"))
    assert backend_mode_registry.is_backend_mode("qq:user:10001") is True

    await app.handle_event(_event(user_id="10001", text="/maintain exit"))

    assert backend_mode_registry.is_backend_mode("qq:user:10001") is False
    assert backend_bridge.admin_requests == []
    assert pipeline.execute_calls == []


async def test_non_admin_message_still_goes_to_pipeline() -> None:
    backend_bridge = FakeBackendBridge()
    backend_mode_registry = BackendModeRegistry()
    app, pipeline = _build_app(
        backend_bridge=backend_bridge,
        backend_mode_registry=backend_mode_registry,
        backend_admin_actor_ids={"qq:user:10001"},
    )

    await app.handle_event(_event(user_id="20002", text="普通私聊消息"))

    assert backend_bridge.admin_requests == []
    assert len(pipeline.execute_calls) == 1


async def test_build_runtime_components_enabled_backend_admin_bang_routes_to_real_backend(
    tmp_path: Path,
) -> None:
    gateway = FakeGateway()
    config = Config(
        {
            "agent": {
                "default_model": "fallback-model",
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "runtime_root": str(tmp_path / ".acabot-runtime"),
                "backend": {
                    "enabled": True,
                    "admin_actor_ids": ["qq:user:10001"],
                    "session_binding_path": "backend/session.json",
                    "pi_command": ["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
                },
            },
        }
    )
    components = build_runtime_components(
        config,
        gateway=gateway,
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await components.plugin_manager.ensure_started()
    components.app.install()

    await gateway.handler(_event(user_id="10001", text="!Reply with exactly: ADMIN_BANG_OK"))

    binding = components.backend_bridge.session.load_binding()
    assert components.backend_bridge.session.is_configured() is True
    assert binding is not None
    assert binding.session_file.endswith(".jsonl")

    await components.backend_bridge.session.adapter.dispose()


async def test_build_runtime_components_enabled_backend_maintain_followup_routes_to_real_backend(
    tmp_path: Path,
) -> None:
    gateway = FakeGateway()
    config = Config(
        {
            "agent": {
                "default_model": "fallback-model",
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "runtime_root": str(tmp_path / ".acabot-runtime"),
                "backend": {
                    "enabled": True,
                    "admin_actor_ids": ["qq:user:10001"],
                    "session_binding_path": "backend/session.json",
                    "pi_command": ["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
                },
            },
        }
    )
    components = build_runtime_components(
        config,
        gateway=gateway,
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await components.plugin_manager.ensure_started()
    components.app.install()

    await gateway.handler(_event(user_id="10001", text="/maintain"))
    assert components.backend_mode_registry.is_backend_mode("qq:user:10001") is True

    await gateway.handler(
        _event(user_id="10001", text="Reply with exactly: MAINTAIN_FOLLOWUP_OK")
    )

    binding = components.backend_bridge.session.load_binding()
    assert binding is not None
    assert binding.session_file.endswith(".jsonl")

    await gateway.handler(_event(user_id="10001", text="/maintain exit"))
    assert components.backend_mode_registry.is_backend_mode("qq:user:10001") is False

    await components.backend_bridge.session.adapter.dispose()
