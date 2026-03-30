from pathlib import Path

from acabot.config import Config
from acabot.runtime import ResolvedAgent, FileSystemSkillPackageLoader, SkillCatalog
from acabot.runtime.bootstrap.builders import build_skill_catalog


def _fixtures_root() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "skills"


def _profile(skills: list[str]) -> ResolvedAgent:
    return ResolvedAgent(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        skills=skills,
    )


def _write_skill_package(
    root_dir: Path,
    relative_dir: str,
    *,
    name: str,
    description: str,
    body: str,
) -> None:
    skill_dir = root_dir / relative_dir
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                body,
                "",
            ]
        ),
        encoding="utf-8",
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


def test_skill_catalog_keeps_all_candidates_but_resolves_visible_skill_by_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_dir = tmp_path / "project"
    home_dir = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_dir))

    _write_skill_package(
        project_dir / ".agents" / "skills",
        "shared",
        name="shared",
        description="项目版本。",
        body="# Project Shared Skill",
    )
    _write_skill_package(
        home_dir / ".agents" / "skills",
        "shared",
        name="shared",
        description="全局版本。",
        body="# Global Shared Skill",
    )

    catalog = build_skill_catalog(
        Config(
            {
                "runtime": {
                    "filesystem": {
                        "enabled": True,
                    }
                }
            },
            path=str(project_dir / "config.yaml"),
        )
    )

    assert [
        (item.skill_name, item.scope)
        for item in catalog.list_all()
    ] == [
        ("shared", "project"),
        ("shared", "user"),
    ]
    visible = catalog.visible_skills(_profile(["shared"]))

    assert [(item.skill_name, item.scope) for item in visible] == [
        ("shared", "project")
    ]
