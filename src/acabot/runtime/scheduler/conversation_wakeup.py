"""scheduler.conversation_wakeup 把定时任务触发转换为 synthetic conversation event."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..control.control_plane import RuntimeControlPlane

logger = logging.getLogger("acabot.runtime.scheduler.conversation_wakeup")


class ScheduledConversationWakeupDispatcher:
    """为 conversation_wakeup 任务生成 fire-time callback."""

    def __init__(
        self,
        control_plane_provider: Callable[[], "RuntimeControlPlane | None"],
    ) -> None:
        self._control_plane_provider = control_plane_provider

    def make_callback(
        self,
        *,
        task_id: str,
        conversation_id: str,
        note: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> Callable[[], Awaitable[None]]:
        async def callback() -> None:
            control_plane = self._control_plane_provider()
            if control_plane is None:
                logger.warning(
                    "Skip scheduled conversation wakeup without control plane: task_id=%s conversation_id=%s",
                    task_id,
                    conversation_id,
                )
                return

            is_group_conversation = conversation_id.startswith("qq:group:")
            payload_metadata = {
                "synthetic": True,
                "source": "scheduler",
                "scheduled_task": {
                    "task_id": task_id,
                    "kind": "conversation_wakeup",
                    **dict(metadata or {}),
                },
            }
            await control_plane.inject_synthetic_event(
                payload={
                    "conversation_id": conversation_id,
                    "text": str(note or "请处理这个定时任务。"),
                    "sender_nickname": "scheduler",
                    "targets_self": True,
                    "mentions_self": is_group_conversation,
                    "metadata": payload_metadata,
                }
            )

        return callback


__all__ = ["ScheduledConversationWakeupDispatcher"]
