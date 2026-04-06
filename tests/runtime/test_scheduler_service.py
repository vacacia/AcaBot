"""scheduler service / facade tests."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from acabot.runtime.scheduler import RuntimeScheduler, SQLiteScheduledTaskStore
from acabot.runtime.scheduler.codec import parse_schedule_payload, serialize_schedule_payload
from acabot.runtime.scheduler.conversation_wakeup import ScheduledConversationWakeupDispatcher
from acabot.runtime.scheduler.service import (
    PluginScheduler,
    ScheduledTaskConflictError,
    ScheduledTaskService,
)


@pytest.fixture()
def mock_control_plane():
    control_plane = MagicMock()
    control_plane.inject_synthetic_event = AsyncMock(return_value={"ok": True})
    return control_plane


@pytest.fixture()
def dispatcher(mock_control_plane):
    return ScheduledConversationWakeupDispatcher(lambda: mock_control_plane)


@pytest.fixture()
def scheduler():
    return RuntimeScheduler()


@pytest.fixture()
def service(scheduler, dispatcher):
    return ScheduledTaskService(
        scheduler=scheduler,
        conversation_wakeup_dispatcher=dispatcher,
    )


def test_schedule_codec_round_trip() -> None:
    payload = {"kind": "cron", "spec": {"expr": "0 9 * * *"}}
    schedule = parse_schedule_payload(payload)
    assert serialize_schedule_payload(schedule) == payload


def test_schedule_codec_accepts_one_shot_at_alias() -> None:
    schedule = parse_schedule_payload({"kind": "one_shot", "spec": {"at": 1775418000}})
    assert serialize_schedule_payload(schedule) == {"kind": "one_shot", "spec": {"fire_at": 1775418000.0}}


def test_schedule_codec_accepts_one_shot_delay_string() -> None:
    before = time.time()
    schedule = parse_schedule_payload({"kind": "one_shot", "spec": {"delay": "120s"}})
    payload = serialize_schedule_payload(schedule)
    fire_at = float(payload["spec"]["fire_at"])
    assert before + 119 <= fire_at <= time.time() + 121


def test_schedule_codec_accepts_one_shot_iso_datetime_string() -> None:
    iso_value = "2030-01-02T03:04:05+00:00"
    schedule = parse_schedule_payload({"kind": "one_shot", "spec": {"fire_at": iso_value}})
    payload = serialize_schedule_payload(schedule)
    assert payload == {
        "kind": "one_shot",
        "spec": {"fire_at": datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc).timestamp()},
    }


async def test_create_conversation_wakeup_task_registers_owner_and_metadata(service: ScheduledTaskService) -> None:
    task = await service.create_conversation_wakeup_task(
        owner="qq:user:10001",
        conversation_id="qq:user:10001",
        schedule_payload={"kind": "interval", "spec": {"seconds": 60}},
        note="提醒我看日报",
    )

    assert task.owner == "qq:user:10001"
    assert task.metadata["kind"] == "conversation_wakeup"
    assert task.metadata["conversation_id"] == "qq:user:10001"
    assert task.metadata["note"] == "提醒我看日报"
    assert service.list_tasks(owner="qq:user:10001")[0].task_id == task.task_id


async def test_cancel_task_checks_owner(service: ScheduledTaskService) -> None:
    task = await service.create_conversation_wakeup_task(
        owner="qq:user:10001",
        conversation_id="qq:user:10001",
        schedule_payload={"kind": "interval", "spec": {"seconds": 60}},
        note="提醒",
    )

    assert await service.cancel_task(owner="qq:user:99999", task_id=task.task_id) is False
    assert len(service.list_tasks(owner="qq:user:10001")) == 1

    assert await service.cancel_task(owner="qq:user:10001", task_id=task.task_id) is True
    assert service.list_tasks(owner="qq:user:10001") == []


async def test_service_lists_conversation_wakeup_tasks_for_webui(service: ScheduledTaskService) -> None:
    await service.create_conversation_wakeup_task(
        owner="qq:user:10001",
        conversation_id="qq:user:10001",
        schedule_payload={"kind": "interval", "spec": {"seconds": 60}},
        note="提醒 A",
    )
    await service.create_conversation_wakeup_task(
        owner="qq:user:20002",
        conversation_id="qq:user:20002",
        schedule_payload={"kind": "cron", "spec": {"expr": "0 9 * * *"}},
        note="提醒 B",
    )

    tasks = service.list_conversation_wakeup_tasks(limit=10)
    assert len(tasks) == 2
    assert {task.metadata["conversation_id"] for task in tasks} == {"qq:user:10001", "qq:user:20002"}

    filtered = service.list_conversation_wakeup_tasks(conversation_id="qq:user:20002", limit=10)
    assert len(filtered) == 1
    assert filtered[0].metadata["conversation_id"] == "qq:user:20002"


async def test_service_disable_and_enable_conversation_wakeup_task(service: ScheduledTaskService) -> None:
    task = await service.create_conversation_wakeup_task(
        owner="qq:user:10001",
        conversation_id="qq:user:10001",
        schedule_payload={"kind": "interval", "spec": {"seconds": 60}},
        note="提醒一下",
    )

    disabled = await service.disable_conversation_wakeup_task(task.task_id)
    assert disabled.enabled is False
    assert disabled.next_fire_at is None

    enabled = await service.enable_conversation_wakeup_task(task.task_id)
    assert enabled.enabled is True
    assert enabled.next_fire_at is not None
    assert enabled.next_fire_at > time.time()


async def test_service_enable_expired_one_shot_raises_conflict(service: ScheduledTaskService) -> None:
    task = await service.create_conversation_wakeup_task(
        owner="qq:user:10001",
        conversation_id="qq:user:10001",
        schedule_payload={"kind": "one_shot", "spec": {"fire_at": time.time() + 0.05}},
        note="一次性提醒",
    )

    await service.disable_conversation_wakeup_task(task.task_id)
    scheduler_task = service._scheduler._tasks[task.task_id]
    scheduler_task.schedule = parse_schedule_payload({"kind": "one_shot", "spec": {"fire_at": time.time() - 10}})

    with pytest.raises(ScheduledTaskConflictError):
        await service.enable_conversation_wakeup_task(task.task_id)


async def test_service_serialize_task_flattens_webui_fields(service: ScheduledTaskService) -> None:
    task = await service.create_conversation_wakeup_task(
        owner="qq:user:10001",
        conversation_id="qq:user:10001",
        schedule_payload={"kind": "interval", "spec": {"seconds": 60}},
        note="提醒一下",
    )

    payload = service.serialize_task(task)
    assert payload["conversation_id"] == "qq:user:10001"
    assert payload["note"] == "提醒一下"
    assert payload["kind"] == "conversation_wakeup"
    assert payload["created_at"] == task.created_at
    assert payload["last_fired_at"] is None


async def test_conversation_wakeup_callback_injects_scheduler_synthetic_event(
    service: ScheduledTaskService,
    scheduler: RuntimeScheduler,
    mock_control_plane,
) -> None:
    task = await service.create_conversation_wakeup_task(
        owner="qq:group:123",
        conversation_id="qq:group:123",
        schedule_payload={"kind": "interval", "spec": {"seconds": 60}},
        note="帮我总结今天群里的重点",
    )

    callback = scheduler._tasks[task.task_id].callback
    assert callback is not None

    await callback()

    mock_control_plane.inject_synthetic_event.assert_awaited_once()
    payload = mock_control_plane.inject_synthetic_event.await_args.kwargs["payload"]
    assert payload["conversation_id"] == "qq:group:123"
    assert payload["text"] == "帮我总结今天群里的重点"
    assert payload["sender_nickname"] == "scheduler"
    assert payload["mentions_self"] is True
    assert payload["metadata"]["synthetic"] is True
    assert payload["metadata"]["scheduled_task"]["task_id"] == task.task_id
    assert payload["metadata"]["scheduled_task"]["kind"] == "conversation_wakeup"


async def test_persisted_tasks_rebind_callback_on_scheduler_start(
    tmp_path: Path,
    dispatcher,
) -> None:
    store = SQLiteScheduledTaskStore(tmp_path / "scheduler.db")
    scheduler1 = RuntimeScheduler(store=store)
    service1 = ScheduledTaskService(
        scheduler=scheduler1,
        conversation_wakeup_dispatcher=dispatcher,
    )
    task = await service1.create_conversation_wakeup_task(
        owner="qq:user:10001",
        conversation_id="qq:user:10001",
        schedule_payload={"kind": "interval", "spec": {"seconds": 3600}},
        note="晚点提醒我",
    )

    scheduler2 = RuntimeScheduler(store=store)
    service2 = ScheduledTaskService(
        scheduler=scheduler2,
        conversation_wakeup_dispatcher=dispatcher,
    )

    await scheduler2.start()
    try:
        assert scheduler2.list_tasks()[0].task_id == task.task_id
        assert scheduler2._tasks[task.task_id].callback is not None
        assert service2.list_tasks(owner="qq:user:10001")[0].task_id == task.task_id
    finally:
        await scheduler2.stop()
        store.close()


async def test_plugin_scheduler_create_handler_task_is_explicitly_deferred(service: ScheduledTaskService) -> None:
    plugin_scheduler = service.build_plugin_scheduler(plugin_id="sample")

    assert isinstance(plugin_scheduler, PluginScheduler)
    with pytest.raises(NotImplementedError, match="deferred"):
        await plugin_scheduler.create_handler_task(
            handler_name="heartbeat",
            schedule_payload={"kind": "interval", "spec": {"seconds": 60}},
        )
