"""scheduler builtin tool surface."""

from __future__ import annotations

import json
from typing import Any

from acabot.agent import ToolSpec

from ..scheduler.service import ScheduledTaskService
from ..tool_broker import ToolBroker, ToolExecutionContext, ToolResult

BUILTIN_SCHEDULER_TOOL_SOURCE = "builtin:scheduler"


class BuiltinSchedulerToolSurface:
    """模型可见的 scheduler tool facade."""

    def __init__(self, *, service: ScheduledTaskService) -> None:
        self._service = service

    def register(self, tool_broker: ToolBroker) -> list[str]:
        tool_broker.unregister_source(BUILTIN_SCHEDULER_TOOL_SOURCE)
        tool_broker.register_tool(
            self._tool_spec(),
            self._handle_scheduler,
            source=BUILTIN_SCHEDULER_TOOL_SOURCE,
        )
        return ["scheduler"]

    @staticmethod
    def _tool_spec() -> ToolSpec:
        return ToolSpec(
            name="scheduler",
            description=(
                "创建、查看和取消定时任务。创建的任务绑定到当前会话，触发时会在原会话中唤醒一次 agent。"
                " create 时请优先使用标准格式：cron 用 spec.expr；interval 用 spec.seconds；one_shot 用 spec.fire_at。"
                " one_shot 的 fire_at 必须是 Unix 时间戳秒数（数字，例如 1775418000）。"
                " 不要优先使用 delay、at 或日期字符串；系统会尽量兼容，但标准写法最稳定。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "cancel"],
                        "description": "create=创建任务，list=列出当前会话任务，cancel=取消任务。",
                    },
                    "schedule": {
                        "type": "object",
                        "description": (
                            "调度配置。cron 使用 spec.expr；interval 使用 spec.seconds；"
                            "one_shot 使用 spec.fire_at（Unix 时间戳秒数字，例如 1775418000）。"
                        ),
                        "oneOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": ["cron"],
                                        "description": "cron 定时。",
                                    },
                                    "spec": {
                                        "type": "object",
                                        "properties": {
                                            "expr": {
                                                "type": "string",
                                                "description": "cron 表达式，例如 0 9 * * *。",
                                            }
                                        },
                                        "required": ["expr"],
                                        "additionalProperties": True,
                                    },
                                },
                                "required": ["kind", "spec"],
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": ["interval"],
                                        "description": "固定间隔。",
                                    },
                                    "spec": {
                                        "type": "object",
                                        "properties": {
                                            "seconds": {
                                                "type": "number",
                                                "description": "间隔秒数，必须是正数。",
                                            }
                                        },
                                        "required": ["seconds"],
                                        "additionalProperties": True,
                                    },
                                },
                                "required": ["kind", "spec"],
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "kind": {
                                        "type": "string",
                                        "enum": ["one_shot"],
                                        "description": "一次性提醒。",
                                    },
                                    "spec": {
                                        "type": "object",
                                        "properties": {
                                            "fire_at": {
                                                "type": "number",
                                                "description": "Unix 时间戳秒数，必须是数字，例如 1775418000。",
                                            }
                                        },
                                        "required": ["fire_at"],
                                        "additionalProperties": True,
                                    },
                                },
                                "required": ["kind", "spec"],
                            },
                        ],
                    },
                    "note": {
                        "type": "string",
                        "description": "定时任务触发时给 agent 的说明。",
                    },
                    "task_id": {
                        "type": "string",
                    },
                },
                "required": ["action"],
            },
        )

    async def _handle_scheduler(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        action = str(arguments.get("action", "") or "").strip()
        if action == "create":
            return await self._handle_create(arguments, ctx)
        if action == "list":
            return self._handle_list(ctx)
        if action == "cancel":
            return await self._handle_cancel(arguments, ctx)
        raise ValueError(f"unsupported scheduler action: {action!r}")

    async def _handle_create(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        conversation_id = self._resolve_channel_scope(ctx)
        schedule_payload = arguments.get("schedule")
        if not isinstance(schedule_payload, dict):
            raise ValueError("schedule is required for action=create")
        task = await self._service.create_conversation_wakeup_task(
            owner=conversation_id,
            conversation_id=conversation_id,
            schedule_payload=schedule_payload,
            note=str(arguments.get("note", "") or ""),
        )
        return ToolResult(
            llm_content=json.dumps(self._service.serialize_task(task), ensure_ascii=False)
        )

    def _handle_list(self, ctx: ToolExecutionContext) -> ToolResult:
        owner = self._resolve_channel_scope(ctx)
        tasks = [self._service.serialize_task(task) for task in self._service.list_tasks(owner=owner)]
        return ToolResult(llm_content=json.dumps({"tasks": tasks, "count": len(tasks)}, ensure_ascii=False))

    async def _handle_cancel(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        task_id = str(arguments.get("task_id", "") or "").strip()
        if not task_id:
            raise ValueError("task_id is required for action=cancel")
        success = await self._service.cancel_task(
            owner=self._resolve_channel_scope(ctx),
            task_id=task_id,
        )
        payload = {"action": "cancelled" if success else "not_found", "task_id": task_id}
        return ToolResult(llm_content=json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def _resolve_channel_scope(ctx: ToolExecutionContext) -> str:
        channel_scope = str(ctx.metadata.get("channel_scope", "") or "").strip()
        if channel_scope:
            return channel_scope
        if ctx.target.message_type == "group":
            return f"{ctx.target.platform}:group:{ctx.target.group_id}"
        return f"{ctx.target.platform}:user:{ctx.target.user_id}"


__all__ = ["BUILTIN_SCHEDULER_TOOL_SOURCE", "BuiltinSchedulerToolSurface"]
