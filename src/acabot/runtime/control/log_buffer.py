"""runtime.control.log_buffer 提供给 WebUI 使用的轻量内存日志缓冲."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
import logging
import threading
import time
from typing import Any
from typing_extensions import override

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
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """极速序列化, 避开 asdict 的反射开销."""
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger,
            "message": self.message,
            "kind": self.kind,
            "seq": self.seq,
            "extra": self.extra,
        }


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
            # Take a snapshot to minimize lock duration
            items_snapshot = list(self._items)
            next_seq = self._next_seq - 1
        
        if not items_snapshot:
            return {"items": [], "next_seq": next_seq, "reset_required": False}

        oldest_seq = int(items_snapshot[0].seq or 0)
        reset_required = bool(normalized_after_seq and normalized_after_seq < oldest_seq - 1)
        
        results: list[LogEntry] = []
        # Search backwards from newest to oldest for better performance when limit is small
        for item in reversed(items_snapshot):
            # 1. Sequence check
            if normalized_after_seq and int(item.seq or 0) <= normalized_after_seq:
                # Since we are iterating backwards, we can stop early if we hit after_seq
                break
                
            # 2. Level filter
            if normalized_level and item.level.upper() != normalized_level:
                continue
                
            # 3. Keyword filter (optimized)
            if normalized_keyword:
                msg = item.message.lower()
                logger = item.logger.lower()
                found = (normalized_keyword in msg) or (normalized_keyword in logger)
                
                if not found and item.extra:
                    # Only search in keys and simple values of extra, avoiding heavy str conversion of huge objects
                    for k, v in item.extra.items():
                        if normalized_keyword in str(k).lower():
                            found = True
                            break
                        if isinstance(v, (str, int, float, bool)) and normalized_keyword in str(v).lower():
                            found = True
                            break
                
                if not found:
                    continue
            
            results.append(item)
            if len(results) >= limit:
                break
        
        # Reverse back to maintain chronological order for the client
        results.reverse()
        
        return {
            "items": [item.to_dict() for item in results],
            "next_seq": next_seq,
            "reset_required": reset_required,
        }


class InMemoryLogHandler(logging.Handler):
    """把 logging 记录镜像进 InMemoryLogBuffer."""

    def __init__(self, buffer: InMemoryLogBuffer) -> None:
        super().__init__()
        self.buffer = buffer

    @override
    @override
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
