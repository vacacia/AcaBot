from pathlib import Path

from acabot.runtime import AgentProfile, FileSystemSkillPackageLoader, SkillCatalog


def _fixtures_root() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "skills"


def _profile(skills: list[str]) -> AgentProfile:
    return AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        skills=skills,
    )


def test_skill_catalog_resolves_visible_skills_from_profile_skills() -> None:
    catalog = SkillCatalog(FileSystemSkillPackageLoader(_fixtures_root()))
    catalog.reload()

    visible = catalog.visible_skills(
        _profile(["sample_configured_skill", "excel_processing"])
    )

    assert [item.skill_name for item in visible] == [
        "sample_configured_skill",
        "excel_processing",
    ]


def test_skill_catalog_ignores_missing_skills() -> None:
    catalog = SkillCatalog(FileSystemSkillPackageLoader(_fixtures_root()))
    catalog.reload()

    visible = catalog.visible_skills(_profile(["missing_skill"]))

    assert visible == []


def test_skill_catalog_reads_package_document_on_demand() -> None:
    catalog = SkillCatalog(FileSystemSkillPackageLoader(_fixtures_root()))
    catalog.reload()

    document = catalog.read("sample_configured_skill")

    assert "Sample Configured Skill" in document.raw_markdown
