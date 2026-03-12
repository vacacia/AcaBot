from acabot.config import Config
from acabot.runtime import build_runtime_components
from acabot.runtime.tool_broker import ToolExecutionContext
from acabot.types import EventSource

from .test_bootstrap import FakeAgent, FakeAgentResponse
from .test_outbox import FakeGateway


def _execution_ctx(profile) -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id="run:delegate",
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
            "event_id": "evt:delegate",
            "event_timestamp": 123,
            "platform": "qq",
            "message_type": "private",
        },
    )


async def test_delegate_skill_is_auto_loaded_for_delegated_profiles() -> None:
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
                        "skill_assignments": [
                            {
                                "skill_name": "sample_configured_skill",
                                "delegation_mode": "prefer_delegate",
                                "delegate_agent_id": "sample_worker",
                            }
                        ],
                    }
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                },
                "plugins": [
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                    "tests.runtime.runtime_plugin_samples:SampleDelegationWorkerPlugin",
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

    profile = components.profile_loader.profiles["aca"]
    visible = components.tool_broker.visible_tools(profile)

    assert "delegate_skill" in [tool.name for tool in visible]


async def test_delegate_skill_tool_calls_subagent_executor() -> None:
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
                        "skill_assignments": [
                            {
                                "skill_name": "sample_configured_skill",
                                "delegation_mode": "must_delegate",
                                "delegate_agent_id": "sample_worker",
                            }
                        ],
                    }
                },
                "prompts": {
                    "prompt/aca": "You are Aca.",
                },
                "plugins": [
                    "tests.runtime.runtime_plugin_samples:SampleConfiguredRuntimePlugin",
                    "tests.runtime.runtime_plugin_samples:SampleDelegationWorkerPlugin",
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

    profile = components.profile_loader.profiles["aca"]
    result = await components.tool_broker.execute(
        tool_name="delegate_skill",
        arguments={
            "skill_name": "sample_configured_skill",
            "task": "整理这份样例任务",
        },
        ctx=_execution_ctx(profile),
    )

    assert "Delegation completed" in str(result.llm_content)
    assert result.raw["ok"] is True
    assert result.raw["delegated_run_id"] == "subrun:run:delegate"
    assert result.raw["summary"] == "worker handled: 整理这份样例任务"
    assert result.metadata["delegate_agent_id"] == "sample_worker"
