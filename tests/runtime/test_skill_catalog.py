from pathlib import Path

from acabot.runtime import (
    AgentProfile,
    FileSystemSkillPackageLoader,
    SkillAssignment,
    SkillCatalog,
)


def _fixtures_root() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "skills"


def _profile(assignments: list[SkillAssignment]) -> AgentProfile:
    return AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        skill_assignments=assignments,
    )


def test_skill_catalog_resolves_visible_skills_from_assignments() -> None:
    catalog = SkillCatalog(FileSystemSkillPackageLoader(_fixtures_root()))
    catalog.reload()

    visible = catalog.visible_skills(
        _profile(
            [
                SkillAssignment(skill_name="sample_configured_skill"),
                SkillAssignment(skill_name="excel_processing"),
            ]
        )
    )

    assert [item.skill_name for item in visible] == [
        "sample_configured_skill",
        "excel_processing",
    ]


def test_skill_catalog_ignores_missing_skills() -> None:
    catalog = SkillCatalog(FileSystemSkillPackageLoader(_fixtures_root()))
    catalog.reload()

    resolved = catalog.resolve_assignments(
        _profile([SkillAssignment(skill_name="missing_skill")])
    )

    assert resolved == []


def test_skill_catalog_reads_package_document_on_demand() -> None:
    catalog = SkillCatalog(FileSystemSkillPackageLoader(_fixtures_root()))
    catalog.reload()

    document = catalog.read("sample_configured_skill")

    assert "Sample Configured Skill" in document.raw_markdown
