import logging

import structlog

from acabot.runtime.control.log_buffer import InMemoryLogBuffer, InMemoryLogHandler, LogEntry
from acabot.runtime.control.log_setup import (
    STDLIB_LOG_RECORD_ATTRS,
    bind_run_context,
    clear_run_context,
    configure_structlog,
    extract_extra_fields,
)


def _logger_with_buffer(name: str) -> tuple[logging.Logger, InMemoryLogBuffer]:
    buffer = InMemoryLogBuffer(max_entries=10)
    handler = InMemoryLogHandler(buffer)
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger, buffer


def test_log_entry_serializes_extra_fields() -> None:
    buffer = InMemoryLogBuffer(max_entries=5)
    buffer.append(
        LogEntry(
            timestamp=1.0,
            level="INFO",
            logger="acabot.test",
            message="hello",
            extra={"tool_name": "bash"},
        )
    )

    snapshot = buffer.list_entries(limit=10)

    assert snapshot["items"][0]["extra"] == {"tool_name": "bash"}


def test_extract_extra_fields_excludes_stdlib_attributes() -> None:
    record = logging.LogRecord("demo", logging.INFO, __file__, 1, "hello", (), None)
    record.tool_name = "bash"
    record.duration_ms = 42

    extra = extract_extra_fields(record)

    assert "name" in STDLIB_LOG_RECORD_ATTRS
    assert "tool_name" in extra
    assert "duration_ms" in extra
    assert "name" not in extra


def test_in_memory_log_handler_extracts_structured_fields() -> None:
    logger, buffer = _logger_with_buffer("acabot.test.log_buffer.structured")

    logger.info("Tool executed", extra={"tool_name": "bash", "duration_ms": 42})

    snapshot = buffer.list_entries(limit=10)

    assert snapshot["items"][0]["extra"]["tool_name"] == "bash"
    assert snapshot["items"][0]["extra"]["duration_ms"] == 42


def test_bind_run_context_injects_stdlib_logger_records() -> None:
    configure_structlog()
    logger, buffer = _logger_with_buffer("acabot.test.log_buffer.context")

    clear_run_context()
    bind_run_context(run_id="run-1", thread_id="thread-1", agent_id="aca")
    logger.info("pipeline started")
    clear_run_context()

    snapshot = buffer.list_entries(limit=10)
    assert snapshot["items"][0]["extra"]["run_id"] == "run-1"
    assert snapshot["items"][0]["extra"]["thread_id"] == "thread-1"
    assert snapshot["items"][0]["extra"]["agent_id"] == "aca"


def test_structlog_logger_preserves_context_and_event_fields() -> None:
    configure_structlog()
    logger, buffer = _logger_with_buffer("acabot.test.structlog")

    clear_run_context()
    bind_run_context(run_id="run-2", thread_id="thread-2", agent_id="agent-2")
    structlog.get_logger("acabot.test.structlog").info(
        "Tool executed",
        tool_name="bash",
        duration_ms=7,
    )
    clear_run_context()

    snapshot = buffer.list_entries(limit=10)
    assert snapshot["items"][0]["extra"]["run_id"] == "run-2"
    assert snapshot["items"][0]["extra"]["tool_name"] == "bash"
    assert snapshot["items"][0]["extra"]["duration_ms"] == 7


def test_clear_run_context_prevents_context_leakage() -> None:
    configure_structlog()
    logger, buffer = _logger_with_buffer("acabot.test.context.clear")

    clear_run_context()
    bind_run_context(run_id="run-3", thread_id="thread-3", agent_id="agent-3")
    logger.info("first")
    clear_run_context()
    logger.info("second")

    snapshot = buffer.list_entries(limit=10)
    assert snapshot["items"][0]["extra"]["run_id"] == "run-3"
    assert "run_id" not in snapshot["items"][1]["extra"]


def test_in_memory_log_buffer_keyword_filter_searches_extra_fields() -> None:
    buffer = InMemoryLogBuffer(max_entries=5)
    buffer.append(
        LogEntry(
            timestamp=1.0,
            level="INFO",
            logger="acabot.test",
            message="tool finished",
            extra={"tool_name": "bash"},
        )
    )

    snapshot = buffer.list_entries(keyword="bash", limit=10)

    assert len(snapshot["items"]) == 1
