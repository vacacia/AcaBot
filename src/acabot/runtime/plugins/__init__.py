"""runtime.plugins 导出 runtime 的扩展插件集合."""

from .backend_bridge_tool import BackendBridgeToolPlugin

__all__ = [
    "BackendBridgeToolPlugin",
]
