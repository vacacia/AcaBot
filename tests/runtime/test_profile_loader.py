from acabot.runtime import AgentProfile, RouteDecision, StaticProfileLoader, StaticPromptLoader


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
