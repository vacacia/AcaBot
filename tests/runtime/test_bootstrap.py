"""bootstrap 组装测试.

这一组测试验证默认 runtime 组件树是否按配置正确装配.
当前主线已经切到 `ModelAgentRuntime`, 因此这里的 fake agent 只需要满足
新的 `BaseAgent.run()` duck-typed 形状.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import shutil

import pytest

from acabot.agent import ToolDef, ToolSpec
from acabot.config import Config
from acabot.runtime import (
    ApprovalRequired,
    ResolvedAgent,
    LtmMemorySource,
    ContextAssembler,
    ContextCompactor,
    FileSystemModelRegistryManager,
    LongTermMemoryIngestor,
    ModelContextSummarizer,
    ModelBinding,
    ModelPreset,
    ModelProvider,
    OpenAICompatibleProviderConfig,
    PayloadJsonWriter,
    RetrievalPlan,
    RunContext,
    RuntimePlugin,
    RuntimePluginContext,
    RuntimePluginManager,
    RetrievalPlanner,
    RouteDecision,
    SQLiteChannelEventStore,
    StickyNoteRecord,
    SQLiteMessageStore,
    StoreBackedRunManager,
    StoreBackedThreadManager,
    ToolPolicyDecision,
    ToolBroker,
    build_agent_model_targets,
    build_runtime_components,
)
from acabot.runtime.memory.long_term_memory.storage import LanceDbLongTermMemoryStore
from acabot.runtime.contracts import PendingApproval
from acabot.runtime.bootstrap.builders import build_payload_json_writer
from acabot.runtime.bootstrap.config import resolve_runtime_path
from acabot.types import EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway
from .test_outbox import RecordingIngestor
from .test_pipeline_runtime import ApprovalToolAgent


def _write_minimal_session(
    base_dir: Path,
    *,
    agent_id: str = "aca",
    prompt_ref: str = "prompt/default",
    prompt_text: str = "You are Aca.",
    visible_tools: list[str] | None = None,
    visible_skills: list[str] | None = None,
    visible_subagents: list[str] | None = None,
) -> None:
    """在 base_dir 下写入最小 session+agent+prompt 文件供 build_runtime_components 使用."""
    import yaml as _yaml

    session_dir = base_dir / "sessions" / "qq" / "user" / "10001"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.yaml").write_text(
        f"session:\n  id: qq:user:10001\n  template: qq_user\nfrontstage:\n  agent_id: {agent_id}\nsurfaces:\n  message.private:\n    admission:\n      default:\n        mode: respond\n",
        encoding="utf-8",
    )
    agent_data = {
        "agent_id": agent_id,
        "prompt_ref": prompt_ref,
        "visible_tools": visible_tools or [],
        "visible_skills": visible_skills or [],
        "visible_subagents": visible_subagents or [],
    }
    (session_dir / "agent.yaml").write_text(
        _yaml.dump(agent_data, default_flow_style=False),
        encoding="utf-8",
    )
    # Write the prompt file
    parts = prompt_ref.replace("prompt/", "", 1).split("/")
    prompts_dir = base_dir / "prompts"
    for p in parts[:-1]:
        prompts_dir = prompts_dir / p
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / f"{parts[-1]}.md").write_text(prompt_text, encoding="utf-8")


def _fs_config(tmp_path: Path, extra: dict | None = None) -> Config:
    """构造带 filesystem 基目录的最小 Config."""
    _write_minimal_session(tmp_path)
    base = {
        "agent": {"system_prompt": "You are Aca."},
        "runtime": {
            "filesystem": {"base_dir": str(tmp_path)},
        },
    }
    if extra:
        for key, val in extra.items():
            if key == "runtime" and isinstance(val, dict):
                base["runtime"].update(val)
            else:
                base[key] = val
    return Config(base)


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


def _config_with_long_term_memory(tmp_path: Path) -> Config:
    return Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "runtime_root": str(tmp_path / "runtime_data"),
                "long_term_memory": {
                    "enabled": True,
                },
            },
        }
    )


async def _model_registry_manager(
    tmp_path: Path,
    *,
    agent_models: dict[str, str],
) -> FileSystemModelRegistryManager:
    manager = FileSystemModelRegistryManager(
        providers_dir=tmp_path / "models/providers",
        presets_dir=tmp_path / "models/presets",
        bindings_dir=tmp_path / "models/bindings",
    )
    manager.target_catalog.replace_agent_targets(
        build_agent_model_targets(
            [
                ResolvedAgent(
                    agent_id=agent_id,
                    name=agent_id,
                    prompt_ref=f"prompt/{agent_id}",
                )
                for agent_id in agent_models
            ]
        )
    )
    await manager.upsert_provider(
        ModelProvider(
            provider_id="openai-main",
            kind="openai_compatible",
            config=OpenAICompatibleProviderConfig(
                base_url="https://example.invalid/v1",
                api_key_env="OPENAI_API_KEY",
            ),
        )
    )
    for agent_id, model in agent_models.items():
        preset_id = f"{agent_id}-main"
        await manager.upsert_preset(
            ModelPreset(
                preset_id=preset_id,
                provider_id="openai-main",
                model=model,
                task_kind="chat",
                capabilities=["tool_calling"],
                context_window=128000,
            )
        )
        await manager.upsert_binding(
            ModelBinding(
                binding_id=f"binding:{agent_id}",
                target_id=f"agent:{agent_id}",
                preset_ids=[preset_id],
            )
        )
    return manager


def test_build_runtime_components_uses_runtime_profiles_and_prompts(tmp_path: Path) -> None:
    # Set up filesystem session config
    session_dir = tmp_path / "sessions" / "qq" / "user" / "10001"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.yaml").write_text(
        "session:\n  id: qq:user:10001\n  template: qq_user\nfrontstage:\n  agent_id: aca\nsurfaces:\n  message.private:\n    admission:\n      default:\n        mode: respond\n",
        encoding="utf-8",
    )
    (session_dir / "agent.yaml").write_text(
        "agent_id: aca\nname: Aca\nprompt_ref: prompt/aca\nvisible_tools: []\nvisible_skills: []\nvisible_subagents: []\n",
        encoding="utf-8",
    )
    # Set up prompts
    prompts_dir = tmp_path / "prompts" / "aca"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "index.md").write_text("You are Aca.", encoding="utf-8")

    config = Config(
        {
            "agent": {
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "filesystem": {
                    "base_dir": str(tmp_path),
                    "sessions_dir": "sessions",
                    "prompts_dir": "prompts",
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
    profile = components.agent_loader(decision)

    assert components.prompt_loader.load("prompt/aca") == "You are Aca."
    assert profile.name == "aca"
    assert not hasattr(profile, "default_model")


async def test_build_runtime_components_runs_app_with_model_agent_runtime(tmp_path: Path) -> None:
    _write_minimal_session(tmp_path)
    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "filesystem": {"base_dir": str(tmp_path)},
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="hello back", model_used="test-model"))
    components = build_runtime_components(
        config,
        gateway=gateway,
        agent=agent,
        model_registry_manager=await _model_registry_manager(tmp_path, agent_models={"aca": "test-model"}),
    )

    components.app.install()
    await gateway.handler(_event())

    assert agent.calls[0]["system_prompt"] == "You are Aca."
    assert agent.calls[0]["model"] == "openai/test-model"
    assert components.pipeline.tool_broker is components.tool_broker
    assert components.pipeline.memory_broker is components.memory_broker


def test_build_runtime_components_wires_optional_long_term_memory_ingestor(tmp_path: Path) -> None:
    _write_minimal_session(tmp_path)
    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "filesystem": {"base_dir": str(tmp_path)},
            },
        }
    )
    ingestor = RecordingIngestor()

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
        long_term_memory_ingestor=ingestor,
    )

    assert components.long_term_memory_ingestor is ingestor
    assert components.app.long_term_memory_ingestor is ingestor
    assert components.outbox.long_term_memory_ingestor is ingestor


async def test_build_runtime_components_registers_long_term_memory_source_and_ingestor(
    tmp_path: Path,
) -> None:
    components = build_runtime_components(
        _config_with_long_term_memory(tmp_path),
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    source = components.memory_broker.registry.get("long_term_memory")

    assert isinstance(components.long_term_memory_ingestor, LongTermMemoryIngestor)
    assert isinstance(source, LtmMemorySource)
    assert isinstance(source.store, LanceDbLongTermMemoryStore)
    assert [source_id for source_id, _ in components.memory_broker.registry.items()] == [
        "self",
        "sticky_notes",
        "long_term_memory",
    ]
    assert components.app.long_term_memory_ingestor is components.long_term_memory_ingestor
    assert components.outbox.long_term_memory_ingestor is components.long_term_memory_ingestor


async def test_build_runtime_components_accepts_runtime_plugins(tmp_path: Path) -> None:
    _write_minimal_session(tmp_path)
    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "filesystem": {"base_dir": str(tmp_path)},
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


async def test_build_runtime_components_loads_runtime_plugins_from_config(tmp_path: Path) -> None:
    from tests.runtime.runtime_plugin_samples import SampleConfiguredRuntimePlugin

    SampleConfiguredRuntimePlugin.reset()
    _write_minimal_session(tmp_path)
    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "filesystem": {"base_dir": str(tmp_path)},
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


async def test_build_runtime_components_exposes_skill_tool_and_empty_subagent_catalog(tmp_path: Path) -> None:
    skills_dir = Path(__file__).resolve().parent.parent / "fixtures" / "skills"
    _write_minimal_session(tmp_path, agent_id="aca", prompt_ref="prompt/aca", prompt_text="You are Aca.")
    # Write agent.yaml with skills
    agent_yaml = tmp_path / "sessions" / "qq" / "user" / "10001" / "agent.yaml"
    agent_yaml.write_text(
        "agent_id: aca\nprompt_ref: prompt/aca\nvisible_tools: []\nvisible_skills:\n  - sample_configured_skill\nvisible_subagents: []\n",
        encoding="utf-8",
    )
    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "filesystem": {
                    "base_dir": str(tmp_path),
                    "skill_catalog_dirs": [str(skills_dir)],
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

    profile = components.agent_loader(
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
    assert components.subagent_catalog.list_all() == []
    assert not hasattr(components, "subagent_executor_registry")
    assert any(tool.name == "Skill" for tool in visible_tools)


async def test_build_runtime_components_loads_profiles_and_prompts_from_filesystem(
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "aca.md").write_text("You are Aca from filesystem.", encoding="utf-8")
    # Write session bundle with agent config
    session_dir = tmp_path / "sessions" / "qq" / "user" / "10001"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.yaml").write_text(
        "session:\n  id: qq:user:10001\n  template: qq_user\nfrontstage:\n  agent_id: aca\nsurfaces:\n  message.private:\n    admission:\n      default:\n        mode: respond\n",
        encoding="utf-8",
    )
    (session_dir / "agent.yaml").write_text(
        "agent_id: aca\nprompt_ref: prompt/aca\nvisible_tools: []\nvisible_skills: []\nvisible_subagents: []\n",
        encoding="utf-8",
    )
    config = Config(
        {
            "agent": {
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "filesystem": {
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

    profile = components.agent_loader(decision)
    prompt = components.prompt_loader.load("prompt/aca")

    assert prompt == "You are Aca from filesystem."


async def test_build_runtime_components_backend_status_exposes_session_path(tmp_path: Path) -> None:
    _write_minimal_session(tmp_path)
    config = Config(
        {
            "agent": {
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "filesystem": {"base_dir": str(tmp_path)},
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
    assert backend_status.session_path.endswith("runtime_data/backend/session.json")


_has_pi = shutil.which("pi") is not None


@pytest.mark.skipif(not _has_pi, reason="pi binary not available")
async def test_build_runtime_components_constructs_configured_backend_service_when_enabled(
    tmp_path: Path,
) -> None:
    config = Config(
        {
            "agent": {
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "runtime_root": str(tmp_path / "runtime_data"),
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
    assert backend_status.session_path == str((tmp_path / "runtime_data" / "backend" / "session.json").resolve())
    assert components.backend_bridge.session.adapter.cwd == config.base_dir()

    await components.backend_bridge.session.adapter.dispose()


async def test_build_runtime_components_uses_default_bot_admin_actor_ids_for_backend_access(
    tmp_path: Path,
) -> None:
    config = Config(
        {
            "agent": {
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "runtime_root": str(tmp_path / "runtime_data"),
                "backend": {
                    "enabled": False,
                    "admin_actor_ids": ["qq:private:123456"],
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


@pytest.mark.skipif(not _has_pi, reason="pi binary not available")
async def test_build_runtime_components_uses_explicit_backend_cwd_when_configured(
    tmp_path: Path,
) -> None:
    backend_cwd = tmp_path / "repo-root"
    backend_cwd.mkdir()
    config = Config(
        {
            "agent": {
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "runtime_root": str(tmp_path / "runtime_data"),
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
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "runtime_root": str(tmp_path / "runtime_data"),
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

    assert backend_status.session_path == str((tmp_path / "runtime_data" / "backend" / "session.json").resolve())


async def test_build_runtime_components_invalid_backend_command_stays_unconfigured(
    tmp_path: Path,
) -> None:
    config = Config(
        {
            "agent": {
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
                "runtime_root": str(tmp_path / "runtime_data"),
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
    assert backend_status.session_path == str((tmp_path / "runtime_data" / "backend" / "session.json").resolve())


async def test_build_runtime_components_exposes_control_plane() -> None:
    config = Config(
        {
            "agent": {
                "system_prompt": "Fallback prompt.",
            },
            "runtime": {
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
    session_dir = tmp_path / "sessions/qq/group/42"
    session_dir.mkdir(parents=True)
    (session_dir / "session.yaml").write_text(
        """
session:
  id: qq:group:42
  template: qq_group
frontstage:
  agent_id: ops
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
    (session_dir / "agent.yaml").write_text(
        """
agent_id: ops
prompt_ref: "prompt/ops"
visible_tools: []
visible_skills: []
visible_subagents: []
""".strip(),
        encoding="utf-8",
    )
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "aca.md").write_text("You are Aca.", encoding="utf-8")
    (prompts_dir / "ops.md").write_text("You are Ops.", encoding="utf-8")
    (prompts_dir / "default.md").write_text("You are a helpful assistant.", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
runtime:
  filesystem:
    base_dir: .
    sessions_dir: sessions
    prompts_dir: prompts
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
    assert {
        key: value
        for key, value in decision.metadata.items()
        if key.startswith("event_")
    } == {
        "event_persist": True,
        "event_tags": ["mention"],
    }













async def test_build_runtime_components_wires_tool_broker_into_agent_runtime(tmp_path: Path) -> None:
    _write_minimal_session(tmp_path, agent_id="aca", prompt_ref="prompt/aca", prompt_text="You are Aca.")
    # Overwrite agent.yaml with visible_tools
    agent_yaml = tmp_path / "sessions" / "qq" / "user" / "10001" / "agent.yaml"
    agent_yaml.write_text(
        "agent_id: aca\nprompt_ref: prompt/aca\nvisible_tools:\n  - get_time\nvisible_skills: []\nvisible_subagents: []\n",
        encoding="utf-8",
    )
    config = Config(
        {
            "agent": {"system_prompt": "You are Aca."},
            "runtime": {"filesystem": {"base_dir": str(tmp_path)}},
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
        model_registry_manager=await _model_registry_manager(tmp_path, agent_models={"aca": "runtime-model"}),
    )

    components.app.install()
    await gateway.handler(_event())

    assert components.tool_broker is broker
    assert agent.calls[0]["tools"][0].name == "get_time"


async def test_build_runtime_components_registers_builtin_computer_tools(tmp_path: Path) -> None:
    _write_minimal_session(tmp_path, agent_id="aca", prompt_ref="prompt/aca", prompt_text="You are Aca.", visible_tools=["read"])
    config = Config(
        {
            "agent": {"system_prompt": "You are Aca."},
            "runtime": {"filesystem": {"base_dir": str(tmp_path)}},
        }
    )
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await components.plugin_manager.ensure_started()
    profile = components.agent_loader(
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
    assert sources["sticky_note_read"] == "builtin:sticky_notes"
    assert sources["sticky_note_append"] == "builtin:sticky_notes"
    assert "exec" not in sources
    assert [tool.name for tool in visible] == ["read"]


async def test_build_runtime_components_drops_stale_tools_from_removed_computer_adapter(tmp_path: Path) -> None:
    _write_minimal_session(tmp_path, agent_id="aca", prompt_ref="prompt/aca", prompt_text="You are Aca.", visible_tools=["read"])
    config = Config(
        {
            "agent": {"system_prompt": "You are Aca."},
            "runtime": {"filesystem": {"base_dir": str(tmp_path)}},
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
    profile = components.agent_loader(
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


async def test_build_runtime_components_drops_stale_builtin_plugins_from_reused_plugin_manager(tmp_path: Path) -> None:
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

    _write_minimal_session(tmp_path, agent_id="aca", prompt_ref="prompt/aca", prompt_text="You are Aca.", visible_tools=["read"])
    config = Config(
        {
            "agent": {"system_prompt": "You are Aca."},
            "runtime": {"filesystem": {"base_dir": str(tmp_path)}},
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
    profile = components.agent_loader(
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


async def test_build_runtime_components_rejects_started_plugin_manager(tmp_path: Path) -> None:
    _write_minimal_session(tmp_path, agent_id="aca", prompt_ref="prompt/aca", prompt_text="You are Aca.", visible_tools=["read"])
    config = Config(
        {
            "agent": {"system_prompt": "You are Aca."},
            "runtime": {"filesystem": {"base_dir": str(tmp_path)}},
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


async def test_build_runtime_components_full_plugin_reload_keeps_builtin_plugins(tmp_path: Path) -> None:
    skills_dir = Path(__file__).resolve().parent.parent / "fixtures" / "skills"
    _write_minimal_session(tmp_path, agent_id="aca", prompt_ref="prompt/aca", prompt_text="You are Aca.", visible_tools=["read"], visible_skills=["sample_configured_skill"])
    config = Config(
        {
            "agent": {"system_prompt": "You are Aca."},
            "runtime": {
                "filesystem": {
                    "base_dir": str(tmp_path),
                    "skill_catalog_dirs": [str(skills_dir)],
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
    profile = components.agent_loader(
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


async def test_build_runtime_components_reload_keeps_conditional_subagent_delegation_builtin(tmp_path: Path) -> None:
    skills_dir = Path(__file__).resolve().parent.parent / "fixtures" / "skills"
    _write_minimal_session(tmp_path, agent_id="aca", prompt_ref="prompt/aca", prompt_text="You are Aca.", visible_skills=["sample_configured_skill"])
    config = Config(
        {
            "agent": {"system_prompt": "You are Aca."},
            "runtime": {
                "filesystem": {
                    "base_dir": str(tmp_path),
                    "skill_catalog_dirs": [str(skills_dir)],
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
    profile = components.agent_loader(
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
    assert sources["delegate_subagent"] == "builtin:subagents"
    assert "delegate_subagent" not in [tool.name for tool in visible]


async def test_build_runtime_components_default_approval_resume_replays_tool_call(tmp_path: Path) -> None:
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
    _write_minimal_session(tmp_path, agent_id="aca", prompt_ref="prompt/aca", prompt_text="You are Aca.", visible_tools=["restricted"])
    components = build_runtime_components(
        Config(
            {
                "agent": {"system_prompt": "You are Aca."},
                "runtime": {"filesystem": {"base_dir": str(tmp_path)}},
            }
        ),
        gateway=gateway,
        agent=ApprovalToolAgent(),
        tool_broker=broker,
        model_registry_manager=await _model_registry_manager(tmp_path, agent_models={"aca": "test-model"}),
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


async def test_build_runtime_components_approval_resume_marks_completed_with_errors_for_undelivered_outputs(
    tmp_path: Path,
) -> None:
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
    _write_minimal_session(tmp_path, agent_id="aca", prompt_ref="prompt/aca", prompt_text="You are Aca.", visible_tools=["restricted"])
    components = build_runtime_components(
        Config(
            {
                "agent": {"system_prompt": "You are Aca."},
                "runtime": {"filesystem": {"base_dir": str(tmp_path)}},
            }
        ),
        gateway=gateway,
        agent=ApprovalToolAgent(),
        tool_broker=broker,
        model_registry_manager=await _model_registry_manager(tmp_path, agent_models={"aca": "test-model"}),
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


async def test_build_runtime_components_approval_resume_fails_closed_on_nested_approval(
    tmp_path: Path,
) -> None:
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
    _write_minimal_session(tmp_path, agent_id="aca", prompt_ref="prompt/aca", prompt_text="You are Aca.", visible_tools=["restricted"])
    components = build_runtime_components(
        Config(
            {
                "agent": {"system_prompt": "You are Aca."},
                "runtime": {"filesystem": {"base_dir": str(tmp_path)}},
            }
        ),
        gateway=gateway,
        agent=ApprovalToolAgent(),
        tool_broker=broker,
        model_registry_manager=await _model_registry_manager(tmp_path, agent_models={"aca": "test-model"}),
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
    _write_minimal_session(tmp_path)
    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "filesystem": {"base_dir": str(tmp_path)},
                "persistence": {
                    "sqlite_path": str(sqlite_path),
                },
            },
        }
    )
    gateway1 = FakeGateway()
    agent1 = FakeAgent(FakeAgentResponse(text="hello back", model_used="test-model"))
    model_registry_manager = await _model_registry_manager(tmp_path, agent_models={"aca": "test-model"})
    components1 = build_runtime_components(
        config,
        gateway=gateway1,
        agent=agent1,
        model_registry_manager=model_registry_manager,
    )

    assert isinstance(components1.thread_manager, StoreBackedThreadManager)
    assert isinstance(components1.run_manager, StoreBackedRunManager)
    assert isinstance(components1.message_store, SQLiteMessageStore)
    assert isinstance(components1.channel_event_store, SQLiteChannelEventStore)

    components1.app.install()
    await gateway1.handler(_event())

    gateway2 = FakeGateway()
    agent2 = FakeAgent(FakeAgentResponse(text="hello again", model_used="test-model"))
    components2 = build_runtime_components(
        config,
        gateway=gateway2,
        agent=agent2,
        model_registry_manager=model_registry_manager,
    )
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


def test_build_runtime_components_ignores_legacy_prompt_assembly_config() -> None:
    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
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
    _write_minimal_session(tmp_path)
    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "filesystem": {"base_dir": str(tmp_path)},
                "runtime_root": str(tmp_path / "runtime_data"),
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    components.soul_source.append_today_entry("[qq:group:20002 time=1] 记录了部署任务")
    components.sticky_notes_source.save_record(
        StickyNoteRecord(
            entity_ref="qq:user:10001",
            readonly="回答要更直接",
        )
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
        agent=components.agent_loader(decision),
        retrieval_plan=RetrievalPlan(
            sticky_note_targets=["qq:user:10001"],
            retained_history=[],
        ),
    )

    result = await components.memory_broker.retrieve(ctx)

    assert [source_id for source_id, _ in components.memory_broker.registry.items()] == [
        "self",
        "sticky_notes",
    ]
    assert [block.source for block in result.blocks[:2]] == ["self", "sticky_notes"]


async def test_build_runtime_components_wires_context_assembler_and_payload_writer(
    tmp_path: Path,
) -> None:
    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "runtime_root": str(tmp_path / "runtime_data"),
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
        "debug/model_payloads",
    )


def test_build_payload_json_writer_uses_default_payload_json_dir(tmp_path: Path) -> None:
    config = Config(
        {
            "runtime": {
                "runtime_root": str(tmp_path / "runtime_data"),
            }
        }
    )

    writer = build_payload_json_writer(config)

    assert writer.root_dir == resolve_runtime_path(config, "debug/model_payloads")


def test_build_runtime_components_applies_context_compaction_config() -> None:
    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
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

