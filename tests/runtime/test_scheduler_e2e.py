"""scheduler 端到端测试.

验证链路:
- 伪造 inbound event 进入 RuntimeApp
- fake agent 通过 builtin scheduler tool 创建任务
- RuntimeScheduler 到时触发 synthetic scheduled event
- agent 在原 conversation 中被再次唤醒并回复
- interval / one_shot / cron 三种 schedule 都覆盖
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest

from acabot.agent import AgentResponse, ToolCallRecord
from acabot.config import Config
from acabot.runtime import RuntimeModelRequest, build_runtime_components
from acabot.runtime.scheduler import CronSchedule, RuntimeScheduler
from acabot.types import EventSource, MsgSegment, StandardEvent
from tests.runtime.test_bootstrap import _write_minimal_session
from tests.runtime.test_outbox import FakeGateway


# region fake agent
@dataclass
class SchedulerE2EAgent:
    """用于 scheduler 端到端链路的 fake agent.

    第一次收到真实用户消息时创建定时任务并立刻 list 一次.
    后续收到 synthetic scheduled event 时回复一条文本, 并在需要时取消任务.
    """

    schedule_payload_factory: Callable[[], dict[str, Any]]
    note: str
    created_text: str
    fired_text: str
    cancel_after_fire: bool = True
    calls: list[dict[str, Any]] = field(default_factory=list)
    created_task_id: str | None = None
    listed_task_ids: list[str] = field(default_factory=list)
    wake_call_count: int = 0
    cancel_results: list[dict[str, Any]] = field(default_factory=list)

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        request_options=None,
        max_tool_rounds=None,
        tools=None,
        tool_executor=None,
    ) -> AgentResponse:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "model": model,
                "request_options": dict(request_options or {}),
                "max_tool_rounds": max_tool_rounds,
                "tools": list(tools or []),
                "tool_executor": tool_executor,
            }
        )
        assert tool_executor is not None

        if self.created_task_id is None:
            created = await tool_executor(
                "scheduler",
                {
                    "action": "create",
                    "schedule": self.schedule_payload_factory(),
                    "note": self.note,
                },
            )
            created_payload = json.loads(str(created.content))
            self.created_task_id = str(created_payload["task_id"])

            listed = await tool_executor("scheduler", {"action": "list"})
            listed_payload = json.loads(str(listed.content))
            self.listed_task_ids = [str(item["task_id"]) for item in listed_payload["tasks"]]

            return AgentResponse(
                text=self.created_text,
                model_used=model or "",
                tool_calls_made=[
                    ToolCallRecord(
                        name="scheduler",
                        arguments={
                            "action": "create",
                            "schedule": self.schedule_payload_factory(),
                            "note": self.note,
                        },
                        result={"status": "ok", "task_id": self.created_task_id},
                    ),
                    ToolCallRecord(
                        name="scheduler",
                        arguments={"action": "list"},
                        result={"status": "ok", "task_ids": list(self.listed_task_ids)},
                    ),
                ],
            )

        self.wake_call_count += 1
        if self.cancel_after_fire and self.created_task_id:
            cancelled = await tool_executor(
                "scheduler",
                {"action": "cancel", "task_id": self.created_task_id},
            )
            self.cancel_results.append(json.loads(str(cancelled.content)))

        return AgentResponse(
            text=self.fired_text,
            model_used=model or "",
            tool_calls_made=[
                ToolCallRecord(
                    name="scheduler",
                    arguments={"action": "cancel", "task_id": self.created_task_id},
                    result=(self.cancel_results[-1] if self.cancel_results else {"status": "skipped"}),
                )
            ],
        )


# endregion


# region helpers

def _config(tmp_path: Path) -> Config:
    return Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "filesystem": {"base_dir": str(tmp_path)},
                "runtime_root": str(tmp_path / "runtime_data"),
            },
        }
    )



def _event(*, text: str = "帮我创建一个定时任务") -> StandardEvent:
    return StandardEvent(
        event_id=f"evt-{int(time.time() * 1000)}",
        event_type="message",
        platform="qq",
        timestamp=int(time.time()),
        source=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        segments=[MsgSegment(type="text", data={"text": text})],
        raw_message_id=f"msg-{int(time.time() * 1000)}",
        sender_nickname="acacia",
        sender_role=None,
    )


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 1.5) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met before timeout")


async def _run_scheduler_e2e(
    tmp_path: Path,
    *,
    agent: SchedulerE2EAgent,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> tuple[Any, FakeGateway]:
    _write_minimal_session(tmp_path, visible_tools=["scheduler"])
    gateway = FakeGateway()
    components = build_runtime_components(
        _config(tmp_path),
        gateway=gateway,
        agent=agent,
    )
    runtime_model_request = RuntimeModelRequest(
        provider_kind="openai_compatible",
        model="openai/test-model",
        supports_tools=True,
        provider_id="provider",
        preset_id="main",
        provider_params={"base_url": "https://example.invalid/v1"},
    )
    components.app._resolve_model_requests = lambda decision, agent: (  # type: ignore[method-assign]
        runtime_model_request,
        None,
        runtime_model_request,
    )

    components.app.install()
    await components.scheduler.start()
    try:
        assert gateway.handler is not None
        await gateway.handler(_event())
        await _wait_until(
            lambda: len(gateway.sent) >= 2 and agent.wake_call_count >= 1,
            timeout=2.0,
        )
        await asyncio.sleep(0.12)
        return components, gateway
    finally:
        await components.scheduler.stop()


def _sent_texts(gateway: FakeGateway) -> list[str]:
    return [str(action.payload.get("text", "")) for action in gateway.sent]


# endregion


async def test_scheduler_interval_e2e_creates_lists_fires_and_cancels(tmp_path: Path) -> None:
    agent = SchedulerE2EAgent(
        schedule_payload_factory=lambda: {"kind": "interval", "spec": {"seconds": 0.05}},
        note="[scheduler-e2e] interval fired",
        created_text="interval task created",
        fired_text="interval wakeup handled",
        cancel_after_fire=True,
    )

    components, gateway = await _run_scheduler_e2e(tmp_path, agent=agent)

    assert _sent_texts(gateway) == ["interval task created", "interval wakeup handled"]
    assert agent.created_task_id is not None
    assert agent.listed_task_ids == [agent.created_task_id]
    assert agent.wake_call_count >= 1
    assert agent.cancel_results[-1]["action"] == "cancelled"
    assert components.scheduler.list_tasks() == []

    events = await components.channel_event_store.get_thread_events("qq:user:10001")
    assert [item.content_text for item in events] == ["帮我创建一个定时任务", "[scheduler-e2e] interval fired"]
    assert events[1].raw_event["synthetic"] is True
    assert events[1].raw_event["conversation_id"] == "qq:user:10001"
    assert events[1].payload_json["metadata"]["synthetic"] is True
    assert events[1].payload_json["metadata"]["source"] == "scheduler"
    assert events[1].payload_json["metadata"]["scheduled_task"]["task_id"] == agent.created_task_id

    delivered = await components.message_store.get_thread_messages("qq:user:10001")
    assert [item.content_text for item in delivered][:2] == ["interval task created", "interval wakeup handled"]


async def test_scheduler_one_shot_e2e_creates_and_fires_in_same_conversation(tmp_path: Path) -> None:
    agent = SchedulerE2EAgent(
        schedule_payload_factory=lambda: {
            "kind": "one_shot",
            "spec": {"fire_at": time.time() + 0.05},
        },
        note="[scheduler-e2e] one-shot fired",
        created_text="one-shot task created",
        fired_text="one-shot wakeup handled",
        cancel_after_fire=False,
    )

    components, gateway = await _run_scheduler_e2e(tmp_path, agent=agent)

    assert _sent_texts(gateway) == ["one-shot task created", "one-shot wakeup handled"]
    assert agent.created_task_id is not None
    assert agent.listed_task_ids == [agent.created_task_id]
    assert agent.wake_call_count == 1
    assert components.scheduler.list_tasks() == []

    events = await components.channel_event_store.get_thread_events("qq:user:10001")
    assert [item.content_text for item in events] == ["帮我创建一个定时任务", "[scheduler-e2e] one-shot fired"]
    assert events[1].payload_json["metadata"]["scheduled_task"]["kind"] == "conversation_wakeup"
    assert len(gateway.sent) == 2


async def test_scheduler_cron_e2e_creates_and_fires_via_synthetic_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_compute_initial_fire = RuntimeScheduler._compute_initial_fire

    def _patched_compute_initial_fire(schedule):
        if isinstance(schedule, CronSchedule):
            return time.time() + 0.05
        return original_compute_initial_fire(schedule)

    monkeypatch.setattr(RuntimeScheduler, "_compute_initial_fire", staticmethod(_patched_compute_initial_fire))

    agent = SchedulerE2EAgent(
        schedule_payload_factory=lambda: {"kind": "cron", "spec": {"expr": "* * * * *"}},
        note="[scheduler-e2e] cron fired",
        created_text="cron task created",
        fired_text="cron wakeup handled",
        cancel_after_fire=True,
    )

    components, gateway = await _run_scheduler_e2e(tmp_path, agent=agent)

    assert _sent_texts(gateway) == ["cron task created", "cron wakeup handled"]
    assert agent.created_task_id is not None
    assert agent.listed_task_ids == [agent.created_task_id]
    assert agent.wake_call_count >= 1
    assert agent.cancel_results[-1]["action"] == "cancelled"

    events = await components.channel_event_store.get_thread_events("qq:user:10001")
    assert [item.content_text for item in events] == ["帮我创建一个定时任务", "[scheduler-e2e] cron fired"]
    assert len(gateway.sent) == 2
