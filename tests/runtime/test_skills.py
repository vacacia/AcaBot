from acabot.config import Config
from acabot.runtime import AgentProfile, SkillRegistry, ToolBroker
from acabot.runtime.plugin_manager import RuntimePluginManager

from .test_outbox import FakeGateway


def _profile(*, enabled_skills: list[str]) -> AgentProfile:
    return AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        enabled_skills=enabled_skills,
    )


async def test_skill_registry_registers_and_unregisters_by_source() -> None:
    from tests.runtime.runtime_plugin_samples import SampleConfiguredRuntimePlugin

    registry = SkillRegistry()
    broker = ToolBroker(skill_registry=registry)
    manager = RuntimePluginManager(
        config=Config({}),
        gateway=FakeGateway(),
        tool_broker=broker,
        skill_registry=registry,
        plugins=[SampleConfiguredRuntimePlugin()],
    )

    await manager.ensure_started()
    before = registry.list_all()
    removed = registry.unregister_source("plugin:sample_configured_runtime")
    after = registry.list_all()

    assert [item.spec.skill_name for item in before] == ["sample_configured_skill"]
    assert removed == ["sample_configured_skill"]
    assert after == []


async def test_tool_broker_expands_tools_from_enabled_skills() -> None:
    from tests.runtime.runtime_plugin_samples import SampleConfiguredRuntimePlugin

    registry = SkillRegistry()
    broker = ToolBroker(skill_registry=registry)
    manager = RuntimePluginManager(
        config=Config({}),
        gateway=FakeGateway(),
        tool_broker=broker,
        skill_registry=registry,
        plugins=[SampleConfiguredRuntimePlugin()],
    )
    await manager.ensure_started()

    visible = broker.visible_tools(_profile(enabled_skills=["sample_configured_skill"]))

    assert [tool.name for tool in visible] == ["sample_configured_tool"]
