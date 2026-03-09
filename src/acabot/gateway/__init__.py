"""gateway package 只导出稳定接口.

这里默认只暴露 BaseGateway.
具体实现例如 NapCatGateway 需要按模块路径显式导入, 避免 package import 时拉起可选依赖.
"""

from .base import BaseGateway

__all__ = [
    "BaseGateway",
]
