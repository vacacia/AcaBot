"""runtime.contracts.records 定义持久化记录和线程状态对象."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .common import MemoryEditMode, RunStatus


@dataclass(slots=True)
class MemoryItem:
    """MemoryItem, 对应持久化层的 memory_items 表."""

    memory_id: str
    scope: str
    scope_key: str
    memory_type: str
    content: str
    edit_mode: MemoryEditMode = "draft"
    author: str = "extractor"
    confidence: float = 0.0
    source_run_id: str | None = None
    source_event_id: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0
    updated_at: int = 0


@dataclass(slots=True)
class ChannelEventRecord:
    """ChannelEventRecord, 对应持久化层的 channel_events 表."""

    event_uid: str
    thread_id: str
    actor_id: str
    channel_scope: str
    platform: str
    event_type: str
    message_type: str
    content_text: str
    payload_json: dict[str, Any]
    timestamp: int
    run_id: str | None = None
    raw_message_id: str = ""
    operator_id: str | None = None
    target_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_event: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MessageRecord:
    """MessageRecord, 对应持久化层的 messages 表."""

    message_uid: str
    thread_id: str
    actor_id: str
    platform: str
    role: str
    content_text: str
    content_json: dict[str, Any]
    timestamp: int
    run_id: str | None = None
    platform_message_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ThreadRecord:
    """thread 的持久化记录, 运行时上下文单元."""

    thread_id: str
    channel_scope: str
    thread_kind: str = "channel"
    working_messages: list[dict[str, Any]] = field(default_factory=list)
    working_summary: str = ""
    last_event_at: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ThreadState:
    """thread 的运行时状态容器."""

    thread_id: str
    channel_scope: str
    thread_kind: str = "channel"
    working_messages: list[dict[str, Any]] = field(default_factory=list)
    working_summary: str = ""
    last_event_at: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)


@dataclass(slots=True)
class RunRecord:
    """一次 agent 执行的生命周期记录."""

    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    trigger_event_id: str
    status: RunStatus
    started_at: int
    finished_at: int | None = None
    error: str | None = None
    approval_context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PendingApprovalRecord:
    """重启恢复后识别出的 pending approval 记录."""

    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    reason: str
    approval_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RecoveryReport:
    """一次 startup recovery 的汇总结果."""

    interrupted_run_ids: list[str] = field(default_factory=list)
    pending_approvals: list[PendingApprovalRecord] = field(default_factory=list)


__all__ = [
    "ChannelEventRecord",
    "MemoryItem",
    "MessageRecord",
    "PendingApprovalRecord",
    "RecoveryReport",
    "RunRecord",
    "ThreadRecord",
    "ThreadState",
]
