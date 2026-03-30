from pathlib import Path

from acabot.config import Config
from acabot.runtime import (
    ResolvedAgent,
    AgentRuntimeResult,
    ComputerPolicyDecision,
    FileSystemModelRegistryManager,
    ModelBinding,
    ModelPreset,
    ModelProvider,
    OpenAICompatibleProviderConfig,
    RouteDecision,
    RunContext,
    RunRecord,
    ThreadState,
    build_agent_model_targets,
    build_runtime_components,
)
from acabot.runtime.tool_broker import ToolExecutionContext
from acabot.types import EventSource, MsgSegment, StandardEvent

from ._agent_fakes import FakeAgent, FakeAgentResponse
from .test_outbox import FakeGateway


def _frontstage_agent(agent_id: str) -> ResolvedAgent:
    return ResolvedAgent(
        agent_id=agent_id,
        name=agent_id,
        prompt_ref=f"prompt/{agent_id}",
    )


def _write_subagent(
    tmp_path: Path,
    *,
    name: str,
    description: str,
    tools: list[str],
    prompt: str,
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
                "visible_skills: []",
                "visible_subagents: []",
            ]
        ),
        encoding="utf-8",
    )


def _event() -> StandardEvent:
    return StandardEvent(
        event_id="evt:parent",
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
        raw_message_id="msg:evt:parent",
        sender_nickname="acacia",
        sender_role=None,
    )


def _runtime_config(tmp_path: Path) -> Config:
    _write_session_bundle(
        tmp_path,
        session_id="qq:user:10001",
        agent_id="aca",
        prompt_ref="prompt/aca",
    )
    _write_session_bundle(
        tmp_path,
        session_id="qq:user:20002",
        agent_id="worker",
        prompt_ref="prompt/worker",
    )
    return Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_agent_name": "Aca",
                "default_prompt_ref": "prompt/aca",
                "filesystem": {
                    "enabled": True,
                    "base_dir": str(tmp_path),
                    "sessions_dir": "sessions",
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                    "prompt/worker": "You are Worker.",
                },
            },
        }
    )


async def _model_registry_manager(
    tmp_path: Path,
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


def _run_ctx(
    components,
    *,
    agent: ResolvedAgent,
    visible_subagents: list[str],
    actor_kind: str = "frontstage_agent",
) -> RunContext:
    event = _event()
    decision = RouteDecision(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id=agent.agent_id,
        channel_scope="qq:user:10001",
        computer_policy_decision=ComputerPolicyDecision(
            actor_kind=actor_kind,
            backend="host",
            allow_exec=True,
            allow_sessions=True,
            roots={
                "workspace": {"visible": True},
                "skills": {"visible": True},
                "self": {"visible": True},
            },
            visible_subagents=list(visible_subagents),
        ),
    )
    return RunContext(
        run=RunRecord(
            run_id="run:1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id=agent.agent_id,
            trigger_event_id=event.event_id,
            status="running",
            started_at=event.timestamp,
        ),
        event=event,
        decision=decision,
        thread=ThreadState(
            thread_id="qq:user:10001",
            channel_scope="qq:user:10001",
        ),
        agent=agent,
        computer_policy_decision=decision.computer_policy_decision,
    )


def _tool_ctx(
    *,
    agent: ResolvedAgent,
    visible_subagents: list[str],
) -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id="run:1",
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
        visible_subagents=list(visible_subagents),
        metadata={
            "channel_scope": "qq:user:10001",
            "platform": "qq",
            "message_type": "private",
            "visible_tools": ["delegate_subagent"],
        },
    )


async def test_delegate_subagent_hidden_when_session_visible_subagents_is_empty(tmp_path: Path) -> None:
    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="Excel worker",
        tools=["read"],
        prompt="You are Excel Worker.",
    )
    components = build_runtime_components(
        _runtime_config(tmp_path),
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    profile = _frontstage_agent("aca")

    tool_runtime = components.tool_broker.build_tool_runtime(
        _run_ctx(components, agent=profile, visible_subagents=[])
    )

    assert "delegate_subagent" not in [tool.name for tool in tool_runtime.tools]
    assert tool_runtime.metadata["visible_subagent_summaries"] == []


async def test_delegate_subagent_rejects_target_not_in_session_allowlist(tmp_path: Path) -> None:
    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="Excel worker",
        tools=["read"],
        prompt="You are Excel Worker.",
    )
    components = build_runtime_components(
        _runtime_config(tmp_path),
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    profile = _frontstage_agent("aca")

    result = await components.tool_broker.execute(
        tool_name="delegate_subagent",
        arguments={
            "delegate_agent_id": "excel-worker",
            "task": "整理 Excel 文件并总结",
        },
        ctx=_tool_ctx(agent=profile, visible_subagents=["search-worker"]),
    )

    assert result.raw["ok"] is False
    assert "visible" in result.raw["error"]


async def test_subagent_child_run_hides_delegate_subagent(tmp_path: Path) -> None:
    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="Excel worker",
        tools=["read"],
        prompt="You are Excel Worker.",
    )
    components = build_runtime_components(
        _runtime_config(tmp_path),
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="worker summary")),
        model_registry_manager=await _model_registry_manager(tmp_path),
    )
    captured = {}

    async def fake_execute(ctx, deliver_actions: bool = True):
        captured["ctx"] = ctx
        _ = deliver_actions
        ctx.response = AgentRuntimeResult(status="completed", text="worker summary")
        await components.run_manager.mark_completed(ctx.run.run_id)

    components.pipeline.execute = fake_execute  # type: ignore[method-assign]
    profile = _frontstage_agent("aca")

    await components.tool_broker.execute(
        tool_name="delegate_subagent",
        arguments={
            "delegate_agent_id": "excel-worker",
            "task": "整理 Excel 文件并总结",
        },
        ctx=_tool_ctx(agent=profile, visible_subagents=["excel-worker"]),
    )

    tool_runtime = components.tool_broker.build_tool_runtime(captured["ctx"])

    assert "delegate_subagent" not in [tool.name for tool in tool_runtime.tools]


async def test_non_default_frontstage_agent_can_delegate_when_session_allows_it(tmp_path: Path) -> None:
    _write_subagent(
        tmp_path,
        name="excel-worker",
        description="Excel worker",
        tools=["read"],
        prompt="You are Excel Worker.",
    )
    components = build_runtime_components(
        _runtime_config(tmp_path),
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="worker summary")),
        model_registry_manager=await _model_registry_manager(tmp_path),
    )
    profile = _frontstage_agent("worker")

    result = await components.tool_broker.execute(
        tool_name="delegate_subagent",
        arguments={
            "delegate_agent_id": "excel-worker",
            "task": "整理 Excel 文件并总结",
        },
        ctx=_tool_ctx(agent=profile, visible_subagents=["excel-worker"]),
    )

    assert result.raw["ok"] is True
