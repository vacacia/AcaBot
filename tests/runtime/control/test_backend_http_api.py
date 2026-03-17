"""backend control plane / HTTP API 的最小测试."""

from __future__ import annotations

from pathlib import Path

from acabot.config import Config
from acabot.runtime import (
    BackendBridge,
    BackendModeRegistry,
    BackendSessionBindingStore,
    BackendSessionService,
    InMemoryChannelEventStore,
    InMemoryRunManager,
    InMemoryThreadManager,
    Outbox,
    RuntimeApp,
    RuntimeControlPlane,
    RuntimeHttpApiServer,
    RuntimeRouter,
    ThreadPipeline,
    build_runtime_components,
)
from acabot.runtime.control.http_api import _to_jsonable

from tests.runtime.test_bootstrap import FakeAgent, FakeAgentResponse
from tests.runtime.test_control_plane import _profile_loader
from tests.runtime.test_outbox import FakeGateway, FakeMessageStore
from tests.runtime.test_pipeline_runtime import FakeAgentRuntime


def _build_control_plane(tmp_path: Path) -> RuntimeControlPlane:
    """构造带 backend 组件的最小 control plane."""

    binding_store = BackendSessionBindingStore(tmp_path / ".acabot-runtime" / "backend" / "session.json")
    session_service = BackendSessionService(binding_store)
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
        backend_bridge=BackendBridge(session=session_service),
        backend_mode_registry=BackendModeRegistry(),
        backend_admin_actor_ids={"qq:user:10001"},
    )
    return RuntimeControlPlane(
        app=app,
        run_manager=InMemoryRunManager(),
    )


async def test_backend_status_endpoint_returns_binding(tmp_path: Path) -> None:
    """control plane 应返回最小 backend status 快照."""

    control_plane = _build_control_plane(tmp_path)
    status = await control_plane.get_backend_status()

    assert status.configured is False
    assert status.admin_actor_ids == ["qq:user:10001"]
    assert status.session_binding is None
    assert status.session_path.endswith(".acabot-runtime/backend/session.json")
    assert status.active_modes == []


async def test_backend_http_api_payload_shape_matches_backend_endpoints(tmp_path: Path) -> None:
    """HTTP API backend endpoints 应返回约定的数据形状."""

    control_plane = _build_control_plane(tmp_path)

    status_payload = {
        "ok": True,
        "data": _to_jsonable(await control_plane.get_backend_status()),
    }
    assert status_payload["data"]["configured"] is False
    assert status_payload["data"]["session_path"].endswith(".acabot-runtime/backend/session.json")

    binding_payload = {
        "ok": True,
        "data": _to_jsonable(await control_plane.get_backend_session_binding()),
    }
    assert binding_payload["data"] is None

    path_payload = {
        "ok": True,
        "data": _to_jsonable({"path": await control_plane.get_backend_session_path()}),
    }
    assert path_payload["data"]["path"].endswith(".acabot-runtime/backend/session.json")


async def test_enabled_backend_control_plane_reports_configured_true(tmp_path: Path) -> None:
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
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    status = await components.control_plane.get_backend_status()

    assert status.configured is True
    assert status.admin_actor_ids == ["qq:user:10001"]
    assert status.session_path == str((tmp_path / ".acabot-runtime" / "backend" / "session.json").resolve())

    await components.backend_bridge.session.adapter.dispose()


async def test_invalid_backend_command_control_plane_reports_unconfigured(tmp_path: Path) -> None:
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
                    "pi_command": ["definitely-not-a-real-pi-binary"],
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    status = await components.control_plane.get_backend_status()

    assert status.configured is False
    assert status.session_path == str((tmp_path / ".acabot-runtime" / "backend" / "session.json").resolve())
