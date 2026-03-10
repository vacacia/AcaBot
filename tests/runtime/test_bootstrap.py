from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from acabot.config import Config
from acabot.runtime import (
    RouteDecision,
    StoreBackedRunManager,
    StoreBackedThreadManager,
    build_runtime_components,
)
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


async def test_build_runtime_components_uses_channel_binding_for_group_event() -> None:
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
                        "default_model": "model-a",
                    },
                    "group": {
                        "name": "Group",
                        "prompt_ref": "prompt/group",
                        "default_model": "model-g",
                    },
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                    "prompt/group": "You are the group agent.",
                },
                "binding_rules": [
                    {
                        "rule_id": "group-default",
                        "agent_id": "group",
                        "priority": 40,
                        "match": {
                            "channel_scope": "qq:group:20002",
                        },
                    }
                ],
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeLegacyAgent(FakeLegacyResponse(text="hello group", model_used="model-g"))
    components = build_runtime_components(config, gateway=gateway, agent=agent)
    event = StandardEvent(
        event_id="evt-group-1",
        event_type="message",
        platform="qq",
        timestamp=456,
        source=EventSource(
            platform="qq",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        segments=[MsgSegment(type="text", data={"text": "hello group"})],
        raw_message_id="msg-group-1",
        sender_nickname="acacia",
        sender_role=None,
    )

    components.app.install()
    await gateway.handler(event)

    assert agent.calls[0]["system_prompt"] == "You are the group agent."
    assert agent.calls[0]["model"] == "model-g"


async def test_build_runtime_components_uses_admin_override_rule() -> None:
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
                        "default_model": "model-a",
                    },
                    "group": {
                        "name": "Group",
                        "prompt_ref": "prompt/group",
                        "default_model": "model-g",
                    },
                    "ops": {
                        "name": "Ops",
                        "prompt_ref": "prompt/ops",
                        "default_model": "model-o",
                    },
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                    "prompt/group": "You are the group agent.",
                    "prompt/ops": "You are the operator agent.",
                },
                "binding_rules": [
                    {
                        "rule_id": "group-default",
                        "agent_id": "group",
                        "priority": 40,
                        "match": {
                            "channel_scope": "qq:group:20002",
                        },
                    },
                    {
                        "rule_id": "group-admins",
                        "agent_id": "ops",
                        "priority": 80,
                        "match": {
                            "channel_scope": "qq:group:20002",
                            "sender_roles": ["admin", "owner"],
                        },
                    },
                ],
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeLegacyAgent(FakeLegacyResponse(text="hello ops", model_used="model-o"))
    components = build_runtime_components(config, gateway=gateway, agent=agent)
    event = StandardEvent(
        event_id="evt-group-admin-1",
        event_type="message",
        platform="qq",
        timestamp=456,
        source=EventSource(
            platform="qq",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        segments=[MsgSegment(type="text", data={"text": "hello ops"})],
        raw_message_id="msg-group-admin-1",
        sender_nickname="acacia",
        sender_role="admin",
    )

    components.app.install()
    await gateway.handler(event)

    assert agent.calls[0]["system_prompt"] == "You are the operator agent."
    assert agent.calls[0]["model"] == "model-o"


async def test_build_runtime_components_uses_sqlite_persistence_when_configured(
    tmp_path: Path,
) -> None:
    sqlite_path = tmp_path / "runtime.db"
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "persistence": {
                    "sqlite_path": str(sqlite_path),
                },
            },
        }
    )
    gateway1 = FakeGateway()
    agent1 = FakeLegacyAgent(FakeLegacyResponse(text="hello back", model_used="test-model"))
    components1 = build_runtime_components(config, gateway=gateway1, agent=agent1)

    assert isinstance(components1.thread_manager, StoreBackedThreadManager)
    assert isinstance(components1.run_manager, StoreBackedRunManager)

    components1.app.install()
    await gateway1.handler(_event())

    gateway2 = FakeGateway()
    agent2 = FakeLegacyAgent(FakeLegacyResponse(text="hello again", model_used="test-model"))
    components2 = build_runtime_components(config, gateway=gateway2, agent=agent2)
    restored = await components2.thread_manager.get("qq:user:10001")

    assert restored is not None
    assert restored.working_messages == [
        {"role": "user", "content": "[acacia/10001] hello"},
        {"role": "assistant", "content": "hello back"},
    ]


def test_build_runtime_components_rejects_thread_id_in_binding_rules() -> None:
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
                        "default_model": "model-a",
                    },
                },
                "binding_rules": [
                    {
                        "rule_id": "bad-thread-rule",
                        "agent_id": "aca",
                        "match": {
                            "thread_id": "thread:temporary",
                        },
                    }
                ],
            },
        }
    )

    try:
        build_runtime_components(
            config,
            gateway=FakeGateway(),
            agent=FakeLegacyAgent(FakeLegacyResponse(text="ok")),
        )
    except ValueError as exc:
        assert "must not declare thread_id" in str(exc)
        return

    raise AssertionError("Expected thread_id in binding_rules to raise ValueError")
