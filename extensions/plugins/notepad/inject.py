"""NotepadInjectHook — PRE_LLM 阶段注入便签内容到 LLM 上下文.

从 KVStore 读取用户级和群级便签, 作为 system 消息插入 ctx.messages 开头,
让 LLM 在回复时能参考便签中的提醒/备忘信息.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from acabot.hook.base import Hook
from acabot.types import HookResult, HookContext

if TYPE_CHECKING:
    from acabot.kv import BaseKVStore

logger = logging.getLogger("acabot.plugin.notepad")


class NotepadInjectHook(Hook):
    """PRE_LLM hook: 把便签内容注入 LLM 上下文.

    便签 key 格式:
        - 用户级: notepad:user:qq:{user_id}
        - 群级: notepad:group:qq:{group_id}

    Attributes:
        kv: 键值存储实例, 用于读取便签.
    """

    name = "notepad_inject"
    priority = 40
    enabled = True

    def __init__(self, kv: BaseKVStore) -> None:
        self.kv = kv

    async def handle(self, ctx: HookContext) -> HookResult:
        """读取便签并注入到 ctx.messages 开头."""
        source = ctx.event.source
        user_id = source.user_id
        group_id = source.group_id

        notes: list[str] = []

        # 用户级便签
        user_note = await self.kv.get(f"notepad:user:{source.platform}:{user_id}")
        if user_note:
            notes.append(user_note)

        # 群级便签(仅群聊时)
        if group_id:
            group_note = await self.kv.get(
                f"notepad:group:{source.platform}:{group_id}",
            )
            if group_note:
                notes.append(group_note)

        if notes:
            combined = "\n---\n".join(notes)
            ctx.messages.insert(0, {
                "role": "system",
                "content": f"[便签] {combined}",
            })
            logger.debug("Injected %d note(s) for user=%s group=%s", len(notes), user_id, group_id)

        return HookResult()
