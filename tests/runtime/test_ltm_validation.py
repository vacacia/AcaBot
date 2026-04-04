from pathlib import Path

import pyarrow as pa

from acabot.runtime.memory.long_term_memory.storage import LanceDbLongTermMemoryStore


class _ArrowTableStub:
    def __init__(self, column_names: list[str]) -> None:
        self.column_names = column_names


class _TableStub:
    def __init__(self, column_names: list[str]) -> None:
        self._column_names = column_names

    def to_arrow(self) -> _ArrowTableStub:
        return _ArrowTableStub(self._column_names)


class _BrokenTableStub:
    def __init__(self, message: str) -> None:
        self._message = message

    def to_arrow(self) -> pa.Table:
        raise RuntimeError(self._message)


def test_validate_reports_missing_required_columns(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")

    store._entries = _TableStub(  # type: ignore[assignment]
        [
            "entry_id",
            "conversation_id",
            "topic",
            "lexical_text",
        ]
    )

    result = store.validate()

    assert result.ok is False
    assert "memory_entries 表缺少必需列: ['lossless_restatement']" in result.errors


def test_validate_reports_missing_manifest(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    versions_dir = store.root_dir / "memory_entries.lance" / "_versions"
    for manifest_path in versions_dir.glob("*.manifest"):
        manifest_path.unlink()

    result = store.validate()

    assert result.ok is False
    assert "memory_entries manifest 缺失" in result.errors


def test_validate_reports_table_read_failure(tmp_path: Path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")

    store._failed_windows = _BrokenTableStub("kaboom")  # type: ignore[assignment]

    result = store.validate()

    assert result.ok is False
    assert "failed_windows 表读取失败: kaboom" in result.errors
