"""Hook 基类 — 所有 hook 的统一接口."""

from __future__ import annotations

from abc import ABC, abstractmethod

from acabot.types import HookResult, HookContext


class Hook(ABC):
    """Hook 基类.

    Attributes:
        name: hook 名, 用于日志标识.
        priority: 执行优先级, 越小越先执行.
        enabled: 开关, 是否启用此 Hook, False 则跳过.
    """
    name: str
    priority: int = 100
    enabled: bool = True

    @abstractmethod
    async def handle(self, ctx: HookContext) -> HookResult:
        """处理 hook.

        Args:
            ctx: 当前 Pipeline 的共享上下文, 可读可改.

        Returns:
            HookResult, 控制后续行为(continue/skip_llm/abort).
        """
        ...
