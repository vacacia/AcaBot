"""runtime.control.log_setup 提供 structlog 初始化和 run context 绑定."""

from __future__ import annotations

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
]
