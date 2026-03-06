# LitellmAgent: LLM 调用 + tool calling loop
# 测试: 简单对话, 模型热切换, 错误处理, tool 注册, tool calling loop

import json
import pytest
from unittest.mock import AsyncMock, patch
from acabot.agent import BaseAgent
from acabot.agent.agent import LitellmAgent
from acabot.agent import AgentResponse, ToolDef


class TestLitellmAgent:
    @pytest.fixture
    def agent(self):
        return LitellmAgent(default_model="gpt-4o-mini")

    def test_is_base_agent(self, agent):
        # 确认实现了 BaseAgent 接口
        assert isinstance(agent, BaseAgent)

    async def test_simple_chat(self, agent):
        # 最简场景: 没有 tool call, LLM 直接返回文字
        mock_resp = AsyncMock()
        mock_resp.choices = [
            type("C", (), {"message": type("M", (), {"content": "Hello!", "tool_calls": None})()})()
        ]
        mock_resp.usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})()

        with patch("acabot.agent.agent.acompletion", return_value=mock_resp):
            resp = await agent.run(system_prompt="test", messages=[{"role": "user", "content": "hi"}])

        assert resp.text == "Hello!"
        assert resp.error is None
        assert resp.model_used == "gpt-4o-mini"

    async def test_model_override(self, agent):
        # model 参数覆盖默认模型 — hook 可通过 HookContext.model 实现热切换
        mock_resp = AsyncMock()
        mock_resp.choices = [
            type("C", (), {"message": type("M", (), {"content": "Hi", "tool_calls": None})()})()
        ]
        mock_resp.usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})()

        with patch("acabot.agent.agent.acompletion", return_value=mock_resp) as mock_call:
            resp = await agent.run(
                system_prompt="test",
                messages=[{"role": "user", "content": "hi"}],
                model="claude-sonnet-4-20250514",
            )

        assert resp.model_used == "claude-sonnet-4-20250514"
        assert mock_call.call_args.kwargs["model"] == "claude-sonnet-4-20250514"

    async def test_error_handling(self, agent):
        # LLM 调用异常 → resp.error 记录错误信息
        with patch("acabot.agent.agent.acompletion", side_effect=Exception("API error")):
            resp = await agent.run(system_prompt="test", messages=[{"role": "user", "content": "hi"}])
        assert resp.error is not None
        assert "API error" in resp.error


class TestToolCalling:
    @pytest.fixture
    def agent(self):
        a = LitellmAgent(default_model="gpt-4o-mini")

        async def get_time(params):
            return {"time": "2026-03-03 12:00:00"}

        a.register_tool(ToolDef(
            name="get_time", description="Get current time",
            parameters={"type": "object", "properties": {}},
            handler=get_time,
        ))
        return a

    def test_tool_registered(self, agent):
        # 工具注册后能在 _tools 字典里找到
        assert "get_time" in agent._tools

    async def test_tool_loop(self, agent):
        # 两轮调用: LLM 返回 tool_call → 执行 tool → LLM 拿到结果给最终回复
        # 第一轮: LLM 请求调用 get_time 工具
        tc_resp = AsyncMock()
        tc_resp.choices = [type("C", (), {"message": type("M", (), {
            "content": None,
            "tool_calls": [type("TC", (), {
                "id": "call_1", "type": "function",
                "function": type("F", (), {"name": "get_time", "arguments": "{}"})(),
            })()],
        })()})()]
        tc_resp.usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})()

        # 第二轮: LLM 拿到 tool 结果后给出最终文字回复
        final_resp = AsyncMock()
        final_resp.choices = [type("C", (), {
            "message": type("M", (), {"content": "It is 2026-03-03 12:00:00", "tool_calls": None})()
        })()]
        final_resp.usage = type("U", (), {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30})()

        with patch("acabot.agent.agent.acompletion", side_effect=[tc_resp, final_resp]):
            resp = await agent.run(system_prompt="test", messages=[{"role": "user", "content": "time?"}])

        assert resp.text == "It is 2026-03-03 12:00:00"
        assert len(resp.tool_calls_made) == 1
        assert resp.tool_calls_made[0].name == "get_time"
