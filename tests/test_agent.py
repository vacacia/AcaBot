import pytest
from unittest.mock import AsyncMock, patch

from acabot.agent import (
    AgentResponse,
    BaseAgent,
    ToolExecutionResult,
    ToolSpec,
)
from acabot.agent.agent import LitellmAgent


def _make_msg(**kwargs):
    attrs = kwargs

    def model_dump(self_=None):
        return dict(attrs)

    attrs["model_dump"] = model_dump
    return type("MockMsg", (), attrs)()


class TestLitellmAgent:
    @pytest.fixture
    def agent(self):
        return LitellmAgent(default_model="gpt-4o-mini")

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
            )

        assert resp.error is not None
        assert "API error" in resp.error


class TestToolCalling:
    @pytest.fixture
    def agent(self):
        return LitellmAgent(default_model="gpt-4o-mini")

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
                    tools=[tool_spec],
                    tool_executor=tool_executor,
                )
