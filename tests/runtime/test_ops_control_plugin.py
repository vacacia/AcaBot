from acabot.config import Config
from acabot.runtime import MemoryItem, build_runtime_components
from acabot.types import EventSource, MsgSegment, StandardEvent

from .test_bootstrap import FakeAgent, FakeAgentResponse
from .test_outbox import FakeGateway


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


def _ops_config() -> Config:
    return Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/aca",
                        "default_model": "model-a",
                    },
                    "ops": {
                        "name": "Ops",
                        "prompt_ref": "prompt/ops",
                        "default_model": "model-o",
                    },
                },
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


async def test_ops_control_plugin_handles_status_command() -> None:
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not be used"))
    components = build_runtime_components(_ops_config(), gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_message_event("/status"))

    assert agent.calls == []
    assert len(gateway.sent) == 1
    assert "active_runs=1" in gateway.sent[0].payload["text"]
    assert "loaded_plugins=ops_control" in gateway.sent[0].payload["text"]
    assert "loaded_skills=sample_configured_skill" in gateway.sent[0].payload["text"]


async def test_ops_control_plugin_can_list_skills() -> None:
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not be used"))
    components = build_runtime_components(_ops_config(), gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_message_event("/skills"))

    assert agent.calls == []
    assert len(gateway.sent) == 1
    assert "sample_configured_skill" in gateway.sent[0].payload["text"]


async def test_ops_control_plugin_can_switch_thread_agent() -> None:
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="hello from ops", model_used="model-o"))
    components = build_runtime_components(_ops_config(), gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_message_event("/switch_agent ops", event_id="evt-switch"))
    await gateway.handler(_message_event("hello", event_id="evt-normal"))

    assert gateway.sent[0].payload["text"] == "thread agent switched to ops"
    assert agent.calls[0]["system_prompt"] == "You are the operator agent."
    assert agent.calls[0]["model"] == "model-o"


async def test_ops_control_plugin_can_show_memory() -> None:
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not be used"))
    components = build_runtime_components(_ops_config(), gateway=gateway, agent=agent)
    await components.memory_store.upsert(
        MemoryItem(
            memory_id="mem:1",
            scope="user",
            scope_key="qq:user:10001",
            memory_type="sticky_note",
            content="用户名字叫阿卡西亚",
            edit_mode="readonly",
        )
    )

    components.app.install()
    await gateway.handler(_message_event("/memory show user qq:user:10001 sticky_note"))

    assert agent.calls == []
    assert len(gateway.sent) == 1
    assert "sticky_note/readonly: 用户名字叫阿卡西亚" in gateway.sent[0].payload["text"]


async def test_ops_control_plugin_can_reload_selected_plugin() -> None:
    from tests.runtime.runtime_plugin_samples import SampleConfiguredRuntimePlugin

    SampleConfiguredRuntimePlugin.reset()
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not be used"))
    components = build_runtime_components(_ops_config(), gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_message_event("/reload_plugin sample_configured_runtime"))

    assert agent.calls == []
    assert len(gateway.sent) == 1
    assert "reloaded_plugins=sample_configured_runtime" in gateway.sent[0].payload["text"]
    assert SampleConfiguredRuntimePlugin.setup_calls == 2


async def test_ops_control_plugin_reports_missing_plugin_on_reload() -> None:
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not be used"))
    components = build_runtime_components(_ops_config(), gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_message_event("/reload_plugin missing_plugin"))

    assert agent.calls == []
    assert len(gateway.sent) == 1
    assert "reloaded_plugins=-" in gateway.sent[0].payload["text"]
    assert "missing_plugins=missing_plugin" in gateway.sent[0].payload["text"]
