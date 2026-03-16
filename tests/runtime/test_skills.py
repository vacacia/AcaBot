from pathlib import Path

from acabot.agent import ToolSpec
from acabot.runtime import AgentProfile, SkillAssignment, SkillCatalog, ToolBroker
from acabot.runtime.skills import FileSystemSkillPackageLoader


def _fixtures_root() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "skills"


def _catalog() -> SkillCatalog:
    catalog = SkillCatalog(FileSystemSkillPackageLoader(_fixtures_root()))
    catalog.reload()
    return catalog


def _profile(*, assignments: list[SkillAssignment]) -> AgentProfile:
    return AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        skill_assignments=list(assignments),
    )


def test_skill_catalog_lists_fixture_skills() -> None:
    catalog = _catalog()

    assert [item.skill_name for item in catalog.list_all()] == [
        "excel_processing",
        "sample_configured_skill",
    ]


async def test_tool_broker_exposes_skill_tool_for_assigned_skills() -> None:
    catalog = _catalog()
    broker = ToolBroker(skill_catalog=catalog)
    broker.register_tool(
        ToolSpec(
            name="skill",
            description="placeholder",
            parameters={"type": "object", "properties": {"name": {"type": "string"}}},
        ),
        lambda arguments, ctx: {"ok": True},  # type: ignore[arg-type]
    )

    visible = broker.visible_tools(
        _profile(assignments=[SkillAssignment(skill_name="sample_configured_skill")])
    )

    assert [tool.name for tool in visible] == ["skill"]
    assert "sample_configured_skill" in visible[0].description


def test_skill_catalog_resolves_explicit_assignments() -> None:
    catalog = _catalog()

    resolved = catalog.resolve_assignments(
        _profile(
            assignments=[
                SkillAssignment(
                    skill_name="sample_configured_skill",
                    delegation_mode="prefer_delegate",
                    delegate_agent_id="excel_worker",
                )
            ]
        )
    )

    assert len(resolved) == 1
    assert resolved[0].skill.skill_name == "sample_configured_skill"
    assert resolved[0].assignment.delegation_mode == "prefer_delegate"
    assert resolved[0].assignment.delegate_agent_id == "excel_worker"
