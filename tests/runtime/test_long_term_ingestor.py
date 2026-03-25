import asyncio

from acabot.runtime import (
    ConversationDelta,
    ConversationFact,
    InMemoryThreadManager,
    LongTermMemoryIngestor,
    ThreadLtmCursor,
)


class RacingWakeEvent:
    def __init__(self, on_clear) -> None:
        self._event = asyncio.Event()
        self._on_clear = on_clear
        self._triggered = False

    def set(self) -> None:
        self._event.set()

    def clear(self) -> None:
        if not self._triggered:
            self._triggered = True
            self._on_clear()
        self._event.clear()

    async def wait(self) -> None:
        await self._event.wait()


class FakeConversationFactReader:
    def __init__(self, deltas: dict[str, ConversationDelta]) -> None:
        self.deltas = deltas
        self.calls: list[tuple[str, int | None, int | None]] = []

    async def get_thread_delta(
        self,
        thread_id: str,
        after_event_id: int | None,
        after_message_id: int | None,
    ) -> ConversationDelta:
        self.calls.append((thread_id, after_event_id, after_message_id))
        return self.deltas.get(
            thread_id,
            ConversationDelta(
                facts=[],
                max_event_id=after_event_id,
                max_message_id=after_message_id,
            ),
        )


class RecordingLongTermMemoryWritePort:
    def __init__(self, *, succeed: bool = True) -> None:
        self.succeed = succeed
        self.cursors: dict[str, ThreadLtmCursor] = {}
        self.ingested_threads: list[str] = []
        self.ingest_calls = 0
        self._events: dict[str, asyncio.Event] = {}

    async def load_cursor(self, thread_id: str) -> ThreadLtmCursor | None:
        return self.cursors.get(thread_id)

    async def save_cursor(self, cursor: ThreadLtmCursor) -> None:
        self.cursors[cursor.thread_id] = cursor

    async def ingest_thread_delta(self, thread_id: str, delta: ConversationDelta) -> bool:
        self.ingest_calls += 1
        self.ingested_threads.append(thread_id)
        self._events.setdefault(thread_id, asyncio.Event()).set()
        _ = delta
        return self.succeed

    async def wait_until_ingested(self, thread_id: str) -> None:
        await asyncio.wait_for(self._events.setdefault(thread_id, asyncio.Event()).wait(), timeout=1)


class BlockingLongTermMemoryWritePort:
    def __init__(self) -> None:
        self.cursors: dict[str, ThreadLtmCursor] = {}
        self.completed_threads: list[str] = []
        self._started: dict[str, asyncio.Event] = {}
        self._release = asyncio.Event()

    async def load_cursor(self, thread_id: str) -> ThreadLtmCursor | None:
        return self.cursors.get(thread_id)

    async def save_cursor(self, cursor: ThreadLtmCursor) -> None:
        self.cursors[cursor.thread_id] = cursor

    async def ingest_thread_delta(self, thread_id: str, delta: ConversationDelta) -> bool:
        _ = delta
        self._started.setdefault(thread_id, asyncio.Event()).set()
        await self._release.wait()
        self.completed_threads.append(thread_id)
        return True

    async def wait_until_started(self, thread_id: str) -> None:
        await asyncio.wait_for(self._started.setdefault(thread_id, asyncio.Event()).wait(), timeout=1)

    def release(self) -> None:
        self._release.set()


class ExplodingLongTermMemoryWritePort(RecordingLongTermMemoryWritePort):
    def __init__(self, explode_thread_id: str) -> None:
        super().__init__()
        self.explode_thread_id = explode_thread_id

    async def ingest_thread_delta(self, thread_id: str, delta: ConversationDelta) -> bool:
        if thread_id == self.explode_thread_id:
            raise RuntimeError(f"boom:{thread_id}")
        return await super().ingest_thread_delta(thread_id, delta)


class ExplodingLoadCursorWritePort(RecordingLongTermMemoryWritePort):
    def __init__(self, explode_thread_id: str) -> None:
        super().__init__()
        self.explode_thread_id = explode_thread_id

    async def load_cursor(self, thread_id: str) -> ThreadLtmCursor | None:
        if thread_id == self.explode_thread_id:
            raise RuntimeError(f"boom:{thread_id}")
        return await super().load_cursor(thread_id)


class ExplodingSaveCursorWritePort(RecordingLongTermMemoryWritePort):
    def __init__(self, explode_thread_id: str) -> None:
        super().__init__()
        self.explode_thread_id = explode_thread_id

    async def save_cursor(self, cursor: ThreadLtmCursor) -> None:
        if cursor.thread_id == self.explode_thread_id:
            raise RuntimeError(f"boom:{cursor.thread_id}")
        await super().save_cursor(cursor)


class ExplodingListThreadsManager(InMemoryThreadManager):
    async def list_threads(self):
        raise RuntimeError("list threads exploded")


def _delta(source_id: str, *, max_event_id: int = 1, max_message_id: int | None = 1) -> ConversationDelta:
    return ConversationDelta(
        facts=[
            ConversationFact(
                thread_id="thread:1",
                timestamp=100,
                source_kind="channel_event",
                source_id=source_id,
                role="user",
                text="hello",
                payload={"text": "hello"},
                actor_id="qq:user:10001",
                actor_display_name="Acacia",
                channel_scope="thread:1",
                run_id=None,
            )
        ],
        max_event_id=max_event_id,
        max_message_id=max_message_id,
    )


async def test_long_term_memory_ingestor_consumes_thread_marked_before_start() -> None:
    thread_manager = InMemoryThreadManager()
    await thread_manager.get_or_create(thread_id="thread:1", channel_scope="thread:1")
    backend = RecordingLongTermMemoryWritePort()
    ingestor = LongTermMemoryIngestor(
        thread_manager=thread_manager,
        fact_reader=FakeConversationFactReader({"thread:1": _delta("evt-1")}),
        write_port=backend,
    )
    ingestor.mark_dirty("thread:1")

    await ingestor.start()
    await backend.wait_until_ingested("thread:1")
    await ingestor.stop()

    assert backend.ingested_threads == ["thread:1"]
    assert backend.cursors["thread:1"].last_event_id == 1


async def test_long_term_memory_ingestor_reconcile_marks_threads_with_pending_delta() -> None:
    thread_manager = InMemoryThreadManager()
    await thread_manager.get_or_create(thread_id="thread:2", channel_scope="thread:2")
    backend = RecordingLongTermMemoryWritePort()
    ingestor = LongTermMemoryIngestor(
        thread_manager=thread_manager,
        fact_reader=FakeConversationFactReader({"thread:2": _delta("evt-2", max_event_id=2)}),
        write_port=backend,
    )

    await ingestor.start()
    await backend.wait_until_ingested("thread:2")
    await ingestor.stop()

    assert backend.ingested_threads == ["thread:2"]
    assert backend.cursors["thread:2"].last_event_id == 2


async def test_long_term_memory_ingestor_does_not_retry_after_failed_ingest_until_new_signal() -> None:
    thread_manager = InMemoryThreadManager()
    backend = RecordingLongTermMemoryWritePort(succeed=False)
    ingestor = LongTermMemoryIngestor(
        thread_manager=thread_manager,
        fact_reader=FakeConversationFactReader({"thread:3": _delta("evt-3", max_event_id=3)}),
        write_port=backend,
    )

    await ingestor.start()
    ingestor.mark_dirty("thread:3")
    await backend.wait_until_ingested("thread:3")
    await asyncio.sleep(0.05)

    assert backend.ingest_calls == 1
    assert "thread:3" not in backend.cursors

    ingestor.mark_dirty("thread:3")
    await asyncio.sleep(0.05)
    await ingestor.stop()

    assert backend.ingest_calls == 2


async def test_long_term_memory_ingestor_stop_drains_inflight_thread_only() -> None:
    thread_manager = InMemoryThreadManager()
    await thread_manager.get_or_create(thread_id="thread:1", channel_scope="thread:1")
    await thread_manager.get_or_create(thread_id="thread:2", channel_scope="thread:2")
    backend = BlockingLongTermMemoryWritePort()
    ingestor = LongTermMemoryIngestor(
        thread_manager=thread_manager,
        fact_reader=FakeConversationFactReader(
            {
                "thread:1": _delta("evt-1"),
                "thread:2": _delta("evt-2", max_event_id=2),
            }
        ),
        write_port=backend,
    )
    ingestor.mark_dirty("thread:1")
    ingestor.mark_dirty("thread:2")

    await ingestor.start()
    await backend.wait_until_started("thread:1")

    stop_task = asyncio.create_task(ingestor.stop())
    await asyncio.sleep(0.05)
    backend.release()
    await stop_task

    assert backend.completed_threads == ["thread:1"]


async def test_long_term_memory_ingestor_does_not_lose_dirty_signal_during_worker_sleep() -> None:
    backend = RecordingLongTermMemoryWritePort()
    ingestor = LongTermMemoryIngestor(
        thread_manager=InMemoryThreadManager(),
        fact_reader=FakeConversationFactReader({"thread:race": _delta("evt-race", max_event_id=9)}),
        write_port=backend,
    )
    ingestor._wake_event = RacingWakeEvent(lambda: ingestor.mark_dirty("thread:race"))  # type: ignore[assignment]

    await ingestor.start()
    await backend.wait_until_ingested("thread:race")
    await ingestor.stop()

    assert backend.ingested_threads == ["thread:race"]


async def test_long_term_memory_ingestor_survives_single_thread_ingest_exception() -> None:
    backend = ExplodingLongTermMemoryWritePort("thread:1")
    ingestor = LongTermMemoryIngestor(
        thread_manager=InMemoryThreadManager(),
        fact_reader=FakeConversationFactReader(
            {
                "thread:1": _delta("evt-1"),
                "thread:2": _delta("evt-2", max_event_id=2),
            }
        ),
        write_port=backend,
    )

    ingestor.mark_dirty("thread:1")
    ingestor.mark_dirty("thread:2")

    await ingestor.start()
    await backend.wait_until_ingested("thread:2")
    await ingestor.stop()

    assert backend.ingested_threads == ["thread:2"]
    assert "thread:2" in backend.cursors


async def test_long_term_memory_ingestor_reconcile_survives_single_thread_cursor_failure() -> None:
    thread_manager = InMemoryThreadManager()
    await thread_manager.get_or_create(thread_id="thread:1", channel_scope="thread:1")
    await thread_manager.get_or_create(thread_id="thread:2", channel_scope="thread:2")
    backend = ExplodingLoadCursorWritePort("thread:1")
    ingestor = LongTermMemoryIngestor(
        thread_manager=thread_manager,
        fact_reader=FakeConversationFactReader({"thread:2": _delta("evt-2", max_event_id=2)}),
        write_port=backend,
    )

    await ingestor.start()
    await backend.wait_until_ingested("thread:2")
    await ingestor.stop()

    assert backend.ingested_threads == ["thread:2"]


async def test_long_term_memory_ingestor_survives_startup_list_threads_failure() -> None:
    backend = RecordingLongTermMemoryWritePort()
    ingestor = LongTermMemoryIngestor(
        thread_manager=ExplodingListThreadsManager(),
        fact_reader=FakeConversationFactReader({"thread:3": _delta("evt-3", max_event_id=3)}),
        write_port=backend,
    )

    await ingestor.start()
    ingestor.mark_dirty("thread:3")
    await backend.wait_until_ingested("thread:3")
    await ingestor.stop()

    assert backend.ingested_threads == ["thread:3"]


async def test_long_term_memory_ingestor_survives_cursor_save_failure() -> None:
    backend = ExplodingSaveCursorWritePort("thread:1")
    ingestor = LongTermMemoryIngestor(
        thread_manager=InMemoryThreadManager(),
        fact_reader=FakeConversationFactReader(
            {
                "thread:1": _delta("evt-1"),
                "thread:2": _delta("evt-2", max_event_id=2),
            }
        ),
        write_port=backend,
    )

    ingestor.mark_dirty("thread:1")
    ingestor.mark_dirty("thread:2")

    await ingestor.start()
    await backend.wait_until_ingested("thread:2")
    await ingestor.stop()

    assert backend.ingested_threads == ["thread:1", "thread:2"]
    assert "thread:1" not in backend.cursors
    assert "thread:2" in backend.cursors
