"""PluginLoader — 插件加载/注册/清理.

1. 加载: 接收 Plugin 实例 → setup(bot) → 注册 hooks → 注册 tools
2. 管理: 维护 loaded 列表, 按 name 去重, 错误隔离
3. 清理: teardown_all() → 逆序 LIFO 调用所有插件的 teardown()

TODO:
- 运行时 enable/disable
- 热重载
"""

from __future__ import annotations

import logging

from .base import Plugin
from .context import BotContext
from acabot.hook import HookRegistry

logger = logging.getLogger("acabot.plugin.loader")


class PluginLoader:
    """管理 Plugin 的完整生命周期.

    加载顺序: 按 load_plugin 调用顺序(即 config 中的列表顺序).
    卸载顺序: 逆序 LIFO, 先加载的后清理.

    Attributes:
        loaded: 已成功加载的插件列表, 保持加载顺序.
    """

    def __init__(self) -> None:
        self.loaded: list[Plugin] = []
        self._names: set[str] = set()

    # region 加载
    async def load_plugin(
        self,
        plugin: Plugin,
        bot: BotContext,
        hooks: HookRegistry,
    ) -> None:
        """加载单个插件: setup → 注册 hooks/tools/schedules.
            - 插件按 plugin.name 去重
            - 只有 setup 成功的插件才注册 hooks/tools 并进入 loaded 列表

        Args:
            plugin: 要加载的插件实例.
            bot: 框架上下文, 传给 plugin.setup().
            hooks: Hook 注册表, 用于注册插件的 hook.
        """
        # 去重
        if plugin.name in self._names:
            logger.warning(f"Plugin '{plugin.name}' already loaded, skipping")
            return

        # setup — 错误隔离
        try:
            await plugin.setup(bot)
        except Exception:
            logger.exception(f"Plugin '{plugin.name}' setup failed, skipping")
            return

        # 注册 hooks
        for point, hook in plugin.hooks():
            hooks.register(point, hook)

        # 注册 tools — 从 bot.agent 获取, 不额外传参
        for tool in plugin.tools():
            bot.agent.register_tool(tool)

        # schedules — T14 ScheduleManager 未实现, 只打 warning
        for sched in plugin.schedules():
            label = sched.name or f"{plugin.name}_unnamed"
            logger.warning(
                f"Plugin '{plugin.name}' has schedule '{label}' "
                f"but ScheduleManager is not available yet (T14)"
            )

        self.loaded.append(plugin)
        self._names.add(plugin.name)

        n_hooks = len(plugin.hooks())
        n_tools = len(plugin.tools())
        logger.info(f"Plugin loaded: {plugin.name} ({n_hooks} hooks, {n_tools} tools)")

    # endregion

    # region 清理
    async def teardown_all(self) -> None:
        """逆序清理所有已加载插件.

        LIFO 顺序: 最后加载的先 teardown, 确保上层插件先释放资源.
        单个 teardown 异常不中断后续清理.
        """
        for plugin in reversed(self.loaded):
            try:
                await plugin.teardown()
            except Exception:
                logger.exception(f"Plugin '{plugin.name}' teardown failed")

        self.loaded.clear()
        self._names.clear()
        logger.info("All plugins torn down")

    # endregion
