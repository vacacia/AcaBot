"""Plugin 基类 — 所有插件的统一接口."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Awaitable, TYPE_CHECKING

from acabot.types import HookPoint
from acabot.agent import ToolDef
from .context import BotContext

if TYPE_CHECKING:
    from acabot.hook import Hook


@dataclass
class ScheduleDef:
    """定时任务定义.

    Attributes:
        cron: cron 表达式, 如 "0 22 * * *"(每天 22 点).
        handler: async 函数, 定时触发时调用.
        name: 任务名, 用于日志标识.
    """
    cron: str
    handler: Callable[[], Awaitable[None]]
    name: str = ""


class Plugin(ABC):
    """插件基类.

    生命周期: setup → hooks/tools/schedules → teardown.
    插件通过 setup() 拿到 BotContext, 之后通过它和框架交互.
    """
    name: str

    @abstractmethod
    async def setup(self, bot: BotContext) -> None:
        """启动时调用. 保存 bot 引用, 初始化资源(DB 连接/缓存预热等)."""
        ...

    @abstractmethod
    def hooks(self) -> list[tuple[HookPoint, Hook]]:
        """返回要注册的 (hook_point, hook_instance) 列表."""
        ...

    def tools(self) -> list[ToolDef]:
        """返回要注册给 Agent 的工具列表. 不需要 tool 的插件无需覆写."""
        return []

    def schedules(self) -> list[ScheduleDef]:
        """返回定时任务列表. PluginLoader 遍历后注册到 ScheduleManager."""
        return []

    async def teardown(self) -> None:
        """框架关闭或插件热卸载时调用. 清理资源(关 DB/释放连接等)."""
        pass
