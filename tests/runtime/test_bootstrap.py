"""bootstrap 组装测试.

这一组测试验证默认 runtime 组件树是否按配置正确装配.
当前主线已经切到 `ModelAgentRuntime`, 因此这里的 fake agent 只需要满足
新的 `BaseAgent.run()` duck-typed 形状.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from acabot.agent import ToolDef, ToolSpec
from acabot.config import Config
from acabot.runtime import (
    ApprovalRequired,
    AgentProfile,
    ContextAssembler,
    InMemoryMemoryStore,
    ContextCompactor,
    ModelContextSummarizer,
    LocalReferenceBackend,
    NullReferenceBackend,
    OpenVikingReferenceBackend,
    PayloadJsonWriter,
    RetrievalPlan,
    RunContext,
    RuntimePlugin,
    RuntimePluginContext,
    RuntimePluginManager,
    RetrievalPlanner,
    RouteDecision,
    SQLiteChannelEventStore,
    SQLiteMemoryStore,
    SQLiteMessageStore,
    StoreBackedRunManager,
    StoreBackedThreadManager,
    ToolPolicyDecision,
    ToolBroker,
    build_runtime_components,
)
from acabot.runtime.contracts import PendingApproval
from acabot.runtime.bootstrap.builders import build_payload_json_writer
from acabot.runtime.bootstrap.config import resolve_runtime_path
from acabot.types import EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway
from .test_pipeline_runtime import ApprovalToolAgent


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
        request_options=None,
        max_tool_rounds=None,
        tools=None,
        tool_executor=None,
    ) -> FakeAgentResponse:
        """记录一次 run 调用.

        Args:
            system_prompt: 本次调用使用的 system prompt.
            messages: 传给模型的消息列表.
            model: 模型覆盖.
            request_options: 当前 run 解析好的 request options.
            max_tool_rounds: 当前 run 允许的最大 tool loop 轮数.
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
                "request_options": dict(request_options or {}),
                "max_tool_rounds": max_tool_rounds,
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


async def test_build_runtime_components_exposes_skill_and_delegate_tools_for_assigned_skills() -> None:
    skills_dir = Path(__file__).resolve().parent.parent / "fixtures" / "skills"
    config = Config(
        {
            "agent": {
                "default_model": "runtime-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "filesystem": {
                    "enabled": True,
                    "skill_catalog_dirs": [str(skills_dir)],
                },
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/aca",
                        "default_model": "runtime-model",
                        "skills": ["sample_configured_skill"],
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

    assert profile.skills == ["sample_configured_skill"]
    assert [tool.name for tool in visible_tools] == ["Skill"]
    assert "sample_configured_skill" in visible_tools[0].description
    registered_executors = components.subagent_delegator.executor_registry.list_all()
    assert [item.agent_id for item in registered_executors] == ["aca"]
    assert registered_executors[0].source == "runtime:local_profile"
    assert any(tool.name == "Skill" for tool in visible_tools)


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


async def test_build_runtime_components_backend_status_exposes_session_path() -> None:
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
    backend_status = await components.control_plane.get_backend_status()

    assert backend_status.configured is False
    assert backend_status.session_path.endswith(".acabot-runtime/backend/session.json")


async def test_build_runtime_components_constructs_configured_backend_service_when_enabled(
    tmp_path: Path,
) -> None:
    config = Config(
        {
            "agent": {
                "default_model": "fallback-model",
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "runtime_root": str(tmp_path / ".acabot-runtime"),
                "backend": {
                    "enabled": True,
                    "admin_actor_ids": ["qq:user:10001"],
                    "session_binding_path": "backend/session.json",
                    "pi_command": ["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    backend_status = await components.control_plane.get_backend_status()

    assert components.backend_bridge.session.is_configured() is True
    assert backend_status.configured is True
    assert backend_status.admin_actor_ids == ["qq:user:10001"]
    assert backend_status.session_path == str((tmp_path / ".acabot-runtime" / "backend" / "session.json").resolve())
    assert components.backend_bridge.session.adapter.cwd == config.base_dir()

    await components.backend_bridge.session.adapter.dispose()


async def test_build_runtime_components_uses_default_bot_admin_actor_ids_for_backend_access(
    tmp_path: Path,
) -> None:
    config = Config(
        {
            "agent": {
                "default_model": "fallback-model",
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "runtime_root": str(tmp_path / ".acabot-runtime"),
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/default",
                        "default_model": "fallback-model",
                        "admin_actor_ids": ["qq:private:123456"],
                    }
                },
                "backend": {
                    "enabled": False,
                    "session_binding_path": "backend/session.json",
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    backend_status = await components.control_plane.get_backend_status()

    assert backend_status.admin_actor_ids == ["qq:private:123456"]


async def test_build_runtime_components_uses_explicit_backend_cwd_when_configured(
    tmp_path: Path,
) -> None:
    backend_cwd = tmp_path / "repo-root"
    backend_cwd.mkdir()
    config = Config(
        {
            "agent": {
                "default_model": "fallback-model",
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "runtime_root": str(tmp_path / ".acabot-runtime"),
                "backend": {
                    "enabled": True,
                    "admin_actor_ids": ["qq:user:10001"],
                    "session_binding_path": "backend/session.json",
                    "pi_command": ["pi", "--mode", "rpc", "--session-dir", str(tmp_path / "pi-sessions")],
                    "cwd": str(backend_cwd),
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    assert components.backend_bridge.session.adapter.cwd == backend_cwd.resolve()

    await components.backend_bridge.session.adapter.dispose()


async def test_build_runtime_components_resolves_backend_binding_path_under_runtime_root(
    tmp_path: Path,
) -> None:
    config = Config(
        {
            "agent": {
                "default_model": "fallback-model",
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "runtime_root": str(tmp_path / ".acabot-runtime"),
                "backend": {
                    "enabled": False,
                    "session_binding_path": "backend/session.json",
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    backend_status = await components.control_plane.get_backend_status()

    assert backend_status.session_path == str((tmp_path / ".acabot-runtime" / "backend" / "session.json").resolve())


async def test_build_runtime_components_invalid_backend_command_stays_unconfigured(
    tmp_path: Path,
) -> None:
    config = Config(
        {
            "agent": {
                "default_model": "fallback-model",
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "runtime_root": str(tmp_path / ".acabot-runtime"),
                "backend": {
                    "enabled": True,
                    "admin_actor_ids": ["qq:user:10001"],
                    "session_binding_path": "backend/session.json",
                    "pi_command": ["definitely-not-a-real-pi-binary"],
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    backend_status = await components.control_plane.get_backend_status()

    assert components.backend_bridge.session.is_configured() is False
    assert backend_status.configured is False
    assert backend_status.session_path == str((tmp_path / ".acabot-runtime" / "backend" / "session.json").resolve())


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



async def test_build_runtime_components_routes_through_session_config(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions/qq/group"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "42.yaml").write_text(
        """
session:
  id: qq:group:42
  template: qq_group
frontstage:
  profile: aca
selectors:
  sender_is_admin:
    sender_roles: [admin]
surfaces:
  message.mention:
    routing:
      default:
        profile: ops
    admission:
      default:
        mode: respond
    extraction:
      default:
        extract_to_memory: true
        scopes: [channel]
        tags: [mention]
  message.plain:
    routing:
      default:
        profile: aca
    admission:
      default:
        mode: record_only
""".strip(),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
agent:
  default_model: "fallback-model"
  system_prompt: "Fallback prompt."

runtime:
  default_agent_id: "aca"
  filesystem:
    base_dir: .
    sessions_dir: sessions
  profiles:
    aca:
      name: "Aca"
      prompt_ref: "prompt/aca"
      default_model: "model-a"
    ops:
      name: "Ops"
      prompt_ref: "prompt/ops"
      default_model: "model-o"
  prompts:
    prompt/aca: "You are Aca."
    prompt/ops: "You are Ops."
""".strip(),
        encoding="utf-8",
    )
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    decision = await components.router.route(
        StandardEvent(
            event_id="evt-session-1",
            event_type="message",
            platform="qq",
            timestamp=123,
            source=EventSource(
                platform="qq",
                message_type="group",
                user_id="10001",
                group_id="42",
            ),
            segments=[MsgSegment(type="text", data={"text": "hello @bot"})],
            raw_message_id="msg-session-1",
            sender_nickname="acacia",
            sender_role="admin",
            mentions_self=True,
            targets_self=True,
        )
    )

    assert decision.agent_id == "ops"
    assert decision.run_mode == "respond"
    assert decision.metadata["surface_id"] == "message.mention"
    assert decision.metadata["event_memory_scopes"] == ["channel"]
    assert decision.metadata["event_tags"] == ["mention"]













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


async def test_build_runtime_components_registers_builtin_computer_tools() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/aca",
                        "default_model": "test-model",
                        "enabled_tools": ["read"],
                    }
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                },
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
    visible = components.tool_broker.visible_tools(profile)
    sources = {
        item["name"]: item["source"]
        for item in components.tool_broker.list_registered_tools()
    }

    assert [plugin.name for plugin in components.plugin_manager.loaded] == ["backend_bridge_tool"]
    assert sources["read"] == "builtin:computer"
    assert "exec" not in sources
    assert [tool.name for tool in visible] == ["read"]


async def test_build_runtime_components_drops_stale_tools_from_removed_computer_adapter() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/aca",
                        "default_model": "test-model",
                        "enabled_tools": ["read", "ls", "exec"],
                    }
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                },
            },
        }
    )
    broker = ToolBroker()
    broker.register_tool(
        ToolSpec(
            name="ls",
            description="stale ls",
            parameters={"type": "object", "properties": {}},
        ),
        lambda arguments, ctx: {"ok": True},
        source="plugin:computer_tool_adapter",
    )
    broker.register_tool(
        ToolSpec(
            name="exec",
            description="stale exec",
            parameters={"type": "object", "properties": {}},
        ),
        lambda arguments, ctx: {"ok": True},
        source="plugin:computer_tool_adapter",
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        tool_broker=broker,
    )
    profile = components.profile_loader.load(
        RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        )
    )
    visible = components.tool_broker.visible_tools(profile)
    sources = {
        item["name"]: item["source"]
        for item in components.tool_broker.list_registered_tools()
    }

    assert "ls" not in sources
    assert "exec" not in sources
    assert [tool.name for tool in visible] == ["read"]


async def test_build_runtime_components_drops_stale_builtin_plugins_from_reused_plugin_manager() -> None:
    class StaleComputerToolAdapterPlugin(RuntimePlugin):
        name = "computer_tool_adapter"

        async def setup(self, runtime: RuntimePluginContext) -> None:
            _ = runtime

        def tools(self) -> list[ToolDef]:
            return [
                ToolDef(
                    name="ls",
                    description="stale ls",
                    parameters={"type": "object", "properties": {}},
                    handler=lambda arguments: {"ok": True, "arguments": arguments},
                )
            ]

    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/aca",
                        "default_model": "test-model",
                        "enabled_tools": ["read", "ls"],
                    }
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                },
            },
        }
    )
    broker = ToolBroker()
    plugin_manager = RuntimePluginManager(
        config=config,
        gateway=FakeGateway(),
        tool_broker=broker,
        builtin_plugins=[StaleComputerToolAdapterPlugin()],
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        tool_broker=broker,
        plugin_manager=plugin_manager,
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
    visible = components.tool_broker.visible_tools(profile)

    assert [plugin.name for plugin in components.plugin_manager.loaded] == ["backend_bridge_tool"]
    assert [tool.name for tool in visible] == ["read"]


async def test_build_runtime_components_rejects_started_plugin_manager() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/aca",
                        "default_model": "test-model",
                        "enabled_tools": ["read"],
                    }
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                },
            },
        }
    )
    broker = ToolBroker()
    plugin_manager = RuntimePluginManager(
        config=config,
        gateway=FakeGateway(),
        tool_broker=broker,
    )
    await plugin_manager.ensure_started()

    with pytest.raises(ValueError, match="fresh RuntimePluginManager"):
        build_runtime_components(
            config,
            gateway=FakeGateway(),
            agent=FakeAgent(FakeAgentResponse(text="ok")),
            tool_broker=broker,
            plugin_manager=plugin_manager,
        )


async def test_build_runtime_components_full_plugin_reload_keeps_builtin_plugins() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/aca",
                        "default_model": "test-model",
                        "enabled_tools": ["read"],
                        "skills": ["sample_configured_skill"],
                    }
                },
                "filesystem": {
                    "enabled": True,
                    "skill_catalog_dirs": [
                        str(Path(__file__).resolve().parent.parent / "fixtures" / "skills")
                    ],
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                },
            },
        }
    )
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    await components.plugin_manager.ensure_started()
    loaded_names, missing = await components.app.reload_plugins()
    profile = components.profile_loader.load(
        RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        )
    )
    visible = components.tool_broker.visible_tools(profile)
    sources = {
        item["name"]: item["source"]
        for item in components.tool_broker.list_registered_tools()
    }

    assert missing == []
    assert loaded_names == ["backend_bridge_tool"]
    assert sources["read"] == "builtin:computer"
    assert sources["Skill"] == "builtin:skills"
    assert [tool.name for tool in visible] == ["read", "Skill"]


async def test_build_runtime_components_reload_keeps_conditional_subagent_delegation_builtin() -> None:
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "filesystem": {
                    "enabled": True,
                    "skill_catalog_dirs": [
                        str(Path(__file__).resolve().parent.parent / "fixtures" / "skills")
                    ],
                },
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/aca",
                        "default_model": "test-model",
                        "skills": ["sample_configured_skill"],
                    },
                    "worker": {
                        "name": "Worker",
                        "prompt_ref": "prompt/worker",
                        "default_model": "test-model",
                    },
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                    "prompt/worker": "You are Worker.",
                },
            },
        }
    )
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    await components.plugin_manager.ensure_started()
    loaded_names, missing = await components.app.reload_plugins()
    profile = components.profile_loader.profiles["aca"]
    visible = components.tool_broker.visible_tools(profile)
    sources = {
        item["name"]: item["source"]
        for item in components.tool_broker.list_registered_tools()
    }

    assert missing == []
    assert loaded_names == ["backend_bridge_tool"]
    assert sources["delegate_subagent"] == "builtin:subagents"
    assert "delegate_subagent" in [tool.name for tool in visible]


async def test_build_runtime_components_default_approval_resume_replays_tool_call() -> None:
    class ApprovalPolicy:
        async def allow(self, *, spec, arguments, ctx) -> ToolPolicyDecision:
            _ = spec, arguments, ctx
            return ToolPolicyDecision(
                allowed=True,
                requires_approval=True,
                reason="needs admin approval",
            )

    broker = ToolBroker(policy=ApprovalPolicy())

    async def restricted(arguments: dict[str, Any], ctx) -> dict[str, Any]:
        _ = arguments, ctx
        return {"ok": True}

    broker.register_tool(
        ToolDef(
            name="restricted",
            description="Restricted tool",
            parameters={"type": "object", "properties": {}},
            handler=lambda arguments: arguments,
        ).to_spec(),
        restricted,
    )
    gateway = FakeGateway()
    components = build_runtime_components(
        Config(
            {
                "agent": {
                    "default_model": "test-model",
                    "system_prompt": "You are Aca.",
                },
                "runtime": {
                    "default_agent_id": "aca",
                    "profiles": {
                        "aca": {
                            "name": "Aca",
                            "prompt_ref": "prompt/aca",
                            "default_model": "test-model",
                            "enabled_tools": ["restricted"],
                        }
                    },
                    "prompts": {
                        "prompt/aca": "You are Aca.",
                    },
                },
            }
        ),
        gateway=gateway,
        agent=ApprovalToolAgent(),
        tool_broker=broker,
    )

    components.app.install()
    await gateway.handler(_event())
    active = await components.run_manager.list_active()
    result = await components.app.approve_pending_approval(active[0].run_id)
    restored = await components.run_manager.get(active[0].run_id)

    assert result.ok is True
    assert result.run_status == "completed"
    assert restored is not None
    assert restored.status == "completed"


async def test_build_runtime_components_approval_resume_marks_completed_with_errors_for_undelivered_outputs() -> None:
    class ApprovalPolicy:
        async def allow(self, *, spec, arguments, ctx) -> ToolPolicyDecision:
            _ = spec, arguments, ctx
            return ToolPolicyDecision(
                allowed=True,
                requires_approval=True,
                reason="needs admin approval",
            )

    broker = ToolBroker(policy=ApprovalPolicy())

    async def restricted(arguments: dict[str, Any], ctx) -> dict[str, Any]:
        _ = arguments, ctx
        return {
            "ok": True,
            "attachments": [
                {"type": "image", "url": "https://example.com/demo.png"},
            ],
        }

    broker.register_tool(
        ToolDef(
            name="restricted",
            description="Restricted tool",
            parameters={"type": "object", "properties": {}},
            handler=lambda arguments: arguments,
        ).to_spec(),
        restricted,
    )
    gateway = FakeGateway()
    components = build_runtime_components(
        Config(
            {
                "agent": {
                    "default_model": "test-model",
                    "system_prompt": "You are Aca.",
                },
                "runtime": {
                    "default_agent_id": "aca",
                    "profiles": {
                        "aca": {
                            "name": "Aca",
                            "prompt_ref": "prompt/aca",
                            "default_model": "test-model",
                            "enabled_tools": ["restricted"],
                        }
                    },
                    "prompts": {
                        "prompt/aca": "You are Aca.",
                    },
                },
            }
        ),
        gateway=gateway,
        agent=ApprovalToolAgent(),
        tool_broker=broker,
    )

    components.app.install()
    await gateway.handler(_event())
    active = await components.run_manager.list_active()
    result = await components.app.approve_pending_approval(active[0].run_id)
    restored = await components.run_manager.get(active[0].run_id)
    steps = await components.run_manager.list_steps(active[0].run_id)

    assert result.ok is True
    assert result.run_status == "completed_with_errors"
    assert restored is not None
    assert restored.status == "completed_with_errors"
    assert steps[-1].step_type == "approval_resume"
    assert steps[-1].payload["result_metadata"]["undelivered_attachment_count"] == 1


async def test_build_runtime_components_approval_resume_fails_closed_on_nested_approval() -> None:
    class ApprovalPolicy:
        async def allow(self, *, spec, arguments, ctx) -> ToolPolicyDecision:
            _ = spec, arguments, ctx
            return ToolPolicyDecision(
                allowed=True,
                requires_approval=True,
                reason="needs admin approval",
            )

    broker = ToolBroker(policy=ApprovalPolicy())

    async def restricted(arguments: dict[str, Any], ctx) -> dict[str, Any]:
        _ = arguments, ctx
        raise ApprovalRequired(
            pending_approval=PendingApproval(
                approval_id="approval:nested",
                reason="nested approval",
                tool_name="restricted",
                tool_call_id="toolcall:nested",
                tool_arguments={"danger": True},
            )
        )

    broker.register_tool(
        ToolDef(
            name="restricted",
            description="Restricted tool",
            parameters={"type": "object", "properties": {}},
            handler=lambda arguments: arguments,
        ).to_spec(),
        restricted,
    )
    gateway = FakeGateway()
    components = build_runtime_components(
        Config(
            {
                "agent": {
                    "default_model": "test-model",
                    "system_prompt": "You are Aca.",
                },
                "runtime": {
                    "default_agent_id": "aca",
                    "profiles": {
                        "aca": {
                            "name": "Aca",
                            "prompt_ref": "prompt/aca",
                            "default_model": "test-model",
                            "enabled_tools": ["restricted"],
                        }
                    },
                    "prompts": {
                        "prompt/aca": "You are Aca.",
                    },
                },
            }
        ),
        gateway=gateway,
        agent=ApprovalToolAgent(),
        tool_broker=broker,
    )

    components.app.install()
    await gateway.handler(_event())
    active = await components.run_manager.list_active()
    result = await components.app.approve_pending_approval(active[0].run_id)
    restored = await components.run_manager.get(active[0].run_id)

    assert result.ok is False
    assert result.run_status == "failed"
    assert "nested approval" in result.message
    assert restored is not None
    assert restored.status == "failed"


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


def test_build_runtime_components_ignores_legacy_prompt_assembly_config() -> None:
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

    assert isinstance(components.retrieval_planner, RetrievalPlanner)
    assert not hasattr(components.retrieval_planner, "config")


async def test_build_runtime_components_memory_broker_reads_self_and_sticky_file_sources(
    tmp_path: Path,
) -> None:
    config = Config(
        {
            "agent": {
                "default_model": "runtime-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "runtime_root": str(tmp_path / ".acabot-runtime"),
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    components.soul_source.append_today_entry("[qq:group:20002 time=1] 记录了部署任务")
    components.sticky_notes_source.create_note(
        scope="user",
        scope_key="qq:user:10001",
        key="reply_style",
        readonly_content="回答要更直接",
    )

    event = _event()
    decision = RouteDecision(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:user:10001",
    )
    thread = await components.thread_manager.get_or_create(
        thread_id=decision.thread_id,
        channel_scope=decision.channel_scope,
        last_event_at=event.timestamp,
    )
    run = await components.run_manager.open(event=event, decision=decision)
    ctx = RunContext(
        run=run,
        event=event,
        decision=decision,
        thread=thread,
        profile=components.profile_loader.load(decision),
        retrieval_plan=RetrievalPlan(
            requested_scopes=["user"],
            sticky_note_scopes=["user"],
            retained_history=[],
        ),
    )

    result = await components.memory_broker.retrieve(ctx)

    assert [source_id for source_id, _ in components.memory_broker.registry.items()] == [
        "self",
        "sticky_notes",
        "store_memory",
    ]
    assert [block.source for block in result.blocks[:2]] == ["self", "sticky_notes"]


async def test_build_runtime_components_wires_context_assembler_and_payload_writer(
    tmp_path: Path,
) -> None:
    config = Config(
        {
            "agent": {
                "default_model": "runtime-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "runtime_root": str(tmp_path / ".acabot-runtime"),
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    assert isinstance(components.context_assembler, ContextAssembler)
    assert isinstance(components.payload_json_writer, PayloadJsonWriter)
    assert components.payload_json_writer.root_dir == resolve_runtime_path(
        config,
        "debug/model-payloads",
    )


def test_build_payload_json_writer_uses_default_payload_json_dir(tmp_path: Path) -> None:
    config = Config(
        {
            "runtime": {
                "runtime_root": str(tmp_path / ".acabot-runtime"),
            }
        }
    )

    writer = build_payload_json_writer(config)

    assert writer.root_dir == resolve_runtime_path(config, "debug/model-payloads")


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
