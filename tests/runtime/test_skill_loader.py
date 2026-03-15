from pathlib import Path

import pytest

from acabot.runtime import (
    FileSystemSkillPackageLoader,
    SkillPackageFormatError,
)


def _fixtures_root() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "skills"


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
    assert manifest.display_name == "Sample Configured Skill"
    assert manifest.description == "用于测试 skill-first catalog 的样例 skill."
    assert manifest.has_references is True
    assert manifest.has_scripts is True
    assert manifest.has_assets is True
    assert manifest.metadata["category"] == "sample"


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
