from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable

from acabot.types import StandardEvent, Action


class BaseGateway(ABC):
    """网关接口 — 负责平台协议与内部标准格式的双向翻译.

    换平台(如从 QQ 换到 Discord)只需实现这一个接口.
    """

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send(self, action: Action) -> dict[str, Any] | None: ...

    @abstractmethod
    def on_event(self, handler: Callable[[StandardEvent], Awaitable[None]]) -> None: ...

    @abstractmethod
    async def call_api(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """通用 API 调用. 
        
        OneBot API 不能全封装成 ActionType, 查询型用此方法.
        如 get_msg, get_group_member_info, get_forward_msg 等.
        """
        ...
