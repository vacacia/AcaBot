"""runtime.control.log_buffer 提供给 WebUI 使用的轻量内存日志缓冲."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import logging
import threading
import time


@dataclass(slots=True)
class LogEntry:
    """一条可序列化的日志记录."""

    timestamp: float
    level: str
    logger: str
    message: str


class InMemoryLogBuffer:
    """线程安全的内存日志 ring buffer."""

    def __init__(self, max_entries: int = 2000) -> None:
        self.max_entries = max_entries
        self._items: deque[LogEntry] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def append(self, entry: LogEntry) -> None:
        with self._lock:
            self._items.append(entry)

    def list_entries(
        self,
        *,
        level: str = "",
        keyword: str = "",
        limit: int = 500,
    ) -> list[dict[str, object]]:
        normalized_level = str(level or "").strip().upper()
        normalized_keyword = str(keyword or "").strip().lower()
        with self._lock:
            items = list(self._items)
        if normalized_level:
            items = [item for item in items if item.level.upper() == normalized_level]
        if normalized_keyword:
            items = [
                item
                for item in items
                if normalized_keyword in item.message.lower() or normalized_keyword in item.logger.lower()
            ]
        items = items[-max(1, int(limit)) :]
        return [asdict(item) for item in items]


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
        self.buffer.append(
            LogEntry(
                timestamp=time.time(),
                level=str(record.levelname or "INFO"),
                logger=str(record.name or ""),
                message=message,
            )
        )


__all__ = ["InMemoryLogBuffer", "InMemoryLogHandler", "LogEntry"]
