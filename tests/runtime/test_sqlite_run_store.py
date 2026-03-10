from pathlib import Path

from acabot.runtime import SQLiteRunStore, StoreBackedRunManager, RouteDecision
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


async def test_store_backed_run_manager_persists_waiting_approval_context(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"

    store1 = SQLiteRunStore(db_path)
    manager1 = StoreBackedRunManager(store1)
    run = await manager1.open(event=_event(), decision=_decision())
    await manager1.mark_waiting_approval(
        run.run_id,
        reason="tool needs approval",
        approval_context={
            "approval_id": "approval:1",
            "tool_name": "shell.exec",
            "tool_arguments": {"cmd": "ls"},
            "required_action_ids": ["action:approval"],
        },
    )
    store1.close()

    store2 = SQLiteRunStore(db_path)
    manager2 = StoreBackedRunManager(store2)
    try:
        restored = await manager2.get(run.run_id)
        active_runs = await manager2.list_active()
    finally:
        store2.close()

    assert restored is not None
    assert restored.status == "waiting_approval"
    assert restored.approval_context["approval_id"] == "approval:1"
    assert restored.approval_context["tool_name"] == "shell.exec"
    assert [item.run_id for item in active_runs] == [run.run_id]


async def test_store_backed_run_manager_clears_approval_context_on_terminal_state(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    store = SQLiteRunStore(db_path)
    manager = StoreBackedRunManager(store)
    run = await manager.open(event=_event(), decision=_decision())

    try:
        await manager.mark_waiting_approval(
            run.run_id,
            reason="tool needs approval",
            approval_context={"approval_id": "approval:1"},
        )
        await manager.mark_completed(run.run_id)
        restored = await manager.get(run.run_id)
        active_runs = await manager.list_active()
    finally:
        store.close()

    assert restored is not None
    assert restored.status == "completed"
    assert restored.approval_context == {}
    assert active_runs == []


async def test_store_backed_run_manager_persists_interrupted_state(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    store = SQLiteRunStore(db_path)
    manager = StoreBackedRunManager(store)
    run = await manager.open(event=_event(), decision=_decision())

    try:
        await manager.mark_running(run.run_id)
        await manager.mark_interrupted(
            run.run_id,
            "process restarted before run finished",
        )
        restored = await manager.get(run.run_id)
        active_runs = await manager.list_active()
    finally:
        store.close()

    assert restored is not None
    assert restored.status == "interrupted"
    assert restored.error == "process restarted before run finished"
    assert active_runs == []
