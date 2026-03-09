"""hook package 只导出稳定协议和运行入口.

这里默认只暴露 Hook 基类和 HookRegistry.
具体 hook implementation 需要按模块路径显式导入, 避免 package import 时拉起可选依赖.
"""

from .base import Hook
from .registry import HookRegistry, run_hooks

__all__ = [
    "Hook",
    "HookRegistry",
    "run_hooks",
]
