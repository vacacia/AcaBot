# PluginLoader: 加载/去重/错误隔离/teardown
# 测试: 正常加载, hook/tool 注册, 重复拒绝, setup 失败隔离, teardown LIFO, schedules warning

import pytest
import logging
from unittest.mock import AsyncMock, MagicMock
from acabot.plugin.loader import PluginLoader
from acabot.plugin import Plugin, BotContext
from acabot.hook import Hook, HookRegistry
from acabot.agent.tool import ToolDef
from acabot.types import HookPoint, HookResult
from acabot.config import Config


# region 测试用 stub

class StubHook(Hook):
    """最简 Hook, 用于测试注册."""
    name = "stub"
    priority = 100
    enabled = True

    async def handle(self, ctx):
        return HookResult()


class SimplePlugin(Plugin):
    """只有 hook 的简单插件."""
    name = "simple"

    async def setup(self, bot):
        self.bot = bot

    def hooks(self):
        return [(HookPoint.ON_RECEIVE, StubHook())]


class ToolPlugin(Plugin):
    """带 tool 的插件."""
    name = "with_tool"

    async def setup(self, bot):
        pass

    def hooks(self):
        return []

    def tools(self):
        async def noop(params):
            return "ok"
        return [ToolDef(
            name="test_tool", description="A test tool",
            parameters={}, handler=noop,
        )]


class FailingPlugin(Plugin):
    """setup 会抛异常的插件."""
    name = "failing"

    async def setup(self, bot):
        raise RuntimeError("setup exploded")

    def hooks(self):
        return []


class TeardownTracker(Plugin):
    """记录 teardown 调用顺序."""
    def __init__(self, label: str, order_log: list):
        self.name = label
        self._order_log = order_log

    async def setup(self, bot):
        pass

    def hooks(self):
        return []

    async def teardown(self):
        self._order_log.append(self.name)


class SchedulePlugin(Plugin):
    """带 schedule 的插件, 用于验证 warning."""
    name = "scheduled"

    async def setup(self, bot):
        pass

    def hooks(self):
        return []

    def schedules(self):
        from acabot.plugin.base import ScheduleDef

        async def tick():
            pass
        return [ScheduleDef(cron="0 * * * *", handler=tick, name="hourly")]


# endregion


# region fixtures

@pytest.fixture
def bot():
    agent = AsyncMock()
    # register_tool 是同步方法, 用 MagicMock 避免 "coroutine never awaited" warning
    agent.register_tool = MagicMock()
    return BotContext(
        gateway=AsyncMock(), session_mgr=AsyncMock(),
        agent=agent, config=Config({}),
    )


@pytest.fixture
def hooks():
    return HookRegistry()


@pytest.fixture
def loader():
    return PluginLoader()

# endregion


# region 正常加载
class TestPluginLoaderBasic:
    """PluginLoader 正常加载: setup 调用, hook/tool 注册, loaded 列表."""

    # setup 被调用, 插件拿到 bot 引用
    async def test_setup_called_with_bot(self, loader, bot, hooks):
        plugin = SimplePlugin()
        await loader.load_plugin(plugin, bot, hooks)
        assert plugin.bot is bot

    # hook 注册到 registry
    async def test_hooks_registered(self, loader, bot, hooks):
        await loader.load_plugin(SimplePlugin(), bot, hooks)
        assert len(hooks.get(HookPoint.ON_RECEIVE)) == 1

    # tool 注册到 bot.agent
    async def test_tools_registered(self, loader, bot, hooks):
        await loader.load_plugin(ToolPlugin(), bot, hooks)
        bot.agent.register_tool.assert_called_once()
        registered = bot.agent.register_tool.call_args[0][0]
        assert registered.name == "test_tool"

    # 加载后出现在 loaded 列表
    async def test_plugin_in_loaded_list(self, loader, bot, hooks):
        plugin = SimplePlugin()
        await loader.load_plugin(plugin, bot, hooks)
        assert plugin in loader.loaded

    # 多个插件依次加载
    async def test_load_multiple(self, loader, bot, hooks):
        await loader.load_plugin(SimplePlugin(), bot, hooks)
        await loader.load_plugin(ToolPlugin(), bot, hooks)
        assert len(loader.loaded) == 2


# endregion


# region 去重
class TestPluginLoaderDedup:
    """同名插件去重: 第二次 load 被拒绝, 不影响已加载的."""

    async def test_duplicate_name_rejected(self, loader, bot, hooks):
        await loader.load_plugin(SimplePlugin(), bot, hooks)
        dup = SimplePlugin()  # 同 name="simple"
        await loader.load_plugin(dup, bot, hooks)
        assert len(loader.loaded) == 1
        assert dup not in loader.loaded


# endregion


# region 错误隔离
class TestPluginLoaderErrorIsolation:
    """setup 失败: 不加入 loaded, 不影响后续插件."""

    async def test_failing_plugin_not_loaded(self, loader, bot, hooks):
        await loader.load_plugin(FailingPlugin(), bot, hooks)
        assert len(loader.loaded) == 0

    async def test_failing_plugin_does_not_block_others(self, loader, bot, hooks):
        await loader.load_plugin(FailingPlugin(), bot, hooks)
        await loader.load_plugin(SimplePlugin(), bot, hooks)
        assert len(loader.loaded) == 1
        assert loader.loaded[0].name == "simple"


# endregion


# region teardown
class TestPluginLoaderTeardown:
    """teardown_all: 逆序 LIFO, 单个 teardown 异常不中断."""

    async def test_teardown_lifo_order(self, loader, bot, hooks):
        order = []
        await loader.load_plugin(TeardownTracker("A", order), bot, hooks)
        await loader.load_plugin(TeardownTracker("B", order), bot, hooks)
        await loader.load_plugin(TeardownTracker("C", order), bot, hooks)
        await loader.teardown_all()
        assert order == ["C", "B", "A"]

    async def test_teardown_error_does_not_block(self, loader, bot, hooks):
        order = []

        class BadTeardown(Plugin):
            name = "bad_td"
            async def setup(self, bot): pass
            def hooks(self): return []
            async def teardown(self):
                order.append("bad")
                raise RuntimeError("teardown boom")

        await loader.load_plugin(TeardownTracker("first", order), bot, hooks)
        await loader.load_plugin(BadTeardown(), bot, hooks)
        await loader.load_plugin(TeardownTracker("last", order), bot, hooks)
        await loader.teardown_all()
        # 逆序: last → bad(异常但仍记录) → first
        assert order == ["last", "bad", "first"]

    async def test_loaded_cleared_after_teardown(self, loader, bot, hooks):
        await loader.load_plugin(SimplePlugin(), bot, hooks)
        await loader.teardown_all()
        assert len(loader.loaded) == 0


# endregion


# region schedules warning
class TestPluginLoaderSchedules:
    """schedules: T14 未实现前, 只打 warning 不注册."""

    async def test_schedules_logged_as_warning(self, loader, bot, hooks, caplog):
        with caplog.at_level(logging.WARNING, logger="acabot.plugin.loader"):
            await loader.load_plugin(SchedulePlugin(), bot, hooks)
        assert any("schedule" in r.message.lower() for r in caplog.records)

# endregion
