"""scheduler.service 提供 typed scheduler facade."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from .codec import parse_schedule_payload, serialize_schedule_payload
from .contracts import ScheduledTaskInfo
from .conversation_wakeup import ScheduledConversationWakeupDispatcher
from .scheduler import RuntimeScheduler

TASK_KIND_CONVERSATION_WAKEUP = "conversation_wakeup"
TASK_KIND_PLUGIN_HANDLER = "plugin_handler"


class ScheduledTaskConflictError(RuntimeError):
    """表示当前任务状态与操作请求冲突."""


class ScheduledTaskUnavailableError(RuntimeError):
    """表示 scheduler service 当前不可用."""


@dataclass(slots=True)
class PluginScheduler:
    """插件可见的稳定 scheduler facade."""

    plugin_id: str
    _service: "ScheduledTaskService"

    @property
    def owner(self) -> str:
        return f"plugin:{self.plugin_id}"

    async def create_handler_task(
        self,
        *,
        handler_name: str,
        schedule_payload: dict[str, Any],
        payload: dict[str, Any] | None = None,
    ) -> ScheduledTaskInfo:
        _ = handler_name, schedule_payload, payload
        raise NotImplementedError("plugin handler scheduled tasks are deferred this round")

    def list_tasks(self) -> list[ScheduledTaskInfo]:
        return self._service.list_tasks(owner=self.owner)

    async def cancel_task(self, *, task_id: str) -> bool:
        return await self._service.cancel_task(owner=self.owner, task_id=task_id)


class ScheduledTaskService:
    """统一的业务层 scheduler facade."""

    def __init__(
        self,
        *,
        scheduler: RuntimeScheduler,
        conversation_wakeup_dispatcher: ScheduledConversationWakeupDispatcher,
    ) -> None:
        self._scheduler = scheduler
        self._conversation_wakeup_dispatcher = conversation_wakeup_dispatcher
        self._scheduler.set_callback_resolver(self._resolve_callback_for_task)

    async def create_conversation_wakeup_task(
        self,
        *,
        owner: str,
        conversation_id: str,
        schedule_payload: dict[str, Any],
        note: str | None,
        created_by: str = "llm_tool",
        source: str = "builtin:scheduler",
    ) -> ScheduledTaskInfo:
        schedule = parse_schedule_payload(schedule_payload)
        task_id = f"sched:{uuid.uuid4().hex}"
        metadata = {
            "kind": TASK_KIND_CONVERSATION_WAKEUP,
            "conversation_id": str(conversation_id or "").strip(),
            "note": str(note or ""),
            "created_by": created_by,
            "source": source,
            "created_at": time.time(),
        }
        callback = await self._resolve_callback_for_metadata(
            task_id=task_id,
            owner=owner,
            metadata=metadata,
        )
        if callback is None:
            raise RuntimeError("failed to build callback for conversation wakeup task")
        await self._scheduler.register(
            task_id=task_id,
            owner=owner,
            schedule=schedule,
            callback=callback,
            persist=True,
            misfire_policy="skip",
            metadata=metadata,
        )
        return self._find_task(task_id)

    def list_tasks(self, *, owner: str) -> list[ScheduledTaskInfo]:
        return [task for task in self._scheduler.list_tasks() if task.owner == owner]

    def list_conversation_wakeup_tasks(
        self,
        *,
        conversation_id: str | None = None,
        enabled: bool | None = None,
        limit: int = 200,
    ) -> list[ScheduledTaskInfo]:
        tasks = [
            task
            for task in self._scheduler.list_tasks()
            if str(task.metadata.get("kind", "") or "") == TASK_KIND_CONVERSATION_WAKEUP
        ]
        if conversation_id:
            tasks = [
                task
                for task in tasks
                if str(task.metadata.get("conversation_id", "") or "") == conversation_id
            ]
        if enabled is not None:
            tasks = [task for task in tasks if task.enabled is enabled]
        tasks.sort(key=lambda item: item.created_at, reverse=True)
        return tasks[: max(1, limit)]

    async def cancel_task(self, *, owner: str, task_id: str) -> bool:
        task = next((item for item in self.list_tasks(owner=owner) if item.task_id == task_id), None)
        if task is None:
            return False
        return await self._scheduler.cancel(task_id)

    async def disable_conversation_wakeup_task(self, task_id: str) -> ScheduledTaskInfo:
        task = self._require_conversation_wakeup_task(task_id)
        _ = task
        if not await self._scheduler.disable(task_id):
            raise KeyError(task_id)
        return self._find_task(task_id)

    async def enable_conversation_wakeup_task(self, task_id: str) -> ScheduledTaskInfo:
        task = self._require_conversation_wakeup_task(task_id)
        try:
            if not await self._scheduler.enable(task_id):
                raise KeyError(task_id)
        except ValueError as exc:
            raise ScheduledTaskConflictError(str(exc)) from exc
        return self._find_task(task_id)

    async def delete_conversation_wakeup_task(self, task_id: str) -> bool:
        self._require_conversation_wakeup_task(task_id)
        return await self._scheduler.cancel(task_id)

    def serialize_task(self, task: ScheduledTaskInfo) -> dict[str, Any]:
        metadata = dict(task.metadata)
        return {
            "task_id": task.task_id,
            "owner": task.owner,
            "conversation_id": str(metadata.get("conversation_id", "") or task.owner),
            "note": str(metadata.get("note", "") or ""),
            "kind": str(metadata.get("kind", "") or ""),
            "schedule": serialize_schedule_payload(task.schedule),
            "persist": task.persist,
            "misfire_policy": task.misfire_policy,
            "next_fire_at": task.next_fire_at,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "last_fired_at": task.last_fired_at,
            "enabled": task.enabled,
            "metadata": metadata,
        }

    def build_plugin_scheduler(self, *, plugin_id: str) -> PluginScheduler:
        return PluginScheduler(plugin_id=plugin_id, _service=self)

    async def _resolve_callback_for_task(
        self,
        task: ScheduledTaskInfo,
    ):
        return await self._resolve_callback_for_metadata(
            task_id=task.task_id,
            owner=task.owner,
            metadata=task.metadata,
        )

    async def _resolve_callback_for_metadata(
        self,
        *,
        task_id: str,
        owner: str,
        metadata: dict[str, Any],
    ):
        kind = str(metadata.get("kind", "") or "").strip()
        if kind == TASK_KIND_CONVERSATION_WAKEUP:
            conversation_id = str(metadata.get("conversation_id", "") or owner).strip()
            note = str(metadata.get("note", "") or "")
            return self._conversation_wakeup_dispatcher.make_callback(
                task_id=task_id,
                conversation_id=conversation_id,
                note=note,
                metadata={
                    "owner": owner,
                    "conversation_id": conversation_id,
                },
            )
        if kind == TASK_KIND_PLUGIN_HANDLER:
            return None
        return None

    def _require_conversation_wakeup_task(self, task_id: str) -> ScheduledTaskInfo:
        task = self._find_task(task_id)
        if str(task.metadata.get("kind", "") or "") != TASK_KIND_CONVERSATION_WAKEUP:
            raise KeyError(task_id)
        return task

    def _find_task(self, task_id: str) -> ScheduledTaskInfo:
        task = self._find_task_or_none(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def _find_task_or_none(self, task_id: str) -> ScheduledTaskInfo | None:
        for task in self._scheduler.list_tasks():
            if task.task_id == task_id:
                return task
        return None


__all__ = [
    "PluginScheduler",
    "ScheduledTaskConflictError",
    "ScheduledTaskService",
    "ScheduledTaskUnavailableError",
    "TASK_KIND_CONVERSATION_WAKEUP",
    "TASK_KIND_PLUGIN_HANDLER",
]
