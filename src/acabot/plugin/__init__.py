"""plugin package 只导出稳定协议和 BotContext.

PluginLoader 需要按模块路径显式导入, 避免 package import 时递归拉起 hook 相关可选依赖.
"""

from .base import Plugin, ScheduleDef
from .context import BotContext

__all__ = [
    "BotContext",
    "Plugin",
    "ScheduleDef",
]
