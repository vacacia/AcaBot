"""subagent 文件系统 catalog 测试."""

from pathlib import Path

from acabot.runtime.subagents.catalog import SubagentCatalog
from acabot.runtime.subagents.loader import (
    FileSystemSubagentPackageLoader,
    SubagentDiscoveryRoot,
)


def _write_subagent_package(
    root_dir: Path,
    *,
    name: str,
    description: str,
    tools: list[str],
    prompt: str,
    model_target: str | None = None,
) -> Path:
    """写入一个最小可用的 SUBAGENT.md 包."""

    package_dir = root_dir / name
    package_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        "tools:",
    ]
    for tool_name in tools:
        lines.append(f"  - {tool_name}")
    if model_target is not None:
        lines.append(f"model_target: {model_target}")
    lines.extend(
        [
            "---",
            prompt,
            "",
        ]
    )
    (package_dir / "SUBAGENT.md").write_text("\n".join(lines), encoding="utf-8")
    return package_dir


def test_filesystem_subagent_loader_discovers_subagent_documents(tmp_path: Path) -> None:
    root_dir = tmp_path / ".agents" / "subagents"
    _write_subagent_package(
        root_dir,
        name="excel-worker",
        description="Handle excel cleanup",
        tools=["read", "bash"],
        model_target="agent:aca",
        prompt="You are an excel cleanup worker.",
    )

    loader = FileSystemSubagentPackageLoader(
        [SubagentDiscoveryRoot(host_root_path=str(root_dir))]
    )

    manifests = loader.discover()

    assert [item.subagent_name for item in manifests] == ["excel-worker"]
    assert manifests[0].description == "Handle excel cleanup"
    document = loader.read_document("excel-worker")
    assert document.manifest.tools == ["read", "bash"]
    assert document.manifest.model_target == "agent:aca"
    assert "excel cleanup worker" in document.body_markdown


def test_subagent_catalog_prefers_project_over_user(tmp_path: Path) -> None:
    project_root = tmp_path / "project" / ".agents" / "subagents"
    user_root = tmp_path / "user" / ".agents" / "subagents"
    _write_subagent_package(
        user_root,
        name="excel-worker",
        description="User scoped worker",
        tools=["read"],
        prompt="User worker prompt.",
    )
    _write_subagent_package(
        project_root,
        name="excel-worker",
        description="Project scoped worker",
        tools=["read", "bash"],
        prompt="Project worker prompt.",
    )

    catalog = SubagentCatalog(
        FileSystemSubagentPackageLoader(
            [
                SubagentDiscoveryRoot(host_root_path=str(user_root), scope="user"),
                SubagentDiscoveryRoot(host_root_path=str(project_root), scope="project"),
            ]
        )
    )

    catalog.reload()
    manifest = catalog.get("excel-worker")

    assert manifest is not None
    assert manifest.scope == "project"
    assert manifest.description == "Project scoped worker"
    assert [item.scope for item in catalog.list_all()] == ["project", "user"]
    assert catalog.read("excel-worker").body_markdown.strip() == "Project worker prompt."
