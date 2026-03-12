from acabot.config import Config
from acabot.runtime import AgentProfile, SkillAssignment, SkillRegistry, ToolBroker
from acabot.runtime.plugin_manager import RuntimePluginManager

from .test_outbox import FakeGateway


def _profile(
    *,
    enabled_skills: list[str],
    skill_assignments: list[SkillAssignment] | None = None,
) -> AgentProfile:
    return AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        enabled_skills=enabled_skills,
        skill_assignments=list(skill_assignments or []),
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


async def test_skill_registry_resolves_explicit_assignments() -> None:
    from tests.runtime.runtime_plugin_samples import SampleConfiguredRuntimePlugin

    registry = SkillRegistry()
    manager = RuntimePluginManager(
        config=Config({}),
        gateway=FakeGateway(),
        tool_broker=ToolBroker(skill_registry=registry),
        skill_registry=registry,
        plugins=[SampleConfiguredRuntimePlugin()],
    )
    await manager.ensure_started()

    resolved = registry.resolve_assignments(
        _profile(
            enabled_skills=[],
            skill_assignments=[
                SkillAssignment(
                    skill_name="sample_configured_skill",
                    delegation_mode="prefer_delegate",
                    delegate_agent_id="excel_worker",
                )
            ],
        )
    )

    assert len(resolved) == 1
    assert resolved[0].registered.spec.skill_name == "sample_configured_skill"
    assert resolved[0].assignment.delegation_mode == "prefer_delegate"
    assert resolved[0].assignment.delegate_agent_id == "excel_worker"
