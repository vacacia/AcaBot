"""builtin scheduler tool tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from acabot.runtime import ResolvedAgent, ToolExecutionContext
from acabot.runtime.builtin_tools.scheduler import BUILTIN_SCHEDULER_TOOL_SOURCE, BuiltinSchedulerToolSurface
from acabot.types import EventSource


class _FakeScheduledTaskService:
    def __init__(self) -> None:
        self.create_conversation_wakeup_task = AsyncMock(return_value=SimpleNamespace(
            task_id="task-1",
            owner="qq:user:10001",
            schedule=SimpleNamespace(),
            persist=True,
            misfire_policy="skip",
            next_fire_at=123.0,
            enabled=True,
            metadata={"kind": "conversation_wakeup", "conversation_id": "qq:user:10001", "note": "提醒"},
        ))
        self.list_tasks = MagicMock(return_value=[])
        self.cancel_task = AsyncMock(return_value=True)
        self.serialize_task = MagicMock(return_value={
            "task_id": "task-1",
            "owner": "qq:user:10001",
            "schedule": {"kind": "interval", "spec": {"seconds": 60}},
            "persist": True,
            "misfire_policy": "skip",
            "next_fire_at": 123.0,
            "enabled": True,
            "metadata": {"kind": "conversation_wakeup", "conversation_id": "qq:user:10001", "note": "提醒"},
        })


@pytest.fixture()
def ctx() -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id="run-1",
        thread_id="thread-1",
        actor_id="qq:user:10001",
        agent_id="aca",
        target=EventSource(platform="qq", message_type="private", user_id="10001", group_id=None),
        agent=ResolvedAgent(agent_id="aca", name="Aca", prompt_ref="prompt/default"),
        metadata={"channel_scope": "qq:user:10001"},
    )


@pytest.fixture()
def service() -> _FakeScheduledTaskService:
    return _FakeScheduledTaskService()


@pytest.fixture()
def surface(service: _FakeScheduledTaskService) -> BuiltinSchedulerToolSurface:
    return BuiltinSchedulerToolSurface(service=service)  # type: ignore[arg-type]


def test_register_registers_scheduler_tool(surface: BuiltinSchedulerToolSurface) -> None:
    broker = MagicMock()

    result = surface.register(broker)

    assert result == ["scheduler"]
    broker.unregister_source.assert_called_once_with(BUILTIN_SCHEDULER_TOOL_SOURCE)
    broker.register_tool.assert_called_once()


def test_tool_spec_documents_schedule_shapes(surface: BuiltinSchedulerToolSurface) -> None:
    spec = surface._tool_spec()
    schedule_schema = spec.parameters["properties"]["schedule"]
    assert "fire_at" in str(schedule_schema)
    assert "Unix" in str(schedule_schema)
    assert "delay" in str(spec.description)


async def test_handle_create_uses_channel_scope_owner(surface: BuiltinSchedulerToolSurface, service: _FakeScheduledTaskService, ctx: ToolExecutionContext) -> None:
    result = await surface._handle_scheduler(
        {
            "action": "create",
            "schedule": {"kind": "interval", "spec": {"seconds": 60}},
            "note": "提醒",
        },
        ctx,
    )

    service.create_conversation_wakeup_task.assert_awaited_once_with(
        owner="qq:user:10001",
        conversation_id="qq:user:10001",
        schedule_payload={"kind": "interval", "spec": {"seconds": 60}},
        note="提醒",
    )
    data = json.loads(result.llm_content)
    assert data["task_id"] == "task-1"


async def test_handle_list_filters_by_owner(surface: BuiltinSchedulerToolSurface, service: _FakeScheduledTaskService, ctx: ToolExecutionContext) -> None:
    task = SimpleNamespace(task_id="task-1")
    service.list_tasks.return_value = [task]

    result = await surface._handle_scheduler({"action": "list"}, ctx)

    service.list_tasks.assert_called_once_with(owner="qq:user:10001")
    service.serialize_task.assert_called_once_with(task)
    data = json.loads(result.llm_content)
    assert data["count"] == 1
    assert data["tasks"][0]["task_id"] == "task-1"


async def test_handle_cancel_scopes_by_owner(surface: BuiltinSchedulerToolSurface, service: _FakeScheduledTaskService, ctx: ToolExecutionContext) -> None:
    result = await surface._handle_scheduler({"action": "cancel", "task_id": "task-1"}, ctx)

    service.cancel_task.assert_awaited_once_with(owner="qq:user:10001", task_id="task-1")
    data = json.loads(result.llm_content)
    assert data["action"] == "cancelled"
