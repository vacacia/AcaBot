from acabot.runtime import InMemoryRunManager, PersistedModelSnapshot, RouteDecision, RunStep
from acabot.types import EventSource, MsgSegment, StandardEvent


def _event() -> StandardEvent:
    return StandardEvent(
        event_id="evt-1",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        segments=[MsgSegment(type="text", data={"text": "hello"})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role=None,
    )


def _decision() -> RouteDecision:
    return RouteDecision(
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:user:10001",
    )


async def test_run_manager_waiting_approval_persists_context() -> None:
    manager = InMemoryRunManager()
    run = await manager.open(event=_event(), decision=_decision())

    await manager.mark_waiting_approval(
        run.run_id,
        reason="tool needs approval",
        approval_context={
            "approval_id": "approval:1",
            "tool_call_id": "toolcall:1",
            "required_action_ids": ["action:1"],
        },
    )

    updated = await manager.get(run.run_id)
    assert updated is not None
    assert updated.status == "waiting_approval"
    assert updated.approval_context["approval_id"] == "approval:1"
    assert updated.approval_context["tool_call_id"] == "toolcall:1"
    assert updated.finished_at is None


async def test_run_manager_clears_approval_context_on_terminal_state() -> None:
    manager = InMemoryRunManager()
    run = await manager.open(event=_event(), decision=_decision())

    await manager.mark_waiting_approval(
        run.run_id,
        reason="tool needs approval",
        approval_context={"approval_id": "approval:1"},
    )
    await manager.mark_failed(run.run_id, "approval prompt not delivered")

    updated = await manager.get(run.run_id)
    assert updated is not None
    assert updated.status == "failed"
    assert updated.approval_context == {}
    assert updated.finished_at is not None


async def test_run_manager_tracks_steps_and_cancellation() -> None:
    manager = InMemoryRunManager()
    run = await manager.open(event=_event(), decision=_decision())

    await manager.append_step(
        RunStep(
            step_id="step-1",
            run_id=run.run_id,
            thread_id=run.thread_id,
            step_type="route",
            status="completed",
            created_at=123,
        )
    )

    cancelled = await manager.cancel(run.run_id)

    assert cancelled is True
    assert manager.is_cancel_requested(run.run_id) is True


async def test_run_manager_can_list_steps_by_thread() -> None:
    manager = InMemoryRunManager()
    run = await manager.open(event=_event(), decision=_decision())

    await manager.append_step(
        RunStep(
            step_id="step-1",
            run_id=run.run_id,
            thread_id=run.thread_id,
            step_type="exec",
            status="completed",
            created_at=123,
        )
    )

    items = await manager.list_thread_steps(run.thread_id, step_types=["exec"])

    assert len(items) == 1
    assert items[0].thread_id == run.thread_id


async def test_run_manager_marks_interrupted_as_terminal_state() -> None:
    manager = InMemoryRunManager()
    run = await manager.open(event=_event(), decision=_decision())

    await manager.mark_running(run.run_id)
    await manager.mark_interrupted(run.run_id, "process restarted before run finished")

    updated = await manager.get(run.run_id)
    assert updated is not None
    assert updated.status == "interrupted"
    assert updated.error == "process restarted before run finished"
    assert updated.finished_at is not None


async def test_run_manager_open_persists_model_snapshot_metadata() -> None:
    manager = InMemoryRunManager()
    snapshot = PersistedModelSnapshot(
        binding_id="binding:aca",
        provider_id="openai-main",
        preset_id="preset:main",
        provider_kind="openai_compatible",
        api_key_env="OPENAI_API_KEY",
        model="gpt-main",
        context_window=128000,
        supports_tools=True,
        supports_vision=False,
        resolved_non_secret_params={"api_base": "https://llm.example.com/v1"},
    )

    run = await manager.open(
        event=_event(),
        decision=_decision(),
        model_snapshot=snapshot,
    )

    updated = await manager.get(run.run_id)

    assert updated is not None
    assert updated.metadata["model_snapshot"]["model"] == "gpt-main"
    assert updated.metadata["model_snapshot"]["binding_id"] == "binding:aca"
