from dataclasses import dataclass, field
from typing import Any

from acabot.config import Config
from acabot.runtime import RouteDecision, build_runtime_components
from acabot.types import EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway


@dataclass
class FakeLegacyResponse:
    text: str = ""
    attachments: list[Any] = field(default_factory=list)
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls_made: list[Any] = field(default_factory=list)
    model_used: str = ""
    raw: Any = None


class FakeLegacyAgent:
    def __init__(self, response: FakeLegacyResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> FakeLegacyResponse:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "model": model,
            }
        )
        return self.response


def _event() -> StandardEvent:
    return StandardEvent(
        event_id="evt-1",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        segments=[MsgSegment(type="text", data={"text": "hello"})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role=None,
    )


def test_build_runtime_components_uses_runtime_profiles_and_prompts() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "fallback-model",
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/aca",
                        "default_model": "runtime-model",
                    }
                },
                "prompts": {
                    "prompt/aca": "You are Aca."
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeLegacyAgent(FakeLegacyResponse(text="ok")),
    )
    decision = RouteDecision(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:user:10001",
    )
    profile = components.profile_loader.load(decision)

    assert components.router.default_agent_id == "aca"
    assert components.prompt_loader.load("prompt/aca") == "You are Aca."
    assert profile.default_model == "runtime-model"


async def test_build_runtime_components_runs_app_with_legacy_agent() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeLegacyAgent(FakeLegacyResponse(text="hello back", model_used="test-model"))
    components = build_runtime_components(config, gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_event())

    assert agent.calls[0]["system_prompt"] == "You are Aca."
    assert agent.calls[0]["model"] == "test-model"
    assert len(gateway.sent) == 1
