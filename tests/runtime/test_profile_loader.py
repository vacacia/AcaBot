from pathlib import Path

from acabot.runtime import (
    AgentProfile,
    ChainedPromptLoader,
    FileSystemBindingLoader,
    FileSystemEventPolicyLoader,
    FileSystemInboundRuleLoader,
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
        default_model="test-model",
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
                "default_model: fs-model",
                "enabled_tools:",
                "  - reference_search",
            ]
        ),
        encoding="utf-8",
    )
    loader = FileSystemProfileLoader(
        profiles_dir,
        default_model="fallback-model",
    )

    profiles = loader.load_all()

    assert "aca" in profiles
    assert profiles["aca"].name == "Aca FS"
    assert profiles["aca"].default_model == "fs-model"
    assert profiles["aca"].enabled_tools == ["reference_search"]


def test_filesystem_binding_loader_loads_yaml_rules(tmp_path: Path) -> None:
    bindings_dir = tmp_path / "bindings"
    bindings_dir.mkdir()
    (bindings_dir / "group.yaml").write_text(
        "\n".join(
            [
                "agent_id: group",
                "priority: 40",
                "match:",
                "  channel_scope: qq:group:20002",
            ]
        ),
        encoding="utf-8",
    )
    (bindings_dir / "notice.yaml").write_text(
        "\n".join(
            [
                "rules:",
                "  - agent_id: notice",
                "    priority: 80",
                "    match:",
                "      event_type: member_join",
                "  - rule_id: mention",
                "    agent_id: group",
                "    match:",
                "      targets_self: true",
            ]
        ),
        encoding="utf-8",
    )
    loader = FileSystemBindingLoader(bindings_dir)

    rules = loader.load_all()

    assert [rule["rule_id"] for rule in rules] == [
        "fs:group",
        "fs:notice:0",
        "mention",
    ]
    assert rules[0]["match"]["channel_scope"] == "qq:group:20002"
    assert rules[1]["match"]["event_type"] == "member_join"
    assert rules[2]["match"]["targets_self"] is True


def test_filesystem_inbound_rule_loader_loads_rule_files(tmp_path: Path) -> None:
    inbound_dir = tmp_path / "inbound_rules"
    inbound_dir.mkdir()
    (inbound_dir / "mentions.yaml").write_text(
        "\n".join(
            [
                "run_mode: record_only",
                "match:",
                "  event_type: message",
                "  targets_self: true",
            ]
        ),
        encoding="utf-8",
    )
    loader = FileSystemInboundRuleLoader(inbound_dir)

    rules = loader.load_all()

    assert rules == [
        {
            "rule_id": "fs:mentions",
            "run_mode": "record_only",
            "match": {
                "event_type": "message",
                "targets_self": True,
            },
        }
    ]


def test_filesystem_event_policy_loader_loads_rule_list(tmp_path: Path) -> None:
    policies_dir = tmp_path / "event_policies"
    policies_dir.mkdir()
    (policies_dir / "notice.yaml").write_text(
        "\n".join(
            [
                "rules:",
                "  - policy_id: poke-memory",
                "    match:",
                "      event_type: poke",
                "    persist_event: false",
                "    extract_to_memory: true",
                "  - match:",
                "      notice_type: member_join",
                "    tags:",
                "      - notice",
            ]
        ),
        encoding="utf-8",
    )
    loader = FileSystemEventPolicyLoader(policies_dir)

    rules = loader.load_all()

    assert rules[0]["policy_id"] == "poke-memory"
    assert rules[0]["extract_to_memory"] is True
    assert rules[1]["policy_id"] == "fs:notice:1"
    assert rules[1]["match"]["notice_type"] == "member_join"
    assert rules[1]["tags"] == ["notice"]
