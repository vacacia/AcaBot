"""runtime.control.log_buffer 提供给 WebUI 使用的轻量内存日志缓冲."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, replace
import logging
import threading
import time
from typing import Any

from .log_setup import extract_extra_fields, sanitize_log_record


@dataclass(slots=True)
class LogEntry:
    """一条可序列化的日志记录."""

    timestamp: float
    level: str
    logger: str
    message: str
    kind: str = "runtime"
    seq: int = 0
    extra: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.extra is None:
            self.extra = {}


class InMemoryLogBuffer:
    """线程安全的内存日志 ring buffer."""

    def __init__(self, max_entries: int = 2000) -> None:
        self.max_entries = max_entries
        self._items: deque[LogEntry] = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._next_seq = 1

    def append(self, entry: LogEntry) -> None:
        with self._lock:
            assigned = entry if int(entry.seq or 0) > 0 else replace(entry, seq=self._next_seq)
            self._items.append(assigned)
            self._next_seq = max(self._next_seq, int(assigned.seq or 0) + 1)

    def list_entries(
        self,
        *,
        after_seq: int = 0,
        level: str = "",
        keyword: str = "",
        limit: int = 500,
    ) -> dict[str, object]:
        normalized_level = str(level or "").strip().upper()
        normalized_keyword = str(keyword or "").strip().lower()
        normalized_after_seq = max(0, int(after_seq or 0))
        with self._lock:
            items = list(self._items)
            next_seq = self._next_seq - 1
        oldest_seq = int(items[0].seq or 0) if items else 0
        reset_required = bool(items and normalized_after_seq and normalized_after_seq < oldest_seq - 1)
        if normalized_level:
            items = [item for item in items if item.level.upper() == normalized_level]
        if normalized_keyword:
            items = [
                item
                for item in items
                if normalized_keyword in item.message.lower()
                or normalized_keyword in item.logger.lower()
                or any(normalized_keyword in str(key).lower() for key in item.extra)
                or any(normalized_keyword in str(value).lower() for value in item.extra.values())
            ]
        if normalized_after_seq:
            items = [item for item in items if int(item.seq or 0) > normalized_after_seq]
        items = items[-max(1, int(limit)) :]
        return {
            "items": [asdict(item) for item in items],
            "next_seq": next_seq,
            "reset_required": reset_required,
        }


class InMemoryLogHandler(logging.Handler):
    """把 logging 记录镜像进 InMemoryLogBuffer."""

    def __init__(self, buffer: InMemoryLogBuffer) -> None:
        super().__init__()
        self.buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        sanitized_message, sanitized_extra = sanitize_log_record(
            message=message,
            extra=extract_extra_fields(record),
        )
        self.buffer.append(
            LogEntry(
                timestamp=time.time(),
                level=str(record.levelname or "INFO"),
                logger=str(record.name or ""),
                message=sanitized_message,
                kind=str(getattr(record, "log_kind", "") or "runtime"),
                extra=sanitized_extra,
            )
        )


__all__ = ["InMemoryLogBuffer", "InMemoryLogHandler", "LogEntry"]
