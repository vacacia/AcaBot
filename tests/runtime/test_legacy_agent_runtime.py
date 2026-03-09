from dataclasses import dataclass, field
from typing import Any

from acabot.runtime import (
    AgentProfile,
    LegacyAgentRuntime,
    RouteDecision,
    RunContext,
    RunRecord,
    StaticPromptLoader,
    ThreadState,
)
from acabot.types import EventSource, MsgSegment, StandardEvent


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


def _context() -> RunContext:
    event = StandardEvent(
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
    return RunContext(
        run=RunRecord(
            run_id="run:1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            trigger_event_id=event.event_id,
            status="running",
            started_at=event.timestamp,
        ),
        event=event,
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
        thread=ThreadState(
            thread_id="qq:user:10001",
            channel_scope="qq:user:10001",
        ),
        profile=AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            default_model="test-model",
        ),
        messages=[{"role": "user", "content": "[acacia/10001] hello"}],
    )


async def test_legacy_agent_runtime_builds_completed_result() -> None:
    legacy_agent = FakeLegacyAgent(
        FakeLegacyResponse(
            text="hello back",
            usage={"total_tokens": 12},
            model_used="test-model",
        )
    )
    runtime = LegacyAgentRuntime(
        agent=legacy_agent,
        prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
    )
    ctx = _context()

    result = await runtime.execute(ctx)

    assert ctx.system_prompt == "You are Aca."
    assert legacy_agent.calls[0]["model"] == "test-model"
    assert result.status == "completed"
    assert result.actions[0].action.payload["text"] == "hello back"
    assert result.usage["total_tokens"] == 12


async def test_legacy_agent_runtime_builds_failed_result() -> None:
    legacy_agent = FakeLegacyAgent(FakeLegacyResponse(error="boom"))
    runtime = LegacyAgentRuntime(
        agent=legacy_agent,
        prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
    )
    ctx = _context()

    result = await runtime.execute(ctx)

    assert result.status == "failed"
    assert result.error == "boom"
    assert result.actions == []
