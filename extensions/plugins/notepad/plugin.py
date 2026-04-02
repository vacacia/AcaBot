"""NotepadPlugin — 便签记忆插件.

通过 KVStore 存储用户/群级便签, 在 PRE_LLM 阶段注入 LLM 上下文.
当前版本只做注入(读取), 写入工具留到后续版本.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from acabot.plugin.base import Plugin
from acabot.types import HookPoint

from .inject import NotepadInjectHook

if TYPE_CHECKING:
    from acabot.hook import Hook
    from acabot.plugin.context import BotContext

logger = logging.getLogger("acabot.plugin.notepad")


class NotepadPlugin(Plugin):
    """便签插件.

    生命周期:
        setup → 保存 bot 引用, 获取 kv 存储
        hooks → 注册 NotepadInjectHook(PRE_LLM)
        tools → 暂不注册工具

    Attributes:
        name: 插件标识.
    """

    name = "notepad"

    async def setup(self, bot: BotContext) -> None:
        """保存 bot 引用, 读取配置."""
        self._bot = bot
        self._config = bot.get_config(self.name)
        logger.info("NotepadPlugin setup: config=%s", self._config)

    def hooks(self) -> list[tuple[HookPoint, Hook]]:
        """注册 PRE_LLM 便签注入 hook."""
        return [
            (HookPoint.PRE_LLM, NotepadInjectHook(kv=self._bot.kv)),
        ]
