from pathlib import Path

from acabot.agent import ToolSpec
from acabot.runtime import AgentProfile, SkillCatalog, ToolBroker
from acabot.runtime.skills import FileSystemSkillPackageLoader


def _fixtures_root() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "skills"


def _catalog() -> SkillCatalog:
    catalog = SkillCatalog(FileSystemSkillPackageLoader(_fixtures_root()))
    catalog.reload()
    return catalog


def _profile(*, skills: list[str]) -> AgentProfile:
    return AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        skills=list(skills),
    )


def test_skill_catalog_lists_fixture_skills() -> None:
    catalog = _catalog()

    assert [item.skill_name for item in catalog.list_all()] == [
        "excel_processing",
        "sample_configured_skill",
    ]


async def test_tool_broker_exposes_skill_tool_for_visible_skills() -> None:
    catalog = _catalog()
    broker = ToolBroker(skill_catalog=catalog)
    broker.register_tool(
        ToolSpec(
            name="Skill",
            description="placeholder",
            parameters={"type": "object", "properties": {"skill": {"type": "string"}}},
        ),
        lambda arguments, ctx: {"ok": True},  # type: ignore[arg-type]
    )

    visible = broker.visible_tools(_profile(skills=["sample_configured_skill"]))

    assert [tool.name for tool in visible] == ["Skill"]
    assert "sample_configured_skill" in visible[0].description


def test_skill_catalog_resolves_visible_skills_from_profile() -> None:
    catalog = _catalog()

    visible = catalog.visible_skills(_profile(skills=["sample_configured_skill"]))

    assert len(visible) == 1
    assert visible[0].skill_name == "sample_configured_skill"
