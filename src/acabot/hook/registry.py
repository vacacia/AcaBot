"""HookRegistry + run_hooks — hook 注册与执行."""

from __future__ import annotations

import logging

from acabot.types import HookPoint, HookResult, HookContext
from .base import Hook

logger = logging.getLogger("acabot.hook")


class HookRegistry:
    """按 HookPoint 分组管理所有注册的 hook."""

    def __init__(self):
        self._hooks: dict[HookPoint, list[Hook]] = {}

    def register(self, point: HookPoint, hook: Hook) -> None:
        """注册 hook 到指定 hook 点, 按 priority 排序."""
        if point not in self._hooks:
            self._hooks[point] = []
        self._hooks[point].append(hook)
        self._hooks[point].sort(key=lambda h: h.priority)
        logger.info(f"Hook registered: {hook.name} @ {point.value} (priority={hook.priority})")

    def get(self, point: HookPoint) -> list[Hook]:
        """获取指定 hook 点的所有已启用 hook, 按优先级排序."""
        return [h for h in self._hooks.get(point, []) if h.enabled]


async def run_hooks(registry: HookRegistry, point: HookPoint, ctx: HookContext) -> HookResult:
    """按优先级在此 Hook Point 依次执行 hook.

    遇到 abort/skip_llm 立即停止并返回该结果.
    单个 hook 异常不中断链, 只 log.

    Returns:
        最终的 HookResult. 全部 continue 则返回默认 HookResult().
    """
    for hook in registry.get(point):
        try:
            result = await hook.handle(ctx)
            if result.action in ("abort", "skip_llm"):
                return result
        except Exception:
            logger.exception(f"Hook {hook.name} @ {point.value} failed")
    return HookResult()
