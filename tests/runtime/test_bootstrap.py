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
    AgentProfile,
    InMemoryMemoryStore,
    ContextCompactor,
    ModelContextSummarizer,
    LocalReferenceBackend,
    NullReferenceBackend,
    OpenVikingReferenceBackend,
    RuntimePlugin,
    RuntimePluginContext,
    RetrievalPlanner,
    RouteDecision,
    SQLiteChannelEventStore,
    SQLiteMemoryStore,
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


class BootstrapTrackingPlugin(RuntimePlugin):
    """用于 bootstrap 注入测试的最小 runtime plugin."""

    name = "bootstrap_tracking"

    def __init__(self) -> None:
        self.setup_calls = 0

    async def setup(self, runtime: RuntimePluginContext) -> None:
        _ = runtime
        self.setup_calls += 1


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
    assert components.pipeline.memory_broker is components.memory_broker
    assert components.pipeline.retrieval_planner is components.retrieval_planner
    assert isinstance(components.memory_store, InMemoryMemoryStore)
    assert len(gateway.sent) == 1


async def test_build_runtime_components_accepts_runtime_plugins() -> None:
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
    plugin = BootstrapTrackingPlugin()
    components = build_runtime_components(
        config,
        gateway=gateway,
        agent=agent,
        plugins=[plugin],
    )

    await components.plugin_manager.ensure_started()

    assert plugin.setup_calls == 1


async def test_build_runtime_components_loads_runtime_plugins_from_config() -> None:
    from tests.runtime.runtime_plugin_samples import SampleConfiguredRuntimePlugin

    SampleConfiguredRuntimePlugin.reset()
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "plugins": [
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                ],
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    await components.plugin_manager.ensure_started()

    assert SampleConfiguredRuntimePlugin.setup_calls == 1


async def test_build_runtime_components_expands_enabled_skills_into_visible_tools() -> None:
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
                        "enabled_skills": ["sample_configured_skill"],
                    }
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                },
                "plugins": [
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                ],
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await components.plugin_manager.ensure_started()

    profile = components.profile_loader.load(
        RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        )
    )
    visible_tools = components.tool_broker.visible_tools(profile)

    assert profile.enabled_skills == ["sample_configured_skill"]
    assert [tool.name for tool in visible_tools] == ["sample_configured_tool"]
    assert any(
        tool.name == "sample_configured_tool"
        for tool in components.tool_broker.visible_tools(
            AgentProfile(
                agent_id="aca",
                name="Aca",
                prompt_ref="prompt/default",
                default_model="test-model",
                enabled_tools=["sample_configured_tool"],
            )
        )
    )


async def test_build_runtime_components_loads_profiles_and_prompts_from_filesystem(
    tmp_path: Path,
) -> None:
    profiles_dir = tmp_path / "profiles"
    prompts_dir = tmp_path / "prompts"
    profiles_dir.mkdir()
    prompts_dir.mkdir()
    (profiles_dir / "aca.yaml").write_text(
        "\n".join(
            [
                "name: Aca Filesystem",
                "prompt_ref: prompt/aca",
                "default_model: fs-model",
                "enabled_tools:",
                "  - reference_search",
            ]
        ),
        encoding="utf-8",
    )
    (prompts_dir / "aca.md").write_text("You are Aca from filesystem.", encoding="utf-8")
    config = Config(
        {
            "agent": {
                "default_model": "fallback-model",
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "filesystem": {
                    "enabled": True,
                    "base_dir": str(tmp_path),
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
    prompt = components.prompt_loader.load("prompt/aca")

    assert profile.name == "Aca Filesystem"
    assert profile.default_model == "fs-model"
    assert profile.enabled_tools == ["reference_search"]
    assert prompt == "You are Aca from filesystem."


async def test_build_runtime_components_exposes_control_plane() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "fallback-model",
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "default_agent_id": "aca",
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    status = await components.control_plane.get_status()

    assert components.control_plane.app is components.app
    assert status.active_run_count == 0
    assert status.loaded_plugins == []


async def test_build_runtime_components_control_plane_can_switch_thread_agent() -> None:
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
                    "ops": {
                        "name": "Ops",
                        "prompt_ref": "prompt/ops",
                        "default_model": "model-o",
                    },
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                    "prompt/ops": "You are the operator agent.",
                },
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="ok", model_used="model-o"))
    components = build_runtime_components(config, gateway=gateway, agent=agent)
    await components.thread_manager.get_or_create(
        thread_id="qq:user:10001",
        channel_scope="qq:user:10001",
    )
    switch = await components.control_plane.switch_thread_agent(
        thread_id="qq:user:10001",
        agent_id="ops",
    )
    event = StandardEvent(
        event_id="evt-switch-1",
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
        raw_message_id="msg-switch-1",
        sender_nickname="acacia",
        sender_role=None,
    )

    components.app.install()
    await gateway.handler(event)

    assert switch.ok is True
    assert agent.calls[0]["system_prompt"] == "You are the operator agent."
    assert agent.calls[0]["model"] == "model-o"


async def test_build_runtime_components_loads_binding_rules_from_filesystem(
    tmp_path: Path,
) -> None:
    bindings_dir = tmp_path / "bindings"
    bindings_dir.mkdir()
    (bindings_dir / "group.yaml").write_text(
        "\n".join(
            [
                "agent_id: group",
                "priority: 60",
                "match:",
                "  channel_scope: qq:group:20002",
            ]
        ),
        encoding="utf-8",
    )
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
                "filesystem": {
                    "enabled": True,
                    "base_dir": str(tmp_path),
                },
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="hello group", model_used="model-g"))
    components = build_runtime_components(config, gateway=gateway, agent=agent)
    event = StandardEvent(
        event_id="evt-group-fs-1",
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
        raw_message_id="msg-group-fs-1",
        sender_nickname="acacia",
        sender_role=None,
    )

    components.app.install()
    await gateway.handler(event)

    assert agent.calls[0]["system_prompt"] == "You are the group agent."
    assert agent.calls[0]["model"] == "model-g"


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


async def test_build_runtime_components_supports_targets_self_binding_rule() -> None:
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
                    "mention": {
                        "name": "Mention",
                        "prompt_ref": "prompt/mention",
                        "default_model": "model-m",
                    },
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                    "prompt/mention": "You are the directed mention agent.",
                },
                "binding_rules": [
                    {
                        "rule_id": "mention-directed",
                        "agent_id": "mention",
                        "priority": 80,
                        "match": {
                            "event_type": "message",
                            "channel_scope": "qq:group:20002",
                            "targets_self": True,
                        },
                    },
                ],
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="hello mention", model_used="model-m"))
    components = build_runtime_components(config, gateway=gateway, agent=agent)
    event = StandardEvent(
        event_id="evt-group-mention-1",
        event_type="message",
        platform="qq",
        timestamp=456,
        source=EventSource(
            platform="qq",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        segments=[MsgSegment(type="text", data={"text": "hello @bot"})],
        raw_message_id="msg-group-mention-1",
        sender_nickname="acacia",
        sender_role="member",
        targets_self=True,
    )

    components.app.install()
    await gateway.handler(event)

    assert agent.calls[0]["system_prompt"] == "You are the directed mention agent."
    assert agent.calls[0]["model"] == "model-m"


async def test_build_runtime_components_supports_event_type_binding_override() -> None:
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
                    "notice": {
                        "name": "Notice",
                        "prompt_ref": "prompt/notice",
                        "default_model": "model-n",
                    },
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                    "prompt/group": "You are the group agent.",
                    "prompt/notice": "You are the notice agent.",
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
                        "rule_id": "group-poke",
                        "agent_id": "notice",
                        "priority": 70,
                        "match": {
                            "event_type": "poke",
                            "channel_scope": "qq:group:20002",
                        },
                    },
                ],
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="noticed", model_used="model-n"))
    components = build_runtime_components(config, gateway=gateway, agent=agent)
    event = StandardEvent(
        event_id="evt-poke-2",
        event_type="poke",
        platform="qq",
        timestamp=789,
        source=EventSource(
            platform="qq",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        segments=[],
        raw_message_id="",
        sender_nickname="acacia",
        sender_role="member",
        operator_id="10001",
    )

    components.app.install()
    await gateway.handler(event)

    assert agent.calls[0]["system_prompt"] == "You are the notice agent."
    assert agent.calls[0]["model"] == "model-n"


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
    assert await components.channel_event_store.get_thread_events("qq:user:10001") == []


async def test_build_runtime_components_loads_inbound_rules_from_filesystem(
    tmp_path: Path,
) -> None:
    inbound_dir = tmp_path / "inbound_rules"
    inbound_dir.mkdir()
    (inbound_dir / "poke.yaml").write_text(
        "\n".join(
            [
                "run_mode: silent_drop",
                "match:",
                "  platform: qq",
                "  event_type: poke",
            ]
        ),
        encoding="utf-8",
    )
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "filesystem": {
                    "enabled": True,
                    "base_dir": str(tmp_path),
                },
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="should not send"))
    components = build_runtime_components(config, gateway=gateway, agent=agent)
    event = StandardEvent(
        event_id="evt-poke-fs-1",
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
    assert await components.channel_event_store.get_thread_events("qq:user:10001") == []


async def test_build_runtime_components_records_record_only_notice_event() -> None:
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
                        "rule_id": "record-recall",
                        "run_mode": "record_only",
                        "match": {
                            "platform": "qq",
                            "event_type": "recall",
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
        event_id="evt-recall-1",
        event_type="recall",
        platform="qq",
        timestamp=456,
        source=EventSource(
            platform="qq",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        segments=[],
        raw_message_id="",
        sender_nickname="acacia",
        sender_role="member",
        operator_id="10002",
        target_message_id="msg-42",
    )

    components.app.install()
    await gateway.handler(event)

    assert agent.calls == []
    assert gateway.sent == []
    saved = await components.channel_event_store.get_thread_events("qq:group:20002")
    assert saved[0].event_type == "recall"
    assert saved[0].content_text == "[notice:recall target=msg-42]"
    assert saved[0].metadata["run_mode"] == "record_only"


async def test_build_runtime_components_applies_event_policies_to_run_metadata() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "event_policies": [
                    {
                        "policy_id": "group-poke-memory",
                        "priority": 80,
                        "match": {
                            "platform": "qq",
                            "event_type": "poke",
                            "channel_scope": "qq:group:20002",
                        },
                        "persist_event": False,
                        "extract_to_memory": True,
                        "memory_scopes": ["episodic", "relationship"],
                        "tags": ["notice", "poke"],
                    }
                ],
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="hello back"))
    components = build_runtime_components(config, gateway=gateway, agent=agent)
    event = StandardEvent(
        event_id="evt-poke-memory-1",
        event_type="poke",
        platform="qq",
        timestamp=321,
        source=EventSource(
            platform="qq",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        segments=[],
        raw_message_id="",
        sender_nickname="acacia",
        sender_role="member",
        operator_id="10001",
    )

    components.app.install()
    await gateway.handler(event)

    run = next(iter(components.run_manager._runs.values()))
    assert run.metadata["event_policy_id"] == "group-poke-memory"
    assert run.metadata["event_extract_to_memory"] is True
    assert run.metadata["event_memory_scopes"] == ["episodic", "relationship"]
    assert await components.channel_event_store.get_thread_events("qq:group:20002") == []


async def test_build_runtime_components_loads_event_policies_from_filesystem(
    tmp_path: Path,
) -> None:
    policies_dir = tmp_path / "event_policies"
    policies_dir.mkdir()
    (policies_dir / "poke.yaml").write_text(
        "\n".join(
            [
                "match:",
                "  platform: qq",
                "  event_type: poke",
                "  channel_scope: qq:group:20002",
                "persist_event: false",
                "extract_to_memory: true",
                "memory_scopes:",
                "  - episodic",
                "  - relationship",
                "tags:",
                "  - notice",
                "  - poke",
            ]
        ),
        encoding="utf-8",
    )
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "filesystem": {
                    "enabled": True,
                    "base_dir": str(tmp_path),
                },
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="hello back"))
    components = build_runtime_components(config, gateway=gateway, agent=agent)
    event = StandardEvent(
        event_id="evt-poke-memory-fs-1",
        event_type="poke",
        platform="qq",
        timestamp=321,
        source=EventSource(
            platform="qq",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        segments=[],
        raw_message_id="",
        sender_nickname="acacia",
        sender_role="member",
        operator_id="10001",
    )

    components.app.install()
    await gateway.handler(event)

    run = next(iter(components.run_manager._runs.values()))
    assert run.metadata["event_extract_to_memory"] is True
    assert run.metadata["event_memory_scopes"] == ["episodic", "relationship"]
    assert await components.channel_event_store.get_thread_events("qq:group:20002") == []


async def test_build_runtime_components_persists_minimal_episodic_memory() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "event_policies": [
                    {
                        "policy_id": "private-message-memory",
                        "priority": 80,
                        "match": {
                            "platform": "qq",
                            "event_type": "message",
                            "channel_scope": "qq:user:10001",
                        },
                        "persist_event": True,
                        "extract_to_memory": True,
                        "memory_scopes": ["episodic", "relationship"],
                        "tags": ["chat"],
                    }
                ],
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="hello back"))
    components = build_runtime_components(config, gateway=gateway, agent=agent)

    components.app.install()
    await gateway.handler(_event())

    items = await components.memory_store.find(
        scope="relationship",
        scope_key="qq:user:10001|qq:user:10001",
        memory_types=["episodic"],
    )

    assert len(items) == 1
    assert items[0].memory_type == "episodic"
    assert items[0].source_event_id == "evt-1"
    assert "assistant_1: hello back" in items[0].content


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
    assert isinstance(components1.channel_event_store, SQLiteChannelEventStore)
    assert isinstance(components1.memory_store, SQLiteMemoryStore)

    components1.app.install()
    await gateway1.handler(_event())

    gateway2 = FakeGateway()
    agent2 = FakeAgent(FakeAgentResponse(text="hello again", model_used="test-model"))
    components2 = build_runtime_components(config, gateway=gateway2, agent=agent2)
    restored = await components2.thread_manager.get("qq:user:10001")
    delivered = await components2.message_store.get_thread_messages("qq:user:10001")
    events = await components2.channel_event_store.get_thread_events("qq:user:10001")

    assert restored is not None
    assert restored.working_messages == [
        {"role": "user", "content": "[acacia/10001] hello"},
        {"role": "assistant", "content": "hello back"},
    ]
    assert [msg.content_text for msg in delivered] == ["hello back"]
    assert delivered[0].metadata["thread_content"] == "hello back"
    assert [event.content_text for event in events] == ["hello"]


def test_build_runtime_components_defaults_to_null_reference_backend() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "runtime-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    assert isinstance(components.reference_backend, NullReferenceBackend)
    assert isinstance(components.retrieval_planner, RetrievalPlanner)
    assert isinstance(components.context_compactor, ContextCompactor)
    assert isinstance(components.context_compactor.summarizer, ModelContextSummarizer)


def test_build_runtime_components_applies_prompt_assembly_config() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "runtime-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "prompt_assembly": {
                    "sticky_intro": "稳定规则如下",
                    "summary_slot_position": "history_prefix",
                    "summary_message_role": "system",
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    assert components.retrieval_planner.config.sticky_intro == "稳定规则如下"
    assert components.retrieval_planner.config.summary_slot_position == "history_prefix"
    assert components.retrieval_planner.config.summary_message_role == "system"


def test_build_runtime_components_applies_context_compaction_config() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "runtime-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "context_compaction": {
                    "enabled": True,
                    "strategy": "summarize",
                    "max_context_ratio": 0.55,
                    "preserve_recent_turns": 4,
                    "system_prompt_reserve_tokens": 1200,
                    "prompt_slot_reserve_tokens": 2200,
                    "tool_schema_reserve_tokens": 3300,
                    "fallback_context_window": 32000,
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    assert components.context_compactor.config.enabled is True
    assert components.context_compactor.config.strategy == "summarize"
    assert components.context_compactor.config.max_context_ratio == 0.55
    assert components.context_compactor.config.preserve_recent_turns == 4
    assert components.context_compactor.config.system_prompt_reserve_tokens == 1200
    assert components.context_compactor.config.prompt_slot_reserve_tokens == 2200
    assert components.context_compactor.config.tool_schema_reserve_tokens == 3300
    assert components.context_compactor.config.fallback_context_window == 32000
    assert components.context_compactor.config.summary_model == ""


def test_build_runtime_components_selects_local_reference_backend(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "reference.sqlite3"
    config = Config(
        {
            "agent": {
                "default_model": "runtime-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "reference": {
                    "enabled": True,
                    "provider": "local",
                    "local": {
                        "sqlite_path": str(sqlite_path),
                    },
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    assert isinstance(components.reference_backend, LocalReferenceBackend)
    assert components.reference_backend.db_path == sqlite_path


def test_build_runtime_components_selects_openviking_reference_backend() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "runtime-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "reference": {
                    "enabled": True,
                    "provider": "openviking",
                    "openviking": {
                        "mode": "embedded",
                        "path": "./ref-data",
                        "base_uri": "viking://resources/acabot-test",
                    },
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    assert isinstance(components.reference_backend, OpenVikingReferenceBackend)
    assert components.reference_backend.mode == "embedded"
    assert components.reference_backend.path == "./ref-data"
    assert components.reference_backend.base_uri == "viking://resources/acabot-test"


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


def test_build_runtime_components_rejects_thread_id_in_filesystem_binding_rules(
    tmp_path: Path,
) -> None:
    bindings_dir = tmp_path / "bindings"
    bindings_dir.mkdir()
    (bindings_dir / "bad.yaml").write_text(
        "\n".join(
            [
                "agent_id: aca",
                "match:",
                "  thread_id: runtime-internal",
            ]
        ),
        encoding="utf-8",
    )
    config = Config(
        {
            "agent": {
                "default_model": "fallback-model",
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "filesystem": {
                    "enabled": True,
                    "base_dir": str(tmp_path),
                },
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

    raise AssertionError("Expected filesystem binding_rules thread_id to raise ValueError")
