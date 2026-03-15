from pathlib import Path

from acabot.config import Config
from acabot.runtime import (
    AgentProfile,
    ComputerRuntime,
    ComputerRuntimeConfig,
    FileSystemSkillPackageLoader,
    RuntimePluginManager,
    SkillAssignment,
    SkillCatalog,
    SkillToolPlugin,
    ToolBroker,
)

from .test_model_agent_runtime import _context
from .test_outbox import FakeGateway


def _fixtures_root() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "skills"


def _catalog() -> SkillCatalog:
    catalog = SkillCatalog(FileSystemSkillPackageLoader(_fixtures_root()))
    catalog.reload()
    return catalog


def _runtime(tmp_path: Path) -> ComputerRuntime:
    return ComputerRuntime(
        config=ComputerRuntimeConfig(
            root_dir=str(tmp_path / "computer"),
            skill_catalog_dir=str(_fixtures_root()),
        )
    )


async def test_skill_tool_visible_when_profile_has_assigned_skills(tmp_path: Path) -> None:
    catalog = _catalog()
    broker = ToolBroker(skill_catalog=catalog)
    manager = RuntimePluginManager(
        config=Config({}),
        gateway=FakeGateway(),
        tool_broker=broker,
        computer_runtime=_runtime(tmp_path),
        skill_catalog=catalog,
        plugins=[SkillToolPlugin()],
    )
    await manager.ensure_started()

    visible = broker.visible_tools(
        AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            default_model="test-model",
            skill_assignments=[],
        )
    )
    assert [tool.name for tool in visible] == []

    visible = broker.visible_tools(
        AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            default_model="test-model",
            skill_assignments=[SkillAssignment(skill_name="sample_configured_skill")],
        )
    )
    assert [tool.name for tool in visible] == ["skill"]
    assert "sample_configured_skill" in visible[0].description


async def test_skill_tool_reads_assigned_skill_and_marks_loaded(tmp_path: Path) -> None:
    catalog = _catalog()
    computer_runtime = _runtime(tmp_path)
    broker = ToolBroker(skill_catalog=catalog)
    manager = RuntimePluginManager(
        config=Config({}),
        gateway=FakeGateway(),
        tool_broker=broker,
        computer_runtime=computer_runtime,
        skill_catalog=catalog,
        plugins=[SkillToolPlugin()],
    )
    await manager.ensure_started()

    ctx = _context()
    ctx.profile = AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        skill_assignments=[SkillAssignment(skill_name="sample_configured_skill")],
    )
    execution_ctx = broker._build_execution_context(ctx)

    result = await broker.execute(
        tool_name="skill",
        arguments={"name": "sample_configured_skill"},
        ctx=execution_ctx,
    )

    assert "Sample Configured Skill" in str(result.llm_content)
    assert result.raw["skill_name"] == "sample_configured_skill"
    assert computer_runtime.list_loaded_skills(ctx.thread.thread_id) == [
        "sample_configured_skill"
    ]


async def test_skill_tool_rejects_unassigned_skill(tmp_path: Path) -> None:
    catalog = _catalog()
    broker = ToolBroker(skill_catalog=catalog)
    manager = RuntimePluginManager(
        config=Config({}),
        gateway=FakeGateway(),
        tool_broker=broker,
        computer_runtime=_runtime(tmp_path),
        skill_catalog=catalog,
        plugins=[SkillToolPlugin()],
    )
    await manager.ensure_started()

    ctx = _context()
    ctx.profile = AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        skill_assignments=[SkillAssignment(skill_name="excel_processing")],
    )
    result = await broker.execute(
        tool_name="skill",
        arguments={"name": "sample_configured_skill"},
        ctx=broker._build_execution_context(ctx),
    )

    assert result.raw["ok"] is False
    assert result.raw["reason"] == "skill_not_assigned"
