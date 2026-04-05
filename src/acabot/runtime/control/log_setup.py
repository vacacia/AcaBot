"""runtime.control.log_setup 提供 structlog 初始化和 run context 绑定."""

from __future__ import annotations

import json
import logging
from typing import Any

import structlog


def _build_stdlib_log_record_attrs() -> frozenset[str]:
    record = logging.LogRecord("", logging.INFO, "", 0, "", (), None)
    attrs = set(record.__dict__.keys())
    attrs.update({"message", "asctime", "log_kind"})
    return frozenset(attrs)


STDLIB_LOG_RECORD_ATTRS: frozenset[str] = _build_stdlib_log_record_attrs()
_PATCHED_LOGGER_CLASSES: set[type[logging.Logger]] = set()


def _patch_logger_make_record(logger_class: type[logging.Logger]) -> None:
    if logger_class in _PATCHED_LOGGER_CLASSES:
        return

    original_make_record = logger_class.makeRecord

    def make_record_with_context(
        self,
        name,
        level,
        fn,
        lno,
        msg,
        args,
        exc_info,
        func=None,
        extra=None,
        sinfo=None,
    ):
        merged_extra = dict(structlog.contextvars.get_contextvars())
        if extra:
            merged_extra.update(extra)
        return original_make_record(
            self,
            name,
            level,
            fn,
            lno,
            msg,
            args,
            exc_info,
            func=func,
            extra=merged_extra or None,
            sinfo=sinfo,
        )

    logger_class.makeRecord = make_record_with_context  # type: ignore[assignment]
    _PATCHED_LOGGER_CLASSES.add(logger_class)


def configure_structlog() -> None:
    """初始化 structlog, 并把 contextvars 注入标准日志记录."""

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.render_to_log_kwargs,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _patch_logger_make_record(logging.Logger)
    _patch_logger_make_record(logging.getLoggerClass())


def bind_run_context(
    *,
    run_id: str,
    thread_id: str,
    agent_id: str,
) -> None:
    """在当前 async context 中绑定 run 级结构化字段."""

    structlog.contextvars.bind_contextvars(
        run_id=run_id,
        thread_id=thread_id,
        agent_id=agent_id,
    )


def clear_run_context() -> None:
    """清空当前 async context 中的 run 级结构化字段."""

    structlog.contextvars.clear_contextvars()


_REDACTED_VALUE = "[REDACTED]"
_REDACT_KEYS = {
    "token",
    "api_key",
    "authorization",
    "cookie",
    "password",
    "secret",
}
_SAFE_VISIBLE_KEYS = {
    "token_usage",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
}
_DEFAULT_STRING_LIMIT = 16 * 1024
_DEFAULT_TOTAL_BUDGET = 32 * 1024
_DEFAULT_MESSAGE_BUDGET = 15 * 1024
_DEFAULT_EXTRA_BUDGET = 15 * 1024


def _utf8_len(value: str) -> int:
    return len(str(value or "").encode("utf-8"))


def _truncate_text(value: str, limit: int) -> str:
    text = str(value or "")
    suffix = "…[truncated]"
    suffix_bytes = suffix.encode("utf-8")
    if limit <= 0:
        return ""
    if _utf8_len(text) <= limit:
        return text
    if limit <= len(suffix_bytes):
        return suffix_bytes[:limit].decode("utf-8", errors="ignore") or "…"
    keep_budget = limit - len(suffix_bytes)
    low = 0
    high = len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if _utf8_len(text[:mid]) <= keep_budget:
            low = mid
        else:
            high = mid - 1
    return f"{text[:low]}{suffix}"


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key or "").strip().lower()
    if lowered in _SAFE_VISIBLE_KEYS:
        return False
    return any(token in lowered for token in _REDACT_KEYS)


def sanitize_inspection_value(
    value: Any,
    *,
    string_limit: int = _DEFAULT_STRING_LIMIT,
    total_budget: int = _DEFAULT_TOTAL_BUDGET,
) -> Any:
    """把任意对象转换成 JSON-safe 的安全快照."""

    def _normalize(item: Any) -> Any:
        if item is None or isinstance(item, (bool, int, float)):
            return item
        if isinstance(item, str):
            return _truncate_text(item, string_limit)
        if isinstance(item, dict):
            return {
                str(key): (_REDACTED_VALUE if _is_sensitive_key(str(key)) else _normalize(val))
                for key, val in item.items()
            }
        if isinstance(item, (list, tuple, set)):
            iterable = item if not isinstance(item, set) else sorted(item, key=lambda part: str(part))
            return [_normalize(part) for part in iterable]
        if isinstance(item, bytes):
            return _truncate_text(item.decode("utf-8", errors="replace"), string_limit)
        return _truncate_text(str(item), string_limit)

    normalized = _normalize(value)
    try:
        serialized = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        serialized = json.dumps(_truncate_text(str(normalized), string_limit), ensure_ascii=False)
        normalized = _truncate_text(str(normalized), string_limit)
    if _utf8_len(serialized) <= total_budget:
        return normalized
    return {
        "_truncated": True,
        "preview": _truncate_text(serialized, total_budget),
    }


def sanitize_log_message(
    message: str,
    *,
    total_budget: int = _DEFAULT_MESSAGE_BUDGET,
) -> str:
    return _truncate_text(str(message or ""), min(_DEFAULT_STRING_LIMIT, total_budget))


def sanitize_log_extra(
    extra: dict[str, Any],
    *,
    total_budget: int = _DEFAULT_EXTRA_BUDGET,
) -> dict[str, Any]:
    sanitized = sanitize_inspection_value(extra, total_budget=total_budget)
    if isinstance(sanitized, dict):
        return sanitized
    return {"_truncated": True, "preview": sanitized}


def sanitize_log_record(
    *,
    message: str,
    extra: dict[str, Any],
    total_budget: int = _DEFAULT_TOTAL_BUDGET,
) -> tuple[str, dict[str, Any]]:
    """Sanitize a log record under the combined `message + extra <= total_budget` contract."""

    message_budget = min(_DEFAULT_MESSAGE_BUDGET, max(0, total_budget))
    extra_budget = min(_DEFAULT_EXTRA_BUDGET, max(0, total_budget - message_budget))
    sanitized_message = sanitize_log_message(message, total_budget=message_budget)
    sanitized_extra = sanitize_log_extra(extra, total_budget=extra_budget)
    return sanitized_message, sanitized_extra


def extract_extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    """从 LogRecord 中提取结构化字段."""

    extra: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key.startswith("_"):
            continue
        if key in STDLIB_LOG_RECORD_ATTRS:
            continue
        extra[key] = value
    return extra


__all__ = [
    "STDLIB_LOG_RECORD_ATTRS",
    "bind_run_context",
    "clear_run_context",
    "configure_structlog",
    "extract_extra_fields",
    "sanitize_inspection_value",
    "sanitize_log_extra",
    "sanitize_log_message",
    "sanitize_log_record",
]
