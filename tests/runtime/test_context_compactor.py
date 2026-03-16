from unittest.mock import patch

import pytest

from acabot.runtime import (
    AgentProfile,
    ContextCompactionConfig,
    ContextCompactor,
    ModelContextSummarizer,
    RouteDecision,
    RunContext,
)
from acabot.runtime.contracts import RunRecord, ThreadState
from acabot.types import EventSource, MsgSegment, StandardEvent


# region helpers
def _make_messages(n_turns: int, *, content_len: int = 10) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for index in range(n_turns):
        messages.append({"role": "user", "content": f"u{index} " + ("x" * content_len)})
        messages.append({"role": "assistant", "content": f"a{index} " + ("y" * content_len)})
    return messages


def _make_tool_messages(n_turns: int) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for index in range(n_turns):
        messages.append({"role": "user", "content": f"user {index}"})
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call_{index}",
                        "function": {"name": "tool", "arguments": "{}"},
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "content": f"result {index}",
                "tool_call_id": f"call_{index}",
            }
        )
        messages.append({"role": "assistant", "content": f"answer {index}"})
    return messages


def _ctx(messages: list[dict[str, object]]) -> RunContext:
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
            trigger_event_id="evt-1",
            status="queued",
            started_at=123,
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
            working_messages=[dict(message) for message in messages],
            working_summary="",
            last_event_at=123,
        ),
        profile=AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            default_model="test-model",
        ),
    )


def _mock_token_counter(model: str = "", messages=None, **kwargs) -> int:
    _ = model, kwargs
    if messages is None:
        return 0
    total = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            total += len(content)
        if "tool_calls" in message:
            total += 20
    return total


_MOCK_MODEL_INFO = {
    "max_input_tokens": 1000,
    "max_output_tokens": 100,
    "max_tokens": 100,
}


class _SummaryAgent:
    def __init__(self, *, text: str = "") -> None:
        self.text = text
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, object]],
        model: str | None = None,
        request_options=None,
    ):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "model": model,
                "request_options": dict(request_options or {}),
            }
        )
        return type(
            "Response",
            (),
            {
                "text": self.text,
                "error": None,
                "usage": {},
                "model_used": model or "",
            },
        )()


@pytest.fixture
def _mock_litellm():
    with (
        patch(
            "acabot.runtime.memory.context_compactor.token_counter",
            side_effect=_mock_token_counter,
        ),
        patch(
            "acabot.runtime.memory.context_compactor.get_model_info",
            return_value=_MOCK_MODEL_INFO,
        ),
    ):
        yield


# endregion


@pytest.mark.usefixtures("_mock_litellm")
async def test_context_compactor_skips_short_context() -> None:
    ctx = _ctx(_make_messages(2, content_len=8))
    compactor = ContextCompactor(
        ContextCompactionConfig(
            max_context_ratio=1.0,
            system_prompt_reserve_tokens=0,
            prompt_slot_reserve_tokens=0,
            tool_schema_reserve_tokens=0,
        )
    )

    result = await compactor.compact(ctx)

    assert result.strategy_used == "none"
    assert len(ctx.thread.working_messages) == 4
    assert ctx.metadata["token_stats"]["messages_dropped"] == 0


@pytest.mark.usefixtures("_mock_litellm")
async def test_context_compactor_truncates_by_token_budget() -> None:
    ctx = _ctx(_make_messages(15, content_len=45))
    compactor = ContextCompactor(
        ContextCompactionConfig(
            max_context_ratio=0.7,
            preserve_recent_turns=3,
        )
    )

    result = await compactor.compact(ctx)

    assert result.strategy_used == "truncate"
    assert len(result.dropped_messages) > 0
    assert len(result.compressed_messages) < 30
    assert str(result.compressed_messages[-1]["content"]).startswith("a14")
    assert ctx.metadata["token_stats"]["before_compression"] > ctx.metadata["token_stats"]["after_compression"]


@pytest.mark.usefixtures("_mock_litellm")
async def test_context_compactor_keeps_complete_tool_turns() -> None:
    ctx = _ctx(_make_tool_messages(5))
    compactor = ContextCompactor(
        ContextCompactionConfig(
            max_context_ratio=0.3,
            preserve_recent_turns=1,
        )
    )

    await compactor.compact(ctx)

    for index, message in enumerate(ctx.thread.working_messages):
        if message["role"] == "tool":
            assert index > 0
            previous = ctx.thread.working_messages[index - 1]
            assert previous["role"] == "assistant"
            assert "tool_calls" in previous
            assert index + 1 < len(ctx.thread.working_messages)
            assert ctx.thread.working_messages[index + 1]["role"] == "assistant"


@pytest.mark.usefixtures("_mock_litellm")
async def test_context_compactor_preserves_pinned_turns() -> None:
    messages = _make_messages(10, content_len=40)
    messages[2]["pinned"] = True
    ctx = _ctx(messages)
    compactor = ContextCompactor(
        ContextCompactionConfig(
            max_context_ratio=0.2,
            preserve_recent_turns=2,
        )
    )

    await compactor.compact(ctx)

    kept_contents = [str(message["content"]) for message in ctx.thread.working_messages]
    assert any(content.startswith("u1 ") for content in kept_contents)
    assert any(content.startswith("a1 ") for content in kept_contents)


@pytest.mark.usefixtures("_mock_litellm")
async def test_context_compactor_budget_respects_reserve_tokens() -> None:
    ctx = _ctx(_make_messages(10, content_len=30))
    compactor = ContextCompactor(
        ContextCompactionConfig(
            max_context_ratio=1.0,
            preserve_recent_turns=1,
            system_prompt_reserve_tokens=300,
            prompt_slot_reserve_tokens=200,
            tool_schema_reserve_tokens=100,
        )
    )

    result = await compactor.compact(ctx)

    assert result.budget == 400
    assert ctx.metadata["token_stats"]["system_prompt_reserve_tokens"] == 300
    assert ctx.metadata["token_stats"]["prompt_slot_reserve_tokens"] == 200
    assert ctx.metadata["token_stats"]["tool_schema_reserve_tokens"] == 100


@pytest.mark.usefixtures("_mock_litellm")
async def test_context_compactor_summarize_without_summarizer_falls_back_to_truncate() -> None:
    ctx = _ctx(_make_messages(15, content_len=45))
    compactor = ContextCompactor(
        ContextCompactionConfig(
            strategy="summarize",
            max_context_ratio=0.7,
            preserve_recent_turns=3,
        )
    )

    result = await compactor.compact(ctx)

    assert result.strategy_used == "truncate"
    assert ctx.thread.working_summary == ""


@pytest.mark.usefixtures("_mock_litellm")
async def test_context_compactor_uses_llm_summary_when_enabled() -> None:
    ctx = _ctx(_make_messages(15, content_len=45))
    summary_agent = _SummaryAgent(text="## Goal\n继续跟进实习材料要求")
    config = ContextCompactionConfig(
        strategy="summarize",
        max_context_ratio=0.7,
        preserve_recent_turns=3,
        summary_model="summary-model",
    )
    compactor = ContextCompactor(
        config,
        summarizer=ModelContextSummarizer(agent=summary_agent, config=config),
    )

    result = await compactor.compact(ctx)

    assert result.strategy_used == "summarize"
    assert result.summary_text == "## Goal\n继续跟进实习材料要求"
    assert summary_agent.calls[0]["model"] == "summary-model"
    assert "Compacted conversation history" in str(summary_agent.calls[0]["messages"][0]["content"])


@pytest.mark.usefixtures("_mock_litellm")
async def test_context_compactor_updates_existing_summary_incrementally() -> None:
    ctx = _ctx(_make_messages(15, content_len=45))
    ctx.thread.working_summary = "旧摘要"
    summary_agent = _SummaryAgent(text="新摘要")
    config = ContextCompactionConfig(
        strategy="summarize",
        max_context_ratio=0.7,
        preserve_recent_turns=3,
    )
    compactor = ContextCompactor(
        config,
        summarizer=ModelContextSummarizer(agent=summary_agent, config=config),
    )

    result = await compactor.compact(ctx)

    assert result.strategy_used == "summarize"
    assert result.summary_text == "新摘要"
    assert summary_agent.calls[0]["system_prompt"] == config.update_summary_system_prompt
    assert "Existing summary" in str(summary_agent.calls[0]["messages"][0]["content"])
    assert "<summary>\n旧摘要\n</summary>" in str(summary_agent.calls[0]["messages"][0]["content"])


@pytest.mark.usefixtures("_mock_litellm")
async def test_context_compactor_truncates_long_summary_output() -> None:
    ctx = _ctx(_make_messages(15, content_len=45))
    summary_agent = _SummaryAgent(text="x" * 50)
    config = ContextCompactionConfig(
        strategy="summarize",
        max_context_ratio=0.7,
        preserve_recent_turns=3,
        summary_max_chars=10,
    )
    compactor = ContextCompactor(
        config,
        summarizer=ModelContextSummarizer(agent=summary_agent, config=config),
    )

    result = await compactor.compact(ctx)

    assert result.summary_text == "xxxxxxxxxx..."


@pytest.mark.usefixtures("_mock_litellm")
async def test_context_compactor_apply_to_thread_rejects_stale_snapshot() -> None:
    ctx = _ctx(_make_messages(15, content_len=45))
    compactor = ContextCompactor(
        ContextCompactionConfig(
            max_context_ratio=0.7,
            preserve_recent_turns=3,
        )
    )
    snapshot = compactor.snapshot_thread(ctx.thread)
    result = await compactor.compact(ctx, snapshot=snapshot)

    ctx.thread.working_messages.append({"role": "assistant", "content": "concurrent"})

    applied = compactor.apply_to_thread(
        ctx.thread,
        snapshot=snapshot,
        result=result,
        timestamp=ctx.event.timestamp,
    )

    assert applied is False
