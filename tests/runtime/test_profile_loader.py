from pathlib import Path

import pytest

from acabot.runtime import (
    AgentProfile,
    ChainedPromptLoader,
    FileSystemProfileLoader,
    FileSystemPromptLoader,
    RouteDecision,
    StaticProfileLoader,
    StaticPromptLoader,
)


def _profile(agent_id: str, prompt_ref: str) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id,
        name=agent_id,
        prompt_ref=prompt_ref,
    )


def test_static_prompt_loader_returns_prompt_text() -> None:
    loader = StaticPromptLoader({"prompt/default": "You are Aca."})

    prompt = loader.load("prompt/default")

    assert prompt == "You are Aca."


def test_static_profile_loader_resolves_profile_by_agent_id() -> None:
    loader = StaticProfileLoader(
        profiles={
            "aca": _profile("aca", "prompt/default"),
            "alt": _profile("alt", "prompt/alt"),
        }
    )
    decision = RouteDecision(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="alt",
        channel_scope="qq:user:10001",
    )

    profile = loader.load(decision)

    assert profile.agent_id == "alt"
    assert profile.prompt_ref == "prompt/alt"


def test_static_profile_loader_falls_back_to_default_agent() -> None:
    loader = StaticProfileLoader(
        profiles={"aca": _profile("aca", "prompt/default")},
        default_agent_id="aca",
    )
    decision = RouteDecision(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="missing",
        channel_scope="qq:user:10001",
    )

    profile = loader.load(decision)

    assert profile.agent_id == "aca"


def test_filesystem_prompt_loader_loads_prompt_file(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "aca.md").write_text("You are Aca from filesystem.", encoding="utf-8")
    loader = FileSystemPromptLoader(prompts_dir)

    prompt = loader.load("prompt/aca")

    assert prompt == "You are Aca from filesystem."


def test_chained_prompt_loader_falls_back_to_static_loader(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    loader = ChainedPromptLoader(
        [
            FileSystemPromptLoader(prompts_dir),
            StaticPromptLoader({"prompt/default": "Fallback prompt."}),
        ]
    )

    prompt = loader.load("prompt/default")

    assert prompt == "Fallback prompt."


def test_filesystem_profile_loader_loads_yaml_profiles(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "aca.yaml").write_text(
        "\n".join(
            [
                "name: Aca FS",
                "prompt_ref: prompt/aca",
                "enabled_tools:",
                "  - reference_search",
                "skills:",
                "  - reference_lookup",
                "  - excel_processing",
            ]
        ),
        encoding="utf-8",
    )
    loader = FileSystemProfileLoader(
        profiles_dir,
    )

    profiles = loader.load_all()

    assert "aca" in profiles
    assert profiles["aca"].name == "Aca FS"
    assert profiles["aca"].enabled_tools == ["reference_search"]
    assert profiles["aca"].skills == ["reference_lookup", "excel_processing"]


def test_filesystem_profile_loader_rejects_non_string_skill_entries(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "aca.yaml").write_text(
        "\n".join(
            [
                "name: Aca FS",
                "skills:",
                "  - skill_name: reference_lookup",
            ]
        ),
        encoding="utf-8",
    )
    loader = FileSystemProfileLoader(
        profiles_dir,
    )

    with pytest.raises(ValueError, match="Skill must be a string"):
        loader.load_all()
