from pathlib import Path

import pytest

from acabot.runtime.control.session_bundle_loader import SessionBundleLoader
from acabot.runtime.control.session_loader import SessionConfigLoader


def _write_session_bundle(
    tmp_path: Path,
    *,
    session_id: str = "qq:group:123456",
    frontstage_agent_id: str = "frontstage",
    agent_id: str = "frontstage",
    prompt_ref: str = "prompt/aca/default",
    visible_tools: list[str] | None = None,
    visible_skills: list[str] | None = None,
    visible_subagents: list[str] | None = None,
) -> Path:
    bundle_dir = tmp_path / "sessions" / "qq" / "group" / "123456"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        "\n".join(
            [
                "session:",
                f"  id: {session_id}",
                "frontstage:",
                f"  agent_id: {frontstage_agent_id}",
            ]
        ),
        encoding="utf-8",
    )
    (bundle_dir / "agent.yaml").write_text(
        "\n".join(
            [
                f"agent_id: {agent_id}",
                f"prompt_ref: {prompt_ref}",
                "visible_tools:",
                *[f"  - {item}" for item in (visible_tools or ["read"])],
                "visible_skills:",
                *[f"  - {item}" for item in (visible_skills or ["frontend-design"])],
                "visible_subagents:",
                *[f"  - {item}" for item in (visible_subagents or ["excel-worker"])],
            ]
        ),
        encoding="utf-8",
    )
    return bundle_dir


def test_session_bundle_loader_reads_session_and_agent_yaml(tmp_path: Path) -> None:
    _write_session_bundle(tmp_path)
    loader = SessionBundleLoader(
        config_root=tmp_path / "sessions",
        prompt_refs={"prompt/aca/default"},
        tool_names={"read"},
        skill_names={"frontend-design"},
        subagent_names={"excel-worker"},
    )

    bundle = loader.load_by_session_id("qq:group:123456")

    assert bundle.session_config.session_id == "qq:group:123456"
    assert bundle.session_config.frontstage_agent_id == "frontstage"
    assert bundle.frontstage_agent.agent_id == "frontstage"
    assert bundle.frontstage_agent.prompt_ref == "prompt/aca/default"
    assert bundle.paths.session_dir == bundle.paths.session_config_path.parent
    assert bundle.paths.agent_config_path.name == "agent.yaml"


def test_session_bundle_loader_rejects_mismatched_internal_ids(tmp_path: Path) -> None:
    _write_session_bundle(
        tmp_path,
        frontstage_agent_id="frontstage",
        agent_id="other-agent",
    )
    loader = SessionBundleLoader(
        config_root=tmp_path / "sessions",
        prompt_refs={"prompt/aca/default"},
        tool_names={"read"},
        skill_names={"frontend-design"},
        subagent_names={"excel-worker"},
    )

    with pytest.raises(ValueError, match="frontstage_agent_id"):
        loader.load_by_session_id("qq:group:123456")


def test_session_bundle_loader_rejects_missing_catalog_reference(tmp_path: Path) -> None:
    _write_session_bundle(
        tmp_path,
        prompt_ref="prompt/missing",
        visible_tools=["shell"],
        visible_skills=["missing-skill"],
        visible_subagents=["missing-worker"],
    )
    loader = SessionBundleLoader(
        config_root=tmp_path / "sessions",
        prompt_refs={"prompt/aca/default"},
        tool_names={"read"},
        skill_names={"frontend-design"},
        subagent_names={"excel-worker"},
    )

    with pytest.raises(ValueError, match="prompt_ref|visible_tools|visible_skills|visible_subagents"):
        loader.load_by_session_id("qq:group:123456")


def test_session_config_loader_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sessions" / "qq" / "group" / "123456"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text("- not-a-mapping\n", encoding="utf-8")

    loader = SessionConfigLoader(config_root=tmp_path / "sessions")

    with pytest.raises(ValueError, match="mapping"):
        loader.load_by_session_id("qq:group:123456")


def test_session_config_loader_rejects_non_mapping_nested_blocks(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sessions" / "qq" / "group" / "123456"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        "\n".join(
            [
                "session:",
                "  - broken",
                "frontstage:",
                "  agent_id: frontstage",
            ]
        ),
        encoding="utf-8",
    )

    loader = SessionConfigLoader(config_root=tmp_path / "sessions")

    with pytest.raises(ValueError, match="session"):
        loader.load_by_session_id("qq:group:123456")


def test_session_config_loader_requires_frontstage_agent_id(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sessions" / "qq" / "group" / "123456"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        "\n".join(
            [
                "session:",
                "  id: qq:group:123456",
                "frontstage: {}",
            ]
        ),
        encoding="utf-8",
    )

    loader = SessionConfigLoader(config_root=tmp_path / "sessions")

    with pytest.raises(ValueError, match="frontstage.agent_id"):
        loader.load_by_session_id("qq:group:123456")


def test_session_config_loader_rejects_mismatched_session_id(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sessions" / "qq" / "group" / "123456"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        "\n".join(
            [
                "session:",
                "  id: qq:group:999999",
                "frontstage:",
                "  agent_id: frontstage",
            ]
        ),
        encoding="utf-8",
    )

    loader = SessionConfigLoader(config_root=tmp_path / "sessions")

    with pytest.raises(ValueError, match="session.id"):
        loader.load_by_session_id("qq:group:123456")


def test_session_config_loader_rejects_non_mapping_domain_block(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sessions" / "qq" / "group" / "123456"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        "\n".join(
            [
                "session:",
                "  id: qq:group:123456",
                "frontstage:",
                "  agent_id: frontstage",
                "surfaces:",
                "  message.mention:",
                "    routing: broken",
            ]
        ),
        encoding="utf-8",
    )

    loader = SessionConfigLoader(config_root=tmp_path / "sessions")

    with pytest.raises(ValueError, match="surfaces\\.message\\.mention\\.routing"):
        loader.load_by_session_id("qq:group:123456")


def test_session_config_loader_rejects_scalar_matchspec_lists(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sessions" / "qq" / "group" / "123456"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        "\n".join(
            [
                "session:",
                "  id: qq:group:123456",
                "frontstage:",
                "  agent_id: frontstage",
                "selectors:",
                "  sender_is_admin:",
                "    sender_roles: admin",
            ]
        ),
        encoding="utf-8",
    )

    loader = SessionConfigLoader(config_root=tmp_path / "sessions")

    with pytest.raises(ValueError, match="sender_roles"):
        loader.load_by_session_id("qq:group:123456")


def test_session_bundle_loader_requires_catalog_validation_inputs(tmp_path: Path) -> None:
    _write_session_bundle(tmp_path)
    loader = SessionBundleLoader(config_root=tmp_path / "sessions")

    with pytest.raises(ValueError, match="catalog"):
        loader.load_by_session_id("qq:group:123456")


def test_session_bundle_loader_rejects_scalar_visibility_fields(tmp_path: Path) -> None:
    bundle_dir = _write_session_bundle(tmp_path)
    (bundle_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "agent_id: frontstage",
                "prompt_ref: prompt/aca/default",
                "visible_tools: read",
                "visible_skills:",
                "  - frontend-design",
                "visible_subagents:",
                "  - excel-worker",
            ]
        ),
        encoding="utf-8",
    )
    loader = SessionBundleLoader(
        config_root=tmp_path / "sessions",
        prompt_refs={"prompt/aca/default"},
        tool_names={"read"},
        skill_names={"frontend-design"},
        subagent_names={"excel-worker"},
    )

    with pytest.raises(ValueError, match="visible_tools"):
        loader.load_by_session_id("qq:group:123456")
