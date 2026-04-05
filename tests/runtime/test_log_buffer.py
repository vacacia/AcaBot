import json
import logging

from acabot.runtime.control.log_buffer import InMemoryLogBuffer, InMemoryLogHandler, LogEntry


def test_in_memory_log_buffer_supports_cursor_based_deltas() -> None:
    buffer = InMemoryLogBuffer(max_entries=5)
    buffer.append(LogEntry(timestamp=1.0, level="INFO", logger="a", message="one"))
    buffer.append(LogEntry(timestamp=2.0, level="INFO", logger="a", message="two"))
    buffer.append(LogEntry(timestamp=3.0, level="ERROR", logger="b", message="three"))

    snapshot = buffer.list_entries(limit=10)

    assert snapshot["next_seq"] == 3
    assert snapshot["reset_required"] is False
    assert [item["seq"] for item in snapshot["items"]] == [1, 2, 3]
    assert [item["kind"] for item in snapshot["items"]] == ["runtime", "runtime", "runtime"]

    delta = buffer.list_entries(after_seq=1, limit=10)

    assert delta["next_seq"] == 3
    assert delta["reset_required"] is False
    assert [item["seq"] for item in delta["items"]] == [2, 3]


def test_in_memory_log_buffer_marks_reset_when_cursor_falls_out_of_window() -> None:
    buffer = InMemoryLogBuffer(max_entries=2)
    buffer.append(LogEntry(timestamp=1.0, level="INFO", logger="a", message="one"))
    buffer.append(LogEntry(timestamp=2.0, level="INFO", logger="a", message="two"))
    buffer.append(LogEntry(timestamp=3.0, level="INFO", logger="a", message="three"))
    buffer.append(LogEntry(timestamp=4.0, level="INFO", logger="a", message="four"))

    delta = buffer.list_entries(after_seq=1, limit=10)

    assert delta["reset_required"] is True
    assert [item["seq"] for item in delta["items"]] == [3, 4]


def test_in_memory_log_handler_preserves_log_kind() -> None:
    buffer = InMemoryLogBuffer(max_entries=5)
    handler = InMemoryLogHandler(buffer)
    logger = logging.getLogger("acabot.test.log_kind")
    logger.setLevel(logging.INFO)
    logger.handlers = [handler]
    logger.propagate = False

    logger.info("hello", extra={"log_kind": "napcat_message"})

    snapshot = buffer.list_entries(limit=10)

    assert snapshot["items"][0]["kind"] == "napcat_message"


def test_in_memory_log_handler_sanitizes_sensitive_extra_fields() -> None:
    buffer = InMemoryLogBuffer(max_entries=5)
    handler = InMemoryLogHandler(buffer)
    logger = logging.getLogger("acabot.test.sanitized_extra")
    logger.setLevel(logging.INFO)
    logger.handlers = [handler]
    logger.propagate = False

    logger.info(
        "hello",
        extra={
            "token": "super-secret",
            "nested": {"api_key": "another-secret", "visible": "ok"},
        },
    )

    snapshot = buffer.list_entries(limit=10)
    item = snapshot["items"][0]

    assert item["extra"]["token"] == "[REDACTED]"
    assert item["extra"]["nested"]["api_key"] == "[REDACTED]"
    assert item["extra"]["nested"]["visible"] == "ok"


def test_in_memory_log_handler_truncates_oversized_message() -> None:
    buffer = InMemoryLogBuffer(max_entries=5)
    handler = InMemoryLogHandler(buffer)
    logger = logging.getLogger("acabot.test.long_message")
    logger.setLevel(logging.INFO)
    logger.handlers = [handler]
    logger.propagate = False

    logger.info("x" * 20000)

    snapshot = buffer.list_entries(limit=10)
    message = snapshot["items"][0]["message"]

    assert isinstance(message, str)
    assert len(message) < 20000
    assert message.endswith("…[truncated]")


def test_in_memory_log_handler_keeps_token_usage_visible() -> None:
    buffer = InMemoryLogBuffer(max_entries=5)
    handler = InMemoryLogHandler(buffer)
    logger = logging.getLogger("acabot.test.token_usage")
    logger.setLevel(logging.INFO)
    logger.handlers = [handler]
    logger.propagate = False

    logger.info("usage", extra={"token_usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}})

    snapshot = buffer.list_entries(limit=10)
    item = snapshot["items"][0]

    assert item["extra"]["token_usage"]["prompt_tokens"] == 12
    assert item["extra"]["token_usage"]["completion_tokens"] == 8
    assert item["extra"]["token_usage"]["total_tokens"] == 20


def test_in_memory_log_handler_enforces_combined_message_and_extra_budget() -> None:
    buffer = InMemoryLogBuffer(max_entries=5)
    handler = InMemoryLogHandler(buffer)
    logger = logging.getLogger("acabot.test.combined_budget")
    logger.setLevel(logging.INFO)
    logger.handlers = [handler]
    logger.propagate = False

    logger.info("猫" * 12000, extra={"payload": "🚀" * 12000})

    snapshot = buffer.list_entries(limit=10)
    item = snapshot["items"][0]
    combined_size = len(item["message"].encode("utf-8")) + len(
        json.dumps(item["extra"], ensure_ascii=False).encode("utf-8")
    )

    assert combined_size <= 32 * 1024
    assert item["message"].endswith("…[truncated]")
    assert isinstance(item["extra"], dict)
