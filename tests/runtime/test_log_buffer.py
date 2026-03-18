from acabot.runtime.control.log_buffer import InMemoryLogBuffer, LogEntry


def test_in_memory_log_buffer_supports_cursor_based_deltas() -> None:
    buffer = InMemoryLogBuffer(max_entries=5)
    buffer.append(LogEntry(timestamp=1.0, level="INFO", logger="a", message="one"))
    buffer.append(LogEntry(timestamp=2.0, level="INFO", logger="a", message="two"))
    buffer.append(LogEntry(timestamp=3.0, level="ERROR", logger="b", message="three"))

    snapshot = buffer.list_entries(limit=10)

    assert snapshot["next_seq"] == 3
    assert snapshot["reset_required"] is False
    assert [item["seq"] for item in snapshot["items"]] == [1, 2, 3]

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
