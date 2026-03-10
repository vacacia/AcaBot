"""bootstrap 组装测试.

这一组测试验证默认 runtime 组件树是否按配置正确装配.
当前主线已经切到 `ModelAgentRuntime`, 因此这里的 fake agent 只需要满足
新的 `BaseAgent.run()` duck-typed 形状, 不再强调 legacy runtime.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from acabot.agent import ToolDef
from acabot.config import Config
from acabot.runtime import (
    RouteDecision,
    SQLiteMessageStore,
    StoreBackedRunManager,
    StoreBackedThreadManager,
    ToolBroker,
    build_runtime_components,
)
from acabot.types import EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway


@dataclass
class FakeAgentResponse:
    text: str = ""
    attachments: list[Any] = field(default_factory=list)
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls_made: list[Any] = field(default_factory=list)
    model_used: str = ""
    raw: Any = None

# region fake agent
class FakeAgent:
    """用于 bootstrap 测试的最小 fake agent.

    Attributes:
        response (FakeAgentResponse): 预设返回值.
        calls (list[dict[str, Any]]): 调用记录.
    """

    def __init__(self, response: FakeAgentResponse) -> None:
        """初始化 fake agent.

        Args:
            response: 预设返回值.
        """

        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        tools=None,
        tool_executor=None,
    ) -> FakeAgentResponse:
        """记录一次 run 调用.

        Args:
            system_prompt: 本次调用使用的 system prompt.
            messages: 传给模型的消息列表.
            model: 模型覆盖.
            tools: 当前 run 可见工具.
            tool_executor: 当前 run 的工具执行器.

        Returns:
            预设的响应对象.
        """

        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "model": model,
                "tools": list(tools or []),
                "tool_executor": tool_executor,
            }
        )
        return self.response


# endregion


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
        agent=FakeAgent(FakeAgentResponse(text="ok")),
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


async def test_build_runtime_components_runs_app_with_model_agent_runtime() -> None:
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
    agent = FakeAgent(FakeAgentResponse(text="hello back", model_used="test-model"))
    components = build_runtime_components(config, gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_event())

    assert agent.calls[0]["system_prompt"] == "You are Aca."
    assert agent.calls[0]["model"] == "test-model"
    assert components.pipeline.tool_broker is components.tool_broker
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
    agent = FakeAgent(FakeAgentResponse(text="hello group", model_used="model-g"))
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
    agent = FakeAgent(FakeAgentResponse(text="hello ops", model_used="model-o"))
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


async def test_build_runtime_components_applies_inbound_rules() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "inbound_rules": [
                    {
                        "rule_id": "ignore-poke",
                        "run_mode": "silent_drop",
                        "match": {
                            "platform": "qq",
                            "event_type": "poke",
                        },
                    }
                ],
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not send"))
    components = build_runtime_components(config, gateway=gateway, agent=agent)
    event = StandardEvent(
        event_id="evt-poke-1",
        event_type="poke",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        segments=[],
        raw_message_id="",
        sender_nickname="",
        sender_role=None,
        operator_id="10001",
    )

    components.app.install()
    await gateway.handler(event)

    assert agent.calls == []
    assert gateway.sent == []


async def test_build_runtime_components_wires_tool_broker_into_agent_runtime() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "runtime-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/aca",
                        "default_model": "runtime-model",
                        "enabled_tools": ["get_time"],
                    }
                },
                "prompts": {
                    "prompt/aca": "You are Aca."
                },
            },
        }
    )
    broker = ToolBroker()

    async def get_time(arguments: dict[str, Any]) -> dict[str, Any]:
        return {"time": arguments.get("timezone", "UTC")}

    broker.register_legacy_tool(
        ToolDef(
            name="get_time",
            description="Get current time",
            parameters={"type": "object", "properties": {}},
            handler=get_time,
        )
    )
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="hello back", model_used="runtime-model"))
    components = build_runtime_components(
        config,
        gateway=gateway,
        agent=agent,
        tool_broker=broker,
    )

    components.app.install()
    await gateway.handler(_event())

    assert components.tool_broker is broker
    assert agent.calls[0]["tools"][0].name == "get_time"
    assert agent.calls[0]["tool_executor"] is not None


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
    agent1 = FakeAgent(FakeAgentResponse(text="hello back", model_used="test-model"))
    components1 = build_runtime_components(config, gateway=gateway1, agent=agent1)

    assert isinstance(components1.thread_manager, StoreBackedThreadManager)
    assert isinstance(components1.run_manager, StoreBackedRunManager)
    assert isinstance(components1.message_store, SQLiteMessageStore)

    components1.app.install()
    await gateway1.handler(_event())

    gateway2 = FakeGateway()
    agent2 = FakeAgent(FakeAgentResponse(text="hello again", model_used="test-model"))
    components2 = build_runtime_components(config, gateway=gateway2, agent=agent2)
    restored = await components2.thread_manager.get("qq:user:10001")
    delivered = await components2.message_store.get_thread_messages("qq:user:10001")

    assert restored is not None
    assert restored.working_messages == [
        {"role": "user", "content": "[acacia/10001] hello"},
        {"role": "assistant", "content": "hello back"},
    ]
    assert [msg.content_text for msg in delivered] == ["hello back"]
    assert delivered[0].metadata["thread_content"] == "hello back"


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
            agent=FakeAgent(FakeAgentResponse(text="ok")),
        )
    except ValueError as exc:
        assert "must not declare thread_id" in str(exc)
        return

    raise AssertionError("Expected thread_id in binding_rules to raise ValueError")
