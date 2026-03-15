from acabot.config import Config
from acabot.runtime import (
    FileSystemModelRegistryManager,
    ModelBinding,
    ModelPreset,
    ModelProvider,
    OpenAICompatibleProviderConfig,
    RouteDecision,
    build_runtime_components,
)
from acabot.runtime.tool_broker import ToolExecutionContext
from acabot.types import EventSource, MsgSegment, StandardEvent

from .test_bootstrap import FakeAgent, FakeAgentResponse
from .test_outbox import FakeGateway


def _skills_dir() -> str:
    from pathlib import Path

    return str(Path(__file__).resolve().parent.parent / "fixtures" / "skills")


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


def _tool_ctx(*, run_id: str, profile) -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id=run_id,
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id=profile.agent_id,
        target=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        profile=profile,
        metadata={
            "channel_scope": "qq:user:10001",
            "event_id": "evt:parent",
            "event_timestamp": 123,
            "platform": "qq",
            "message_type": "private",
        },
    )


async def _model_registry_manager(tmp_path) -> FileSystemModelRegistryManager:
    manager = FileSystemModelRegistryManager(
        providers_dir=tmp_path / "providers",
        presets_dir=tmp_path / "presets",
        bindings_dir=tmp_path / "bindings",
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
    await manager.upsert_preset(
        ModelPreset(
            preset_id="worker-main",
            provider_id="openai-main",
            model="gpt-worker",
            context_window=32000,
            supports_tools=True,
        )
    )
    await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:excel-worker",
            target_type="agent",
            target_id="excel_worker",
            preset_id="worker-main",
        )
    )
    return manager


async def test_delegate_skill_uses_real_local_child_run() -> None:
    gateway = FakeGateway()
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
                    "skill_catalog_dir": _skills_dir(),
                },
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/aca",
                        "default_model": "runtime-model",
                        "skill_assignments": [
                            {
                                "skill_name": "sample_configured_skill",
                                "delegation_mode": "must_delegate",
                                "delegate_agent_id": "excel_worker",
                            }
                        ],
                    },
                    "excel_worker": {
                        "name": "Excel Worker",
                        "prompt_ref": "prompt/excel_worker",
                        "default_model": "runtime-model",
                    },
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                    "prompt/excel_worker": "You are Excel Worker.",
                },
                "plugins": [
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                ],
            },
        }
    )
    components = build_runtime_components(
        config,
        gateway=gateway,
        agent=FakeAgent(FakeAgentResponse(text="worker summary", model_used="runtime-model")),
    )
    await components.plugin_manager.ensure_started()

    parent_decision = RouteDecision(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:user:10001",
    )
    parent_run = await components.run_manager.open(
        event=_event(),
        decision=parent_decision,
    )
    profile = components.profile_loader.profiles["aca"]

    result = await components.tool_broker.execute(
        tool_name="delegate_skill",
        arguments={
            "skill_name": "sample_configured_skill",
            "task": "整理 Excel 文件并总结",
        },
        ctx=_tool_ctx(run_id=parent_run.run_id, profile=profile),
    )

    assert result.raw["ok"] is True
    child_run_id = str(result.raw["delegated_run_id"])
    assert child_run_id.startswith("run:")
    assert result.raw["summary"] == "worker summary"
    assert result.metadata["delegate_agent_id"] == "excel_worker"
    assert gateway.sent == []

    child_run = await components.run_manager.get(child_run_id)
    assert child_run is not None
    assert child_run.agent_id == "excel_worker"
    assert child_run.status == "completed"
    assert child_run.metadata["run_kind"] == "subagent"
    assert child_run.metadata["parent_run_id"] == parent_run.run_id
    assert child_run.metadata["delegated_skill"] == "sample_configured_skill"

    child_thread = await components.thread_manager.get(child_run.thread_id)
    assert child_thread is not None
    assert child_thread.thread_kind == "subagent"
    assert child_thread.metadata["parent_run_id"] == parent_run.run_id
    assert child_thread.metadata["delegate_agent_id"] == "excel_worker"
    assert child_thread.working_messages[-1]["role"] == "assistant"
    assert child_thread.working_messages[-1]["content"] == "worker summary"

    parent_steps = components.run_manager._steps[parent_run.run_id]  # type: ignore[attr-defined]
    assert len(parent_steps) == 2
    assert parent_steps[0].status == "started"
    assert parent_steps[1].status == "completed"
    assert parent_steps[1].payload["child_run_id"] == child_run_id
    assert parent_steps[1].payload["result_summary"] == "worker summary"


async def test_bootstrap_registers_local_profile_subagent_executors() -> None:
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
                    },
                    "excel_worker": {
                        "name": "Excel Worker",
                        "prompt_ref": "prompt/excel_worker",
                        "default_model": "runtime-model",
                    },
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                    "prompt/excel_worker": "You are Excel Worker.",
                },
            },
        }
    )
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )

    registered = components.subagent_executor_registry.list_all()

    assert [item.agent_id for item in registered] == ["aca", "excel_worker"]
    assert all(item.source == "runtime:local_profile" for item in registered)
    assert registered[1].metadata["kind"] == "local_profile"


async def test_delegate_skill_child_run_uses_delegate_agent_model_binding(
    tmp_path,
) -> None:
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="worker summary", model_used="gpt-worker"))
    model_registry_manager = await _model_registry_manager(tmp_path)
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
                    "skill_catalog_dir": _skills_dir(),
                },
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/aca",
                        "default_model": "runtime-model",
                        "skill_assignments": [
                            {
                                "skill_name": "sample_configured_skill",
                                "delegation_mode": "must_delegate",
                                "delegate_agent_id": "excel_worker",
                            }
                        ],
                    },
                    "excel_worker": {
                        "name": "Excel Worker",
                        "prompt_ref": "prompt/excel_worker",
                        "default_model": "runtime-model",
                    },
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                    "prompt/excel_worker": "You are Excel Worker.",
                },
                "plugins": [
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                ],
            },
        }
    )
    components = build_runtime_components(
        config,
        gateway=gateway,
        agent=agent,
        model_registry_manager=model_registry_manager,
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
    profile = components.profile_loader.profiles["aca"]

    result = await components.tool_broker.execute(
        tool_name="delegate_skill",
        arguments={
            "skill_name": "sample_configured_skill",
            "task": "整理 Excel 文件并总结",
        },
        ctx=_tool_ctx(run_id=parent_run.run_id, profile=profile),
    )

    child_run = await components.run_manager.get(str(result.raw["delegated_run_id"]))

    assert child_run is not None
    assert child_run.metadata["model_snapshot"]["binding_id"] == "binding:excel-worker"
    assert child_run.metadata["model_snapshot"]["provider_id"] == "openai-main"
    assert child_run.metadata["model_snapshot"]["preset_id"] == "worker-main"
    assert agent.calls[-1]["model"] == "gpt-worker"
    assert agent.calls[-1]["request_options"]["api_base"] == "https://example.invalid/v1"
    assert agent.calls[-1]["request_options"]["provider_kind"] == "openai_compatible"
