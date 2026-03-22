from pathlib import Path

from acabot.config import Config
from acabot.runtime import AgentProfile, ComputerPolicyDecision, ComputerRuntime, ComputerRuntimeConfig, SkillCatalog, ToolBroker
from acabot.runtime.builtin_tools.skills import BuiltinSkillToolSurface
from acabot.runtime.skills import FileSystemSkillPackageLoader

from .test_model_agent_runtime import _context


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


def _broker_with_builtin_skill_tool(tmp_path: Path) -> tuple[ToolBroker, ComputerRuntime]:
    catalog = _catalog()
    computer_runtime = _runtime(tmp_path)
    broker = ToolBroker(skill_catalog=catalog)
    BuiltinSkillToolSurface(
        skill_catalog=catalog,
        computer_runtime=computer_runtime,
    ).register(broker)
    return broker, computer_runtime


async def test_builtin_skill_tool_visible_when_profile_has_visible_skills(tmp_path: Path) -> None:
    broker, _ = _broker_with_builtin_skill_tool(tmp_path)

    visible = broker.visible_tools(
        AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            default_model="test-model",
            skills=[],
        )
    )
    assert [tool.name for tool in visible] == []

    visible = broker.visible_tools(
        AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            default_model="test-model",
            skills=["sample_configured_skill"],
        )
    )
    assert [tool.name for tool in visible] == ["skill"]
    assert "sample_configured_skill" in visible[0].description


async def test_builtin_skill_tool_reads_visible_skill_and_marks_loaded(tmp_path: Path) -> None:
    broker, computer_runtime = _broker_with_builtin_skill_tool(tmp_path)

    ctx = _context()
    ctx.profile = AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        skills=["sample_configured_skill"],
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


async def test_builtin_skill_tool_rejects_invisible_skill(tmp_path: Path) -> None:
    broker, _ = _broker_with_builtin_skill_tool(tmp_path)

    ctx = _context()
    ctx.profile = AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        skills=["excel_processing"],
    )
    result = await broker.execute(
        tool_name="skill",
        arguments={"name": "sample_configured_skill"},
        ctx=broker._build_execution_context(ctx),
    )

    assert result.raw["ok"] is False
    assert result.raw["reason"] == "skill_not_assigned"


async def test_builtin_skill_tool_respects_world_visible_skills(tmp_path: Path) -> None:
    broker, computer_runtime = _broker_with_builtin_skill_tool(tmp_path)

    ctx = _context()
    ctx.profile = AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        skills=["sample_configured_skill", "excel_processing"],
    )
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
        visible_skills=["sample_configured_skill"],
    )
    await computer_runtime.prepare_run_context(ctx)

    blocked = await broker.execute(
        tool_name="skill",
        arguments={"name": "excel_processing"},
        ctx=broker._build_execution_context(ctx),
    )
    allowed = await broker.execute(
        tool_name="skill",
        arguments={"name": "sample_configured_skill"},
        ctx=broker._build_execution_context(ctx),
    )

    assert blocked.raw["ok"] is False
    assert blocked.raw["reason"] == "skill_not_assigned"
    assert allowed.raw["ok"] is True
    assert allowed.raw["skill_name"] == "sample_configured_skill"


async def test_builtin_skill_tool_disappears_when_visible_skills_is_explicitly_empty(tmp_path: Path) -> None:
    broker, computer_runtime = _broker_with_builtin_skill_tool(tmp_path)

    ctx = _context()
    ctx.profile = AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        skills=["sample_configured_skill"],
    )
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
        visible_skills=[],
    )
    await computer_runtime.prepare_run_context(ctx)

    tool_runtime = broker.build_tool_runtime(ctx)
    result = await broker.execute(
        tool_name="skill",
        arguments={"name": "sample_configured_skill"},
        ctx=broker._build_execution_context(ctx),
    )

    assert "skill" not in [tool.name for tool in tool_runtime.tools]
    assert '"error": "Tool not enabled for current run: skill"' in str(result.llm_content)


async def test_builtin_skill_tool_disappears_when_skills_root_is_hidden(tmp_path: Path) -> None:
    broker, computer_runtime = _broker_with_builtin_skill_tool(tmp_path)

    ctx = _context()
    ctx.profile = AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        skills=["sample_configured_skill"],
    )
    ctx.computer_policy_decision = ComputerPolicyDecision(
        actor_kind="frontstage_agent",
        backend="host",
        allow_exec=True,
        allow_sessions=True,
        roots={
            "workspace": {"visible": True},
            "skills": {"visible": False},
            "self": {"visible": True},
        },
        visible_skills=["sample_configured_skill"],
    )
    await computer_runtime.prepare_run_context(ctx)

    tool_runtime = broker.build_tool_runtime(ctx)
    result = await broker.execute(
        tool_name="skill",
        arguments={"name": "sample_configured_skill"},
        ctx=broker._build_execution_context(ctx),
    )

    assert "skill" not in [tool.name for tool in tool_runtime.tools]
    assert '"error": "Tool not enabled for current run: skill"' in str(result.llm_content)
