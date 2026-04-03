import logging

import pytest
from unittest.mock import AsyncMock, patch

from acabot.agent import (
    AgentResponse,
    BaseAgent,
    ToolExecutionResult,
    ToolSpec,
)
from acabot.agent.agent import LitellmAgent
from acabot.runtime.control.log_buffer import InMemoryLogBuffer, InMemoryLogHandler
from acabot.runtime.control.log_setup import configure_structlog


def _make_msg(**kwargs):
    attrs = kwargs

    def model_dump(self_=None):
        return dict(attrs)

    attrs["model_dump"] = model_dump
    return type("MockMsg", (), attrs)()


class TestLitellmAgent:
    @pytest.fixture
    def agent(self):
        return LitellmAgent()

    def test_is_base_agent(self, agent):
        assert isinstance(agent, BaseAgent)

    async def test_simple_chat(self, agent):
        mock_resp = AsyncMock()
        mock_resp.choices = [
            type("C", (), {"message": type("M", (), {"content": "Hello!", "tool_calls": None})()})()
        ]
        mock_resp.usage = type(
            "U",
            (),
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )()

        with patch("acabot.agent.agent.acompletion", return_value=mock_resp):
            resp = await agent.run(
                system_prompt="test",
                messages=[{"role": "user", "content": "hi"}],
                model="gpt-4o-mini",
            )

        assert resp.text == "Hello!"
        assert resp.error is None
        assert resp.model_used == "gpt-4o-mini"

    async def test_model_override(self, agent):
        mock_resp = AsyncMock()
        mock_resp.choices = [
            type("C", (), {"message": type("M", (), {"content": "Hi", "tool_calls": None})()})()
        ]
        mock_resp.usage = type(
            "U",
            (),
            {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )()

        with patch("acabot.agent.agent.acompletion", return_value=mock_resp) as mock_call:
            resp = await agent.run(
                system_prompt="test",
                messages=[{"role": "user", "content": "hi"}],
                model="claude-sonnet-4-20250514",
            )

        assert resp.model_used == "claude-sonnet-4-20250514"
        assert mock_call.call_args.kwargs["model"] == "claude-sonnet-4-20250514"

    async def test_error_handling(self, agent):
        with patch("acabot.agent.agent.acompletion", side_effect=Exception("API error")):
            resp = await agent.run(
                system_prompt="test",
                messages=[{"role": "user", "content": "hi"}],
                model="gpt-4o-mini",
            )

        assert resp.error is not None
        assert "API error" in resp.error

    async def test_requires_explicit_model_when_no_legacy_fallback(self):
        agent = LitellmAgent()

        resp = await agent.run(
            system_prompt="test",
            messages=[{"role": "user", "content": "hi"}],
        )

        assert resp.error == "model is required"
        assert resp.model_used == ""

    async def test_run_emits_structured_usage_log(self, agent):
        configure_structlog()
        buffer = InMemoryLogBuffer(max_entries=10)
        handler = InMemoryLogHandler(buffer)
        logger = logging.getLogger("acabot.agent")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False

        mock_resp = AsyncMock()
        mock_resp.choices = [
            type("C", (), {"message": type("M", (), {"content": "Hello!", "tool_calls": None})()})()
        ]
        mock_resp.usage = type(
            "U",
            (),
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )()

        with patch("acabot.agent.agent.acompletion", return_value=mock_resp):
            resp = await agent.run(
                system_prompt="test",
                messages=[{"role": "user", "content": "hi"}],
                model="gpt-4o-mini",
            )

        assert resp.text == "Hello!"
        snapshot = buffer.list_entries(keyword="LLM run completed", limit=10)
        assert len(snapshot["items"]) == 1
        assert snapshot["items"][0]["extra"]["model"] == "gpt-4o-mini"
        assert snapshot["items"][0]["extra"]["total_tokens"] == 15

    async def test_complete_emits_structured_usage_log(self, agent):
        configure_structlog()
        buffer = InMemoryLogBuffer(max_entries=10)
        handler = InMemoryLogHandler(buffer)
        logger = logging.getLogger("acabot.agent")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False

        mock_resp = AsyncMock()
        mock_resp.choices = [
            type("C", (), {"message": type("M", (), {"content": "Hi", "tool_calls": None})()})()
        ]
        mock_resp.usage = type(
            "U",
            (),
            {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        )()

        with patch("acabot.agent.agent.acompletion", return_value=mock_resp):
            resp = await agent.complete(
                system_prompt="test",
                messages=[{"role": "user", "content": "hi"}],
                model="gpt-4o-mini",
            )

        assert resp.text == "Hi"
        snapshot = buffer.list_entries(keyword="LLM complete finished", limit=10)
        assert len(snapshot["items"]) == 1
        assert snapshot["items"][0]["extra"]["model"] == "gpt-4o-mini"
        assert snapshot["items"][0]["extra"]["total_tokens"] == 3


class TestToolCalling:
    @pytest.fixture
    def agent(self):
        return LitellmAgent()

    async def test_tool_loop_with_explicit_tools_and_executor(self, agent):
        tool_spec = ToolSpec(
            name="get_time",
            description="Get current time",
            parameters={"type": "object", "properties": {}},
        )
        tc_msg = _make_msg(
            content=None,
            role="assistant",
            tool_calls=[
                type(
                    "TC",
                    (),
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": type(
                            "F",
                            (),
                            {"name": "get_time", "arguments": "{}"},
                        )(),
                    },
                )()
            ],
        )
        tc_resp = AsyncMock()
        tc_resp.choices = [type("C", (), {"message": tc_msg})()]
        tc_resp.usage = type(
            "U",
            (),
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )()

        final_resp = AsyncMock()
        final_resp.choices = [
            type(
                "C",
                (),
                {
                    "message": type(
                        "M",
                        (),
                        {"content": "It is 2026-03-03 12:00:00", "tool_calls": None},
                    )()
                },
            )()
        ]
        final_resp.usage = type(
            "U",
            (),
            {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        )()

        async def tool_executor(tool_name, arguments):
            assert tool_name == "get_time"
            assert arguments == {}
            return ToolExecutionResult(
                content='{"time": "2026-03-03 12:00:00"}',
                raw={"time": "2026-03-03 12:00:00"},
            )

        with patch("acabot.agent.agent.acompletion", side_effect=[tc_resp, final_resp]):
            resp = await agent.run(
                system_prompt="test",
                messages=[{"role": "user", "content": "time?"}],
                model="gpt-4o-mini",
                tools=[tool_spec],
                tool_executor=tool_executor,
            )

        assert resp.text == "It is 2026-03-03 12:00:00"
        assert len(resp.tool_calls_made) == 1
        assert resp.tool_calls_made[0].name == "get_time"
        assert resp.tool_calls_made[0].result == {"time": "2026-03-03 12:00:00"}

    async def test_explicit_tools_require_tool_executor(self, agent):
        tool_spec = ToolSpec(
            name="get_time",
            description="Get current time",
            parameters={"type": "object", "properties": {}},
        )

        resp = await agent.run(
            system_prompt="test",
            messages=[{"role": "user", "content": "time?"}],
            model="gpt-4o-mini",
            tools=[tool_spec],
        )

        assert isinstance(resp, AgentResponse)
        assert resp.error == "tool_executor is required when tools are provided"

    async def test_tool_executor_exceptions_are_not_swallowed(self, agent):
        tool_spec = ToolSpec(
            name="restricted",
            description="Restricted tool",
            parameters={"type": "object", "properties": {}},
        )
        tc_msg = _make_msg(
            content=None,
            role="assistant",
            tool_calls=[
                type(
                    "TC",
                    (),
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": type(
                            "F",
                            (),
                            {"name": "restricted", "arguments": "{}"},
                        )(),
                    },
                )()
            ],
        )
        tc_resp = AsyncMock()
        tc_resp.choices = [type("C", (), {"message": tc_msg})()]
        tc_resp.usage = type(
            "U",
            (),
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )()

        async def tool_executor(tool_name, arguments):
            _ = tool_name, arguments
            raise RuntimeError("tool interrupted")

        with patch("acabot.agent.agent.acompletion", return_value=tc_resp):
            with pytest.raises(RuntimeError, match="tool interrupted"):
                await agent.run(
                    system_prompt="test",
                    messages=[{"role": "user", "content": "time?"}],
                    model="gpt-4o-mini",
                    tools=[tool_spec],
                    tool_executor=tool_executor,
                )

    async def test_tool_call_round_rewrites_null_assistant_content_to_empty_string(self, agent):
        tool_spec = ToolSpec(
            name="get_time",
            description="Get current time",
            parameters={"type": "object", "properties": {}},
        )
        tc_msg = _make_msg(
            content=None,
            role="assistant",
            tool_calls=[
                type(
                    "TC",
                    (),
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": type(
                            "F",
                            (),
                            {"name": "get_time", "arguments": "{}"},
                        )(),
                    },
                )()
            ],
        )
        tc_resp = AsyncMock()
        tc_resp.choices = [type("C", (), {"message": tc_msg})()]
        tc_resp.usage = type(
            "U",
            (),
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )()

        final_resp = AsyncMock()
        final_resp.choices = [
            type("C", (), {"message": type("M", (), {"content": "ok", "tool_calls": None})()})()
        ]
        final_resp.usage = type(
            "U",
            (),
            {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        )()

        async def tool_executor(tool_name, arguments):
            _ = tool_name, arguments
            return ToolExecutionResult(content="{}", raw={})

        with patch("acabot.agent.agent.acompletion", side_effect=[tc_resp, final_resp]) as mock_call:
            await agent.run(
                system_prompt="test",
                messages=[{"role": "user", "content": "time?"}],
                model="gpt-4o-mini",
                tools=[tool_spec],
                tool_executor=tool_executor,
            )

        second_messages = mock_call.call_args_list[1].kwargs["messages"]
        assert second_messages[2]["role"] == "assistant"
        assert second_messages[2]["content"] == ""

    async def test_run_sanitizes_none_content_from_existing_history(self, agent):
        mock_resp = AsyncMock()
        mock_resp.choices = [
            type("C", (), {"message": type("M", (), {"content": "ok", "tool_calls": None})()})()
        ]
        mock_resp.usage = type(
            "U",
            (),
            {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )()

        with patch("acabot.agent.agent.acompletion", return_value=mock_resp) as mock_call:
            await agent.run(
                system_prompt="test",
                messages=[
                    {"role": "assistant", "content": None},
                    {"role": "user", "content": "hello"},
                ],
                model="gpt-4o-mini",
            )

        sent_messages = mock_call.call_args.kwargs["messages"]
        assert sent_messages[1]["role"] == "assistant"
        assert sent_messages[1]["content"] == ""

    async def test_max_tool_rounds_override_is_applied(self, agent):
        tc_msg = _make_msg(
            content=None,
            role="assistant",
            tool_calls=[
                type(
                    "TC",
                    (),
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": type(
                            "F",
                            (),
                            {"name": "get_time", "arguments": "{}"},
                        )(),
                    },
                )()
            ],
        )
        tc_resp = AsyncMock()
        tc_resp.choices = [type("C", (), {"message": tc_msg})()]
        tc_resp.usage = type(
            "U",
            (),
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )()

        async def tool_executor(tool_name, arguments):
            _ = tool_name, arguments
            return ToolExecutionResult(content="{}", raw={})

        with patch("acabot.agent.agent.acompletion", return_value=tc_resp):
            resp = await agent.run(
                system_prompt="test",
                messages=[{"role": "user", "content": "time?"}],
                model="gpt-4o-mini",
                max_tool_rounds=0,
                tools=[
                    ToolSpec(
                        name="get_time",
                        description="Get current time",
                        parameters={"type": "object", "properties": {}},
                    )
                ],
                tool_executor=tool_executor,
            )

        assert resp.error == "Tool calling exceeded max rounds (0)"
