from pathlib import Path

import pytest

from acabot.runtime import (
    AgentProfile,
    ComputerPolicy,
    ComputerPolicyDecision,
    ComputerRuntime,
    ComputerRuntimeConfig,
    DockerSandboxBackend,
    RouteDecision,
    RunContext,
    RunRecord,
    ThreadState,
)
from acabot.types import EventAttachment, EventSource, MsgSegment, StandardEvent


def _ctx(tmp_path: Path) -> tuple[ComputerRuntime, RunContext]:
    service = ComputerRuntime(
        config=ComputerRuntimeConfig(
            root_dir=str(tmp_path / "workspaces"),
            skill_catalog_dir=str(tmp_path / "workspaces/catalog/skills"),
        )
    )
    event = StandardEvent(
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
    ctx = RunContext(
        run=RunRecord(
            run_id="run:1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            trigger_event_id="evt-1",
            status="queued",
            started_at=123,
        ),
        event=event,
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
        thread=ThreadState(
            thread_id="qq:user:10001",
            channel_scope="qq:user:10001",
        ),
        profile=AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            default_model="test-model",
            computer_policy=ComputerPolicy(),
            config={},
            skills=[],
        ),
        computer_policy_decision=ComputerPolicyDecision(
            actor_kind="frontstage_agent",
            backend="host",
            allow_exec=True,
            allow_sessions=True,
            roots={
                "workspace": {"visible": True},
                "skills": {"visible": True},
                "self": {"visible": True},
            },
            visible_skills=None,
        ),
    )
    return service, ctx


async def test_computer_runtime_prepares_workspace_state(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)

    await service.prepare_run_context(ctx)

    assert ctx.workspace_state is not None
    assert ctx.workspace_state.backend_kind == "host"
    assert ctx.workspace_state.workspace_visible_root == "/workspace"
    assert Path(ctx.workspace_state.workspace_host_path).exists()
    assert ctx.world_view is not None
    assert ctx.world_view.resolve("/workspace").world_path == "/workspace"
    assert ctx.world_view.execution_view.workspace_path == ctx.workspace_state.workspace_host_path


async def test_computer_runtime_stages_file_url_attachments(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    source_file = tmp_path / "source.txt"
    source_file.write_text("hello attachment", encoding="utf-8")
    ctx.event.attachments = [
        EventAttachment(
            type="file",
            source=source_file.resolve().as_uri(),
            name="source.txt",
        )
    ]

    await service.prepare_run_context(ctx)

    assert len(ctx.attachment_snapshots) == 1
    assert ctx.attachment_snapshots[0].download_status == "staged"
    assert Path(ctx.attachment_snapshots[0].staged_path).read_text(encoding="utf-8") == "hello attachment"
    assert ctx.attachment_snapshots[0].metadata["world_path"].startswith("/workspace/attachments/inbound/evt-1/")


async def test_computer_runtime_supports_exec_and_shell_session(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    policy = ctx.computer_policy_effective
    assert policy is not None

    exec_result = await service.exec_once(
        thread_id=ctx.thread.thread_id,
        command="printf 'hello world'",
        policy=policy,
        world_view=ctx.world_view,
    )
    session = await service.open_session(
        thread_id=ctx.thread.thread_id,
        agent_id=ctx.profile.agent_id,
        policy=policy,
        world_view=ctx.world_view,
    )
    await service.write_session(
        thread_id=ctx.thread.thread_id,
        session_id=session.session_id,
        command="printf 'session output'\n",
    )
    await service.write_session(
        thread_id=ctx.thread.thread_id,
        session_id=session.session_id,
        command="exit\n",
    )
    await service.close_session(
        thread_id=ctx.thread.thread_id,
        session_id=session.session_id,
    )

    assert exec_result.ok is True
    assert "hello world" in exec_result.stdout_excerpt
    assert session.cwd_visible == ctx.world_view.execution_view.workspace_path


async def test_computer_runtime_world_view_respects_decision_visible_skills(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    ctx.profile.skills = ["profile_skill"]
    ctx.computer_policy_decision = ComputerPolicyDecision(
        actor_kind="frontstage_agent",
        backend="host",
        allow_exec=True,
        allow_sessions=True,
        roots={
            "workspace": {"visible": True},
            "skills": {"visible": True},
            "self": {"visible": True},
        },
        visible_skills=["decision_skill"],
    )
    shared_skills = service.workspace_manager.ensure_skills_layout(ctx.thread.thread_id)
    (shared_skills / "decision_skill").mkdir(parents=True, exist_ok=True)
    (shared_skills / "decision_skill" / "SKILL.md").write_text("decision", encoding="utf-8")
    (shared_skills / "profile_skill").mkdir(parents=True, exist_ok=True)
    (shared_skills / "profile_skill" / "SKILL.md").write_text("profile", encoding="utf-8")

    await service.prepare_run_context(ctx)

    assert ctx.world_view is not None
    assert ctx.world_view.resolve("/skills/decision_skill/SKILL.md").root_kind == "skills"
    try:
        ctx.world_view.resolve("/skills/profile_skill/SKILL.md")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("profile-level skill should not leak into world view")


async def test_computer_runtime_refreshes_skills_world_view_after_mirroring(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    ctx.profile.skills = ["sample_skill"]
    source_skill = tmp_path / "catalog" / "sample_skill"
    source_skill.mkdir(parents=True, exist_ok=True)
    (source_skill / "SKILL.md").write_text("sample skill", encoding="utf-8")

    class Catalog:
        def get(self, skill_name: str):
            if skill_name != "sample_skill":
                return None
            return type("Manifest", (), {"root_dir": source_skill})()

    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    with pytest.raises(FileNotFoundError):
        ctx.world_view.resolve("/skills/sample_skill/SKILL.md")

    service.mark_skill_loaded(ctx.thread.thread_id, "sample_skill")
    await service.ensure_loaded_skills_mirrored(
        ctx.thread.thread_id,
        Catalog(),
        world_view=ctx.world_view,
    )

    resolved = ctx.world_view.resolve("/skills/sample_skill/SKILL.md")
    assert Path(resolved.host_path).read_text(encoding="utf-8") == "sample skill"


async def test_computer_runtime_hides_shell_tools_when_workspace_is_not_visible(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    ctx.computer_policy_decision = ComputerPolicyDecision(
        actor_kind="frontstage_agent",
        backend="host",
        allow_exec=True,
        allow_sessions=True,
        roots={
            "workspace": {"visible": False},
            "skills": {"visible": True},
            "self": {"visible": True},
        },
        visible_skills=None,
    )

    await service.prepare_run_context(ctx)

    assert ctx.workspace_state is not None
    assert "exec" not in ctx.workspace_state.available_tools
    assert "bash_open" not in ctx.workspace_state.available_tools


async def test_computer_runtime_resolves_platform_file_id_via_gateway_api(tmp_path: Path) -> None:
    source_file = tmp_path / "resolved.txt"
    source_file.write_text("resolved from gateway api", encoding="utf-8")

    class Gateway:
        async def call_api(self, action: str, params: dict[str, object]):
            assert action in {"get_file", "get_group_file_url"}
            assert params["file_id"] == "file-123"
            return {
                "status": "ok",
                "data": {
                    "url": source_file.resolve().as_uri(),
                },
            }

    service, ctx = _ctx(tmp_path)
    service.gateway = Gateway()
    ctx.event.attachments = [
        EventAttachment(
            type="file",
            source="file-123",
            name="resolved.txt",
            metadata={"id": "file-123"},
        )
    ]

    await service.prepare_run_context(ctx)

    assert len(ctx.attachment_snapshots) == 1
    assert ctx.attachment_snapshots[0].download_status == "staged"
    assert ctx.attachment_snapshots[0].source_kind == "platform_api_resolved"
    assert Path(ctx.attachment_snapshots[0].staged_path).read_text(encoding="utf-8") == "resolved from gateway api"


async def test_docker_backend_reports_status_from_known_container() -> None:
    backend = DockerSandboxBackend(
        image="python:3.12-slim",
        stdout_window_bytes=1024,
        stderr_window_bytes=1024,
        network_mode="bridge",
    )
    backend._containers["qq:user:10001"] = "container-123"

    status = await backend.get_sandbox_status(
        thread_id="qq:user:10001",
        host_path=Path("/tmp/workspace"),
    )

    assert status.active is True
    assert status.container_id == "container-123"
