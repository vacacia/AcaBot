from pathlib import Path

from acabot.config import Config
from acabot.runtime import (
    ResolvedAgent,
    AgentRuntimeResult,
    FileSystemModelRegistryManager,
    InMemoryToolAudit,
    ModelBinding,
    ModelPreset,
    ModelProvider,
    OpenAICompatibleProviderConfig,
    RouteDecision,
    ToolBroker,
    ToolPolicyDecision,
    build_agent_model_targets,
    build_runtime_components,
)
from acabot.agent import ToolSpec
from acabot.runtime.tool_broker import ToolExecutionContext
from acabot.types import EventSource, MsgSegment, StandardEvent

from ._agent_fakes import FakeAgent, FakeAgentResponse
from .test_outbox import FakeGateway


def _skills_dir() -> str:
    return str(Path(__file__).resolve().parent.parent / "fixtures" / "skills")


def _write_subagent(
    tmp_path: Path,
    *,
    name: str,
    description: str,
    tools: list[str],
    prompt: str,
    model_target: str | None = None,
) -> None:
    subagent_dir = tmp_path / ".agents" / "subagents" / name
    subagent_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        "tools:",
    ]
    for tool_name in tools:
        lines.append(f"  - {tool_name}")
    if model_target is not None:
        lines.append(f"model_target: {model_target}")
    lines.extend(
        [
            "---",
            prompt,
            "",
        ]
    )
    (subagent_dir / "SUBAGENT.md").write_text("\n".join(lines), encoding="utf-8")


def _write_session_bundle(
    tmp_path: Path,
    *,
    session_id: str,
    agent_id: str,
    prompt_ref: str,
    visible_skills: list[str] | None = None,
) -> None:
    platform, scope_kind, identifier = session_id.split(":", 2)
    bundle_dir = tmp_path / "sessions" / platform / scope_kind / identifier
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        "\n".join(
            [
                "session:",
                f"  id: {session_id}",
                "frontstage:",
                f"  agent_id: {agent_id}",
            ]
        ),
        encoding="utf-8",
    )
    (bundle_dir / "agent.yaml").write_text(
        "\n".join(
            [
                f"agent_id: {agent_id}",
                f"prompt_ref: {prompt_ref}",
                "visible_tools: []",
                "visible_skills:",
                *[f"  - {item}" for item in list(visible_skills or [])],
                "visible_subagents: []",
            ]
        ),
        encoding="utf-8",
    )


def _event(*, event_id: str = "evt:parent") -> StandardEvent:
    return StandardEvent(
        event_id=event_id,
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        segments=[MsgSegment(type="text", data={"text": "请处理这个任务"})],
        raw_message_id=f"msg:{event_id}",
        sender_nickname="acacia",
        sender_role=None,
    )


def _tool_ctx(*, run_id: str, agent) -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id=run_id,
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id=agent.agent_id,
        target=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        agent=agent,
        visible_subagents=["excel-worker"],
        metadata={
            "channel_scope": "qq:user:10001",
            "event_id": "evt:parent",
            "event_timestamp": 123,
            "platform": "qq",
            "message_type": "private",
            "visible_tools": ["delegate_subagent"],
            "visible_subagents": ["excel-worker"],
        },
    )


def _parent_agent(agent_id: str = "aca") -> ResolvedAgent:
    return ResolvedAgent(
        agent_id=agent_id,
        name=agent_id,
        prompt_ref=f"prompt/{agent_id}",
    )


def _write_prompt_file(
    tmp_path: Path,
    *,
    ref: str,
    body: str,
) -> None:
    prompts_dir = tmp_path / "prompts"
    parts = ref.split("/", 1)
    if len(parts) == 2:
        prompt_file = prompts_dir / f"{parts[1]}.md"
    else:
        prompt_file = prompts_dir / f"{ref}.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(body, encoding="utf-8")


def _runtime_config(tmp_path: Path) -> Config:
    _write_session_bundle(
        tmp_path,
        session_id="qq:user:10001",
        agent_id="aca",
        prompt_ref="prompt/aca",
        visible_skills=["sample_configured_skill"],
    )
    _write_session_bundle(
        tmp_path,
        session_id="qq:user:20002",
        agent_id="worker",
        prompt_ref="prompt/worker",
    )
    _write_prompt_file(tmp_path, ref="prompt/aca", body="You are Aca.")
    _write_prompt_file(tmp_path, ref="prompt/worker", body="You are Worker.")
    return Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "filesystem": {
                    "base_dir": str(tmp_path),
                    "sessions_dir": "sessions",
                    "skill_catalog_dirs": [_skills_dir()],
                    "subagent_catalog_dirs": [str(tmp_path / ".agents" / "subagents")],
                },
                "skills": ["sample_configured_skill"],
                "plugins": [
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                ],
            },
        }
    )


async def _model_registry_manager(
    tmp_path,
    *,
    agent_models: dict[str, str] | None = None,
) -> FileSystemModelRegistryManager:
    models = dict(agent_models or {"aca": "gpt-parent", "worker": "gpt-worker"})
    manager = FileSystemModelRegistryManager(
        providers_dir=tmp_path / "providers",
        presets_dir=tmp_path / "presets",
        bindings_dir=tmp_path / "bindings",
    )
    manager.target_catalog.replace_agent_targets(
        build_agent_model_targets(
            [
                ResolvedAgent(
                    agent_id=agent_id,
                    name=agent_id,
                    prompt_ref=f"prompt/{agent_id}",
                )
                for agent_id in models
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
    for agent_id, model in models.items():
        preset_id = f"{agent_id}-main"
        await manager.upsert_preset(
            ModelPreset(
                preset_id=preset_id,
                provider_id="openai-main",
                model=model,
                task_kind="chat",
                capabilities=["tool_calling"],
                context_window=32000,
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


async def test_delegate_subagent_uses_subagent_prompt_body(tmp_path) -> None:
    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="Excel worker",
        tools=["sample_configured_tool"],
        prompt="You are Excel Worker.",
    )
    prompts_dir = tmp_path / "prompts" / "subagent"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "excel-worker.md").write_text(
        "Legacy prompt file should never win.",
        encoding="utf-8",
    )
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="worker summary", model_used="gpt-parent"))
    components = build_runtime_components(
        _runtime_config(tmp_path),
        gateway=gateway,
        agent=agent,
        model_registry_manager=await _model_registry_manager(tmp_path),
    )
    await components.plugin_manager.ensure_started()

    parent_run = await components.run_manager.open(
        event=_event(),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
    )
    profile = _parent_agent("aca")

    result = await components.tool_broker.execute(
        tool_name="delegate_subagent",
        arguments={
            "delegate_agent_id": "excel-worker",
            "task": "整理 Excel 文件并总结",
        },
        ctx=_tool_ctx(run_id=parent_run.run_id, agent=profile),
    )

    assert result.raw["ok"] is True
    assert "You are Excel Worker." in agent.calls[-1]["system_prompt"]
    assert "Legacy prompt file should never win." not in agent.calls[-1]["system_prompt"]
    assert agent.calls[-1]["model"] == "openai/gpt-parent"
    child_run = await components.run_manager.get(str(result.raw["delegated_run_id"]))
    assert child_run is not None
    assert child_run.agent_id == "subagent:excel-worker"
    assert child_run.metadata["delegate_agent_id"] == "excel-worker"


async def test_delegate_subagent_uses_manifest_model_target_override(
    tmp_path,
) -> None:
    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="Excel worker",
        tools=["sample_configured_tool"],
        prompt="You are Excel Worker.",
        model_target="agent:worker",
    )
    agent = FakeAgent(FakeAgentResponse(text="worker summary", model_used="gpt-worker"))
    components = build_runtime_components(
        _runtime_config(tmp_path),
        gateway=FakeGateway(),
        agent=agent,
        model_registry_manager=await _model_registry_manager(tmp_path),
    )
    await components.plugin_manager.ensure_started()

    parent_run = await components.run_manager.open(
        event=_event(),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
    )
    profile = _parent_agent("aca")

    result = await components.tool_broker.execute(
        tool_name="delegate_subagent",
        arguments={
            "delegate_agent_id": "excel-worker",
            "task": "整理 Excel 文件并总结",
        },
        ctx=_tool_ctx(run_id=parent_run.run_id, agent=profile),
    )

    child_run = await components.run_manager.get(str(result.raw["delegated_run_id"]))

    assert child_run is not None
    assert child_run.metadata["model_snapshot"]["binding_id"] == "binding:worker"
    assert child_run.metadata["model_snapshot"]["provider_id"] == "openai-main"
    assert child_run.metadata["model_snapshot"]["preset_id"] == "worker-main"
    assert agent.calls[-1]["model"] == "openai/gpt-worker"
    assert agent.calls[-1]["request_options"]["api_base"] == "https://example.invalid/v1"
    assert agent.calls[-1]["request_options"]["provider_kind"] == "openai_compatible"


async def test_delegate_subagent_builds_subagent_computer_policy(tmp_path) -> None:
    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="Excel worker",
        tools=["sample_configured_tool"],
        prompt="You are Excel Worker.",
    )
    components = build_runtime_components(
        _runtime_config(tmp_path),
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="worker summary", model_used="gpt-parent")),
    )
    await components.plugin_manager.ensure_started()

    captured = {}

    async def fake_execute(ctx, deliver_actions: bool = True):
        captured["ctx"] = ctx
        _ = deliver_actions
        ctx.response = AgentRuntimeResult(status="completed", text="worker summary")
        await components.run_manager.mark_completed(ctx.run.run_id)

    components.pipeline.execute = fake_execute  # type: ignore[method-assign]

    parent_run = await components.run_manager.open(
        event=_event(),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
    )
    profile = _parent_agent("aca")

    result = await components.tool_broker.execute(
        tool_name="delegate_subagent",
        arguments={
            "delegate_agent_id": "excel-worker",
            "task": "整理 Excel 文件并总结",
        },
        ctx=_tool_ctx(run_id=parent_run.run_id, agent=profile),
    )

    assert result.raw["ok"] is True
    child_ctx = captured["ctx"]
    assert child_ctx.agent.agent_id == "subagent:excel-worker"
    assert child_ctx.agent.prompt_ref == "subagent/excel-worker"
    assert child_ctx.agent.enabled_tools == ["sample_configured_tool"]
    assert child_ctx.computer_policy_decision is not None
    assert child_ctx.computer_policy_decision.actor_kind == "subagent"
    assert child_ctx.computer_policy_decision.roots["self"]["visible"] is False


async def test_subagent_can_use_plugin_tool_when_subagent_definition_enables_it(
    tmp_path: Path,
) -> None:
    class PluginToolCallingAgent:
        def __init__(self) -> None:
            self.tool_results = []

        async def run(
            self,
            system_prompt: str,
            messages,
            model: str | None = None,
            *,
            request_options=None,
            max_tool_rounds=None,
            tools=None,
            tool_executor=None,
        ):
            _ = system_prompt, messages, model, request_options, max_tool_rounds
            assert tools is not None
            assert tool_executor is not None
            execution = await tool_executor(
                "sample_configured_tool",
                {"text": "plugin says hi"},
            )
            self.tool_results.append(execution)
            return FakeAgentResponse(text=str(execution.raw["echo"]), model_used=str(model or ""))

    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="Excel worker",
        tools=["sample_configured_tool"],
        prompt="You are Excel Worker.",
    )
    agent = PluginToolCallingAgent()
    components = build_runtime_components(
        _runtime_config(tmp_path),
        gateway=FakeGateway(),
        agent=agent,
        model_registry_manager=await _model_registry_manager(tmp_path),
    )
    await components.plugin_manager.ensure_started()

    parent_run = await components.run_manager.open(
        event=_event(),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
    )
    profile = _parent_agent("aca")

    result = await components.tool_broker.execute(
        tool_name="delegate_subagent",
        arguments={
            "delegate_agent_id": "excel-worker",
            "task": "调用 plugin tool",
        },
        ctx=_tool_ctx(run_id=parent_run.run_id, agent=profile),
    )

    assert result.raw["ok"] is True
    assert result.raw["summary"] == "plugin says hi"
    assert agent.tool_results[0].raw["echo"] == "plugin says hi"


async def test_subagent_child_run_cannot_enter_waiting_approval(tmp_path: Path) -> None:
    class ApprovalPolicy:
        async def allow(self, *, spec, arguments, ctx) -> ToolPolicyDecision:
            _ = arguments, ctx
            if spec.name == "restricted":
                return ToolPolicyDecision(
                    allowed=True,
                    requires_approval=True,
                    reason="needs admin approval",
                )
            return ToolPolicyDecision(allowed=True)

    class ApprovalToolAgent:
        async def run(
            self,
            system_prompt: str,
            messages,
            model: str | None = None,
            *,
            request_options=None,
            max_tool_rounds=None,
            tools=None,
            tool_executor=None,
        ):
            _ = system_prompt, messages, model, request_options, max_tool_rounds, tools
            assert tool_executor is not None
            await tool_executor("restricted", {"danger": True})
            raise AssertionError("approval interrupt should stop the subagent tool loop")

    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="Excel worker",
        tools=["restricted"],
        prompt="You are Excel Worker.",
    )
    audit = InMemoryToolAudit()
    broker = ToolBroker(policy=ApprovalPolicy(), audit=audit)

    async def restricted(arguments: dict[str, object], ctx) -> dict[str, object]:
        _ = arguments, ctx
        return {"ok": True}

    broker.register_tool(
        ToolSpec(
            name="restricted",
            description="Restricted tool",
            parameters={"type": "object", "properties": {}},
        ),
        restricted,
    )
    components = build_runtime_components(
        _runtime_config(tmp_path),
        gateway=FakeGateway(),
        agent=ApprovalToolAgent(),
        tool_broker=broker,
        model_registry_manager=await _model_registry_manager(tmp_path),
    )
    await components.plugin_manager.ensure_started()

    parent_run = await components.run_manager.open(
        event=_event(),
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
    )
    profile = _parent_agent("aca")

    result = await components.tool_broker.execute(
        tool_name="delegate_subagent",
        arguments={
            "delegate_agent_id": "excel-worker",
            "task": "触发审批工具",
        },
        ctx=_tool_ctx(run_id=parent_run.run_id, agent=profile),
    )

    restricted_record = next(
        record for record in audit.records.values() if record.tool_name == "restricted"
    )
    child_run = await components.run_manager.get(restricted_record.run_id)

    assert result.raw["ok"] is False
    assert "cannot enter waiting_approval" in str(result.raw["error"])
    assert child_run is not None
    assert child_run.status == "failed"
    assert restricted_record.status == "failed"


async def test_bootstrap_no_longer_registers_local_profiles_as_subagents(tmp_path) -> None:
    components = build_runtime_components(
        _runtime_config(tmp_path),
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    assert not hasattr(components, "subagent_executor_registry")
