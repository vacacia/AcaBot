# BotContext: 插件与框架交互的唯一入口(门面模式)
# 测试: Null Object 默认值, 代理调用委托(llm_call/get_messages), Config 读取

import pytest
from unittest.mock import AsyncMock
from acabot.plugin.context import BotContext
from acabot.store.null import NullMessageStore
from acabot.agent import AgentResponse
from acabot.types import Action, ActionType, EventSource
from acabot.config import Config


class TestBotContext:
    @pytest.fixture
    def bot(self):
        gateway = AsyncMock()
        session_mgr = AsyncMock()
        agent = AsyncMock()
        agent.run = AsyncMock(return_value=AgentResponse(text="hi"))
        config = Config({})

        return BotContext(
            gateway=gateway,
            session_mgr=session_mgr,
            agent=agent,
            config=config,
        )

    def test_store_is_null_by_default(self, bot):
        assert isinstance(bot.store, NullMessageStore)

    async def test_get_messages_delegates_to_store(self, bot):
        msgs = await bot.get_messages("qq:group:123", limit=10)
        assert msgs == []  # NullMessageStore returns []

    async def test_llm_call_delegates_to_agent(self, bot):
        resp = await bot.llm_call(system_prompt="test", messages=[{"role": "user", "content": "hi"}])
        assert resp.text == "hi"
        bot.agent.run.assert_called_once()

    async def test_llm_call_with_model_override(self, bot):
        await bot.llm_call(
            system_prompt="test",
            messages=[{"role": "user", "content": "hi"}],
            model="claude-sonnet-4-20250514",
        )
        call_kwargs = bot.agent.run.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"

    def test_get_config_returns_empty_for_unknown(self, bot):
        assert bot.get_config("nonexistent") == {}

    def test_get_config_returns_plugin_section(self):
        config = Config({"plugins": {"my_plugin": {"key": "value"}}})
        bot = BotContext(
            gateway=AsyncMock(), session_mgr=AsyncMock(),
            agent=AsyncMock(), config=config,
        )
        assert bot.get_config("my_plugin") == {"key": "value"}
