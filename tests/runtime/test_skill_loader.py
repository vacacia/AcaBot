from pathlib import Path

import pytest

from acabot.config import Config
from acabot.runtime import (
    ResolvedAgent,
    FileSystemSkillPackageLoader,
    SkillPackageFormatError,
)
from acabot.runtime.bootstrap.builders import build_skill_catalog


def _fixtures_root() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "skills"


def _write_skill_package(
    root_dir: Path,
    relative_dir: str,
    *,
    name: str,
    description: str,
    body: str,
    argument_hint: str = "",
    disable_model_invocation: bool | None = None,
) -> None:
    skill_dir = root_dir / relative_dir
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if argument_hint:
        lines.append(f"argument-hint: {argument_hint}")
    if disable_model_invocation is not None:
        lines.append(
            f"disable-model-invocation: {'true' if disable_model_invocation else 'false'}"
        )
    lines.extend(["---", "", body, ""])
    skill_dir.joinpath("SKILL.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


# region direct loader

def test_skill_loader_discovers_valid_packages_and_skips_invalid() -> None:
    loader = FileSystemSkillPackageLoader(_fixtures_root())

    manifests = loader.discover()

    assert [item.skill_name for item in manifests] == [
        "excel_processing",
        "sample_configured_skill",
    ]


def test_skill_loader_reads_manifest_metadata() -> None:
    loader = FileSystemSkillPackageLoader(_fixtures_root())

    manifest = loader.read_manifest("sample_configured_skill")

    assert manifest.skill_name == "sample_configured_skill"
    assert manifest.scope == "project"
    assert manifest.description == "用于测试 skill-first catalog 的样例 skill."
    assert manifest.host_skill_file_path.endswith("sample_configured_skill/SKILL.md")
    assert manifest.host_skill_root_path.endswith("sample_configured_skill")
    assert manifest.display_name == "Sample Configured Skill"
    assert manifest.has_references is True
    assert manifest.has_scripts is True
    assert manifest.has_assets is True
    assert manifest.metadata["category"] == "sample"


def test_skill_loader_reads_argument_hint_and_disable_model_invocation_fields(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    _write_skill_package(
        skills_root,
        "planner",
        name="planner",
        description="带额外参数提示的测试 skill.",
        body="# Planner",
        argument_hint="when task is planning-heavy",
        disable_model_invocation=True,
    )

    loader = FileSystemSkillPackageLoader(skills_root)
    manifest = loader.discover()[0]

    assert manifest.argument_hint == "when task is planning-heavy"
    assert manifest.disable_model_invocation is True


def test_skill_loader_reads_full_skill_document() -> None:
    loader = FileSystemSkillPackageLoader(_fixtures_root())

    document = loader.read_document("excel_processing")

    assert document.manifest.skill_name == "excel_processing"
    assert document.raw_markdown.startswith("---\n")
    assert "# Excel Processing" in document.body_markdown


def test_skill_loader_rejects_invalid_skill_on_direct_read() -> None:
    loader = FileSystemSkillPackageLoader(_fixtures_root())

    with pytest.raises(SkillPackageFormatError):
        loader.read_manifest("invalid_missing_description")


def test_skill_loader_discovers_nested_skill_packages_using_colon_names(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    _write_skill_package(
        skills_root,
        "frontend/design",
        name="Frontend Design",
        description="处理前端设计任务的测试 skill.",
        body="# Frontend Design",
    )

    loader = FileSystemSkillPackageLoader(skills_root)
    manifests = loader.discover()

    assert [item.skill_name for item in manifests] == ["frontend:design"]
    assert manifests[0].display_name == "Frontend Design"


def test_skill_loader_falls_back_to_relative_dir_name_when_frontmatter_name_is_missing(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "ops" / "debug"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "description: 调试任务的测试 skill.",
                "---",
                "",
                "# Debug Skill",
                "",
            ]
        ),
        encoding="utf-8",
    )

    loader = FileSystemSkillPackageLoader(skills_root)
    manifests = loader.discover()

    assert [item.skill_name for item in manifests] == ["ops:debug"]
    assert manifests[0].display_name == "ops:debug"


# endregion


# region catalog bootstrap

def test_build_skill_catalog_scans_all_project_and_user_skill_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    _write_skill_package(
        home_dir / ".agents" / "skills",
        "global_only",
        name="global_only",
        description="只在全局里存在的 skill。",
        body="# Global Only Skill",
    )

    config = Config(
        {
            "runtime": {
                "filesystem": {
                    "skill_catalog_dirs": [
                        "./.agents/skills",
                        "~/.agents/skills",
                    ],
                }
            }
        },
        path=str(project_dir / "config.yaml"),
    )

    catalog = build_skill_catalog(config)

    assert [
        (item.skill_name, item.scope)
        for item in catalog.list_all()
    ] == [
        ("global_only", "user"),
        ("shared", "project"),
        ("shared", "user"),
    ]


def test_build_skill_catalog_visible_skills_prefers_project_scope_for_duplicate_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    home_dir = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_dir))

    _write_skill_package(
        project_dir / ".agents" / "skills",
        "shared",
        name="shared",
        description="项目版本应该被模型看见。",
        body="# Project Shared Skill",
    )
    _write_skill_package(
        home_dir / ".agents" / "skills",
        "shared",
        name="shared",
        description="全局版本不该覆盖项目版本。",
        body="# Global Shared Skill",
    )
    _write_skill_package(
        home_dir / ".agents" / "skills",
        "global_only",
        name="global_only",
        description="只在全局里存在的 skill。",
        body="# Global Only Skill",
    )

    config = Config(
        {
            "runtime": {
                "filesystem": {
                    "skill_catalog_dirs": [
                        "./.agents/skills",
                        "~/.agents/skills",
                    ],
                }
            }
        },
        path=str(project_dir / "config.yaml"),
    )

    catalog = build_skill_catalog(config)
    visible = catalog.visible_skills(
        ResolvedAgent(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            skills=["shared", "global_only"],
        )
    )

    assert [
        (item.skill_name, item.scope)
        for item in visible
    ] == [
        ("shared", "project"),
        ("global_only", "user"),
    ]
    shared = catalog.read("shared")
    assert "Project Shared Skill" in shared.raw_markdown
    assert "Global Shared Skill" not in shared.raw_markdown


def test_build_skill_catalog_honors_runtime_filesystem_base_dir_for_default_skill_root(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    runtime_config_dir = project_dir / "runtime_config"

    _write_skill_package(
        runtime_config_dir / "extensions" / "skills",
        "renderkit",
        name="renderkit",
        description="来自 runtime_config 的 skill。",
        body="# RenderKit",
    )

    config = Config(
        {
            "runtime": {
                "filesystem": {
                    "base_dir": "runtime_config",
                }
            }
        },
        path=str(project_dir / "config.yaml"),
    )

    catalog = build_skill_catalog(config)

    assert [item.skill_name for item in catalog.list_all()] == ["renderkit"]
    assert catalog.list_all()[0].host_skill_root_path == str(
        (runtime_config_dir / "extensions" / "skills" / "renderkit").resolve()
    )


def test_build_skill_catalog_infers_scope_from_skill_catalog_dirs_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    home_dir = tmp_path / "home"
    absolute_user_dir = tmp_path / "external-user-skills"
    monkeypatch.setenv("HOME", str(home_dir))

    _write_skill_package(
        project_dir / "agent" / "skills",
        "project_only",
        name="project_only",
        description="相对路径目录里的 skill。",
        body="# Project Only Skill",
    )
    _write_skill_package(
        home_dir / ".codex" / "skills",
        "home_user_only",
        name="home_user_only",
        description="家目录 skill。",
        body="# Home User Skill",
    )
    _write_skill_package(
        absolute_user_dir,
        "absolute_user_only",
        name="absolute_user_only",
        description="绝对路径 skill。",
        body="# Absolute User Skill",
    )

    config = Config(
        {
            "runtime": {
                "filesystem": {
                    "enabled": True,
                    "skill_catalog_dirs": [
                        "./agent/skills",
                        "~/.codex/skills",
                        str(absolute_user_dir),
                    ],
                }
            }
        },
        path=str(project_dir / "config.yaml"),
    )

    catalog = build_skill_catalog(config)

    assert [
        (item.skill_name, item.scope)
        for item in catalog.list_all()
    ] == [
        ("absolute_user_only", "user"),
        ("home_user_only", "user"),
        ("project_only", "project"),
    ]


# endregion
