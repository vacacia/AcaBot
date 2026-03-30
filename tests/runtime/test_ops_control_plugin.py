from acabot.config import Config
from acabot.runtime import build_runtime_components
from acabot.types import EventSource, MsgSegment, StandardEvent

from ._agent_fakes import FakeAgent, FakeAgentResponse
from .test_outbox import FakeGateway


def _skills_dir() -> str:
    from pathlib import Path

    return str(Path(__file__).resolve().parent.parent / "fixtures" / "skills")


def _write_subagent(tmp_path, *, name: str, description: str) -> None:
    subagent_dir = tmp_path / ".agents" / "subagents" / name
    subagent_dir.mkdir(parents=True, exist_ok=True)
    (subagent_dir / "SUBAGENT.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "tools:",
                "  - sample_configured_tool",
                "---",
                f"You are {name}.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _message_event(text: str, *, event_id: str = "evt-1") -> StandardEvent:
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
        segments=[MsgSegment(type="text", data={"text": text})],
        raw_message_id=f"msg-{event_id}",
        sender_nickname="acacia",
        sender_role=None,
    )


def _ops_config(tmp_path) -> Config:
    _write_subagent(
        tmp_path,
        name="sample-worker",
        description="处理样例子任务的 catalog worker",
    )
    return Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_agent_name": "Aca",
                "default_prompt_ref": "prompt/aca",
                "filesystem": {
                    "enabled": True,
                    "base_dir": str(tmp_path),
                    "skill_catalog_dirs": [_skills_dir()],
                },
                "skills": ["sample_configured_skill"],
                "prompts": {
                    "prompt/aca": "You are Aca.",
                    "prompt/ops": "You are the operator agent.",
                },
                "plugins": [
                    "acabot.runtime.plugins:OpsControlPlugin",
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                ],
            },
            "plugins": {
                "ops_control": {
                    "allowed_actor_ids": ["qq:user:10001"],
                },
            },
        }
    )


async def test_ops_control_plugin_handles_status_command(tmp_path) -> None:
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not be used"))
    components = build_runtime_components(_ops_config(tmp_path), gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_message_event("/status"))

    assert agent.calls == []
    assert len(gateway.sent) == 1
    status_text = gateway.sent[0].payload["text"]
    assert "active_runs=1" in status_text
    assert "loaded_plugins=backend_bridge_tool,ops_control,sample_configured_runtime" in status_text
    loaded_skills_line = next(
        line for line in status_text.splitlines() if line.startswith("loaded_skills=")
    )
    assert "excel_processing" in loaded_skills_line
    assert "sample_configured_skill" in loaded_skills_line


async def test_ops_control_plugin_can_list_skills(tmp_path) -> None:
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not be used"))
    components = build_runtime_components(_ops_config(tmp_path), gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_message_event("/skills"))

    assert agent.calls == []
    assert len(gateway.sent) == 1
    assert "sample_configured_skill" in gateway.sent[0].payload["text"]


async def test_ops_control_plugin_can_list_agent_skills(tmp_path) -> None:
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not be used"))
    components = build_runtime_components(_ops_config(tmp_path), gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_message_event("/skills aca"))

    assert agent.calls == []
    assert len(gateway.sent) == 1
    assert "skills for aca:" in gateway.sent[0].payload["text"]
    assert "sample_configured_skill" in gateway.sent[0].payload["text"]
    assert "resources=" in gateway.sent[0].payload["text"]


async def test_ops_control_plugin_can_list_subagents(tmp_path) -> None:
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not be used"))
    components = build_runtime_components(_ops_config(tmp_path), gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_message_event("/subagents"))

    assert agent.calls == []
    assert len(gateway.sent) == 1
    assert "sample-worker" in gateway.sent[0].payload["text"]
    assert "catalog worker" in gateway.sent[0].payload["text"]



async def test_ops_control_plugin_reports_unknown_memory_command(tmp_path) -> None:
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not be used"))
    components = build_runtime_components(_ops_config(tmp_path), gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_message_event("/memory show user qq:user:10001 sticky_note"))

    assert agent.calls == []
    assert len(gateway.sent) == 1
    assert "unknown ops command: memory" in gateway.sent[0].payload["text"]


async def test_ops_control_plugin_can_reload_selected_plugin(tmp_path) -> None:
    from tests.runtime.runtime_plugin_samples import SampleConfiguredRuntimePlugin

    SampleConfiguredRuntimePlugin.reset()
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not be used"))
    components = build_runtime_components(_ops_config(tmp_path), gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_message_event("/reload_plugin sample_configured_runtime"))

    assert agent.calls == []
    assert len(gateway.sent) == 1
    assert "reloaded_plugins=sample_configured_runtime" in gateway.sent[0].payload["text"]
    assert SampleConfiguredRuntimePlugin.setup_calls == 2


async def test_ops_control_plugin_reports_missing_plugin_on_reload(tmp_path) -> None:
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not be used"))
    components = build_runtime_components(_ops_config(tmp_path), gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_message_event("/reload_plugin missing_plugin"))

    assert agent.calls == []
    assert len(gateway.sent) == 1
    assert "reloaded_plugins=-" in gateway.sent[0].payload["text"]
    assert "missing_plugins=missing_plugin" in gateway.sent[0].payload["text"]
