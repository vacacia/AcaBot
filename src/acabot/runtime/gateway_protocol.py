"""runtime.gateway_protocol 定义 runtime 需要的最小 gateway 协议.

这样新 runtime 可以只依赖接口形状, 不会因为导入旧 gateway 包而带出额外依赖.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol

from acabot.types import Action, StandardEvent


class GatewayProtocol(Protocol):
    """runtime 视角下的最小 gateway 协议."""

    async def start(self) -> None:
        """启动 gateway.
        """

        ...

    async def stop(self) -> None:
        """停止 gateway.
        """

        ...

    async def send(self, action: Action) -> dict[str, object] | None:
        """发送一个动作到外部平台.

        Args:
            action: 待发送的动作对象.

        Returns:
            平台返回的原始回执, 或 None.
        """

        ...

    def on_event(self, handler: Callable[[StandardEvent], Awaitable[None]]) -> None:
        """注册标准事件处理器.

        Args:
            handler: 接收 StandardEvent 的异步处理函数.
        """

        ...
