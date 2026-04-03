import asyncio
import shutil
import threading
from pathlib import Path

from acabot.config import Config
from acabot.runtime.bootstrap.builders import build_ltm_backup_task
from acabot.runtime.memory.long_term_ingestor import ThreadLtmCursor
from acabot.runtime.memory.long_term_memory.contracts import MemoryEntry, MemoryProvenance
from acabot.runtime.memory.long_term_memory.storage import LanceDbLongTermMemoryStore


def _entry(entry_id: str = "entry-1") -> MemoryEntry:
    return MemoryEntry(
        entry_id=entry_id,
        conversation_id="qq:group:42",
        created_at=10,
        updated_at=100,
        extractor_version="ltm-v1",
        topic="咖啡偏好",
        lossless_restatement="Alice 喜欢拿铁。",
        keywords=["latte"],
        persons=["Alice"],
        provenance=MemoryProvenance(fact_ids=["e:evt-1"]),
    )


def _config(tmp_path: Path, *, enabled: bool = True) -> Config:
    return Config(
        {
            "agent": {"system_prompt": "You are Aca."},
            "runtime": {
                "filesystem": {"base_dir": str(tmp_path)},
                "runtime_root": str(tmp_path / "runtime_data"),
                "long_term_memory": {
                    "enabled": True,
                    "backup": {
                        "enabled": enabled,
                        "interval_hours": 1,
                        "max_backups": 5,
                        "backup_dir": "long_term_memory/backups",
                    },
                },
            },
        }
    )


def test_build_ltm_backup_task_uses_runtime_config(tmp_path: Path) -> None:
    class FakeStore:
        def __init__(self) -> None:
            self.calls: list[tuple[Path, int]] = []

        def backup(self, target_dir: str | Path, *, max_backups: int = 5) -> Path:
            path = Path(target_dir)
            self.calls.append((path, max_backups))
            path.mkdir(parents=True, exist_ok=True)
            return path / "lancedb-backup-test"

    store = FakeStore()
    callback_and_interval = build_ltm_backup_task(_config(tmp_path), store=store)

    assert callback_and_interval is not None
    callback, interval_seconds = callback_and_interval
    assert interval_seconds == 3600

    asyncio.run(callback())

    assert store.calls
    backup_dir, max_backups = store.calls[0]
    assert backup_dir == (tmp_path / "runtime_data" / "long_term_memory" / "backups")
    assert max_backups == 5


def test_backup_creates_directory_copy(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "src")

    backup_path = store.backup(tmp_path / "backups")

    assert backup_path.exists()
    assert backup_path.name.startswith("lancedb-backup-")
    assert any(backup_path.iterdir())


def test_backup_contains_entries_data(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "src")
    store.upsert_entries([_entry()])

    backup_path = store.backup(tmp_path / "backups")
    restored = LanceDbLongTermMemoryStore(backup_path)

    assert restored.validate().ok is True
    assert restored.get_entry("entry-1") is not None


def test_backup_cleanup_old(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "src")

    for index in range(7):
        store.upsert_entries([_entry(entry_id=f"entry-{index}")])
        store.backup(tmp_path / "backups", max_backups=5)

    backups = sorted((tmp_path / "backups").iterdir(), key=lambda path: path.name)
    assert len(backups) == 5
    assert all(path.name.startswith("lancedb-backup-") for path in backups)


def test_backup_empty_store(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "src")

    backup_path = store.backup(tmp_path / "backups")

    assert backup_path.exists()


def test_backup_holds_write_lock_during_copy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "src")
    entered = threading.Event()
    release = threading.Event()

    def fake_copytree(src, dst, *args, **kwargs):
        _ = src, args, kwargs
        entered.set()
        release.wait(timeout=5)
        Path(dst).mkdir(parents=True, exist_ok=True)
        return dst

    monkeypatch.setattr(shutil, "copytree", fake_copytree)

    async def _run() -> None:
        backup_task = asyncio.create_task(asyncio.to_thread(store.backup, tmp_path / "backups"))
        await asyncio.to_thread(entered.wait, 5)

        upsert_task = asyncio.create_task(asyncio.to_thread(store.upsert_entries, [_entry("entry-lock")]))
        await asyncio.sleep(0.1)
        assert not upsert_task.done()

        release.set()
        await backup_task
        await upsert_task

    asyncio.run(_run())
