"""runtime.plugins 导出 runtime 的扩展插件集合.

这里放的是会参与 plugin 生命周期的扩展能力.
基础工具的注册入口位于 `runtime.builtin_tools`.
"""

from .backend_bridge_tool import BackendBridgeToolPlugin
from .napcat_tools import NapCatToolsPlugin
from .ops_control import OpsControlPlugin
from .reference_tools import ReferenceToolsPlugin
from .sticky_notes import StickyNotesPlugin

__all__ = [
    "BackendBridgeToolPlugin",
    "NapCatToolsPlugin",
    "OpsControlPlugin",
    "ReferenceToolsPlugin",
    "StickyNotesPlugin",
]
