"""runtime.contracts.records 定义持久化记录和线程状态对象.

组件关系:

    ChannelEventStore / MessageStore
        |
        v
    SequencedChannelEventRecord / SequencedMessageRecord
        |
        v
    ConversationFactReader

这里把事实内容和增量边界分开表达:
- `ChannelEventRecord` / `MessageRecord` 继续表示原始事实
- `Sequenced*Record` 负责把单调 sequence 包在外层
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .common import RunStatus


@dataclass(slots=True)
class ChannelEventRecord:
    """ChannelEventRecord, 对应持久化层的 channel_events 表.

    Attributes:
        event_uid (str): 事件主键.
        thread_id (str): 所属 thread.
        actor_id (str): 发送者身份键.
        channel_scope (str): 当前 channel scope.
        platform (str): 平台名.
        event_type (str): 事件类型.
        message_type (str): 消息场景类型.
        content_text (str): 便于检索的文本内容.
        payload_json (dict[str, Any]): 标准化 payload.
        timestamp (int): 事件时间.
        run_id (str | None): 关联 run.
        raw_message_id (str): 平台侧原始消息 id.
        operator_id (str | None): 操作者 id.
        target_message_id (str | None): 被操作消息 id.
        metadata (dict[str, Any]): 附加信息.
        raw_event (dict[str, Any]): 原始事件内容.
    """

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
    """MessageRecord, 对应持久化层的 messages 表.

    Attributes:
        message_uid (str): 消息主键.
        thread_id (str): 所属 thread.
        actor_id (str): 发送者身份键.
        platform (str): 平台名.
        role (str): 消息角色.
        content_text (str): 纯文本内容.
        content_json (dict[str, Any]): 结构化内容.
        timestamp (int): 送达时间.
        run_id (str | None): 关联 run.
        platform_message_id (str): 平台消息 id.
        metadata (dict[str, Any]): 附加信息.
    """

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
class SequencedChannelEventRecord:
    """SequencedChannelEventRecord 把事件事实和增量边界绑在一起.

    Attributes:
        sequence_id (int): 单调递增的边界编号.
        record (ChannelEventRecord): 原始事件事实.
    """

    sequence_id: int
    record: ChannelEventRecord


@dataclass(slots=True)
class SequencedMessageRecord:
    """SequencedMessageRecord 把消息事实和增量边界绑在一起.

    Attributes:
        sequence_id (int): 单调递增的边界编号.
        record (MessageRecord): 原始消息事实.
    """

    sequence_id: int
    record: MessageRecord


@dataclass(slots=True)
class ThreadRecord:
    """thread 的持久化记录, 运行时上下文单元.

    Attributes:
        thread_id (str): thread 主键.
        channel_scope (str): 当前 scope.
        thread_kind (str): thread 类型.
        working_messages (list[dict[str, Any]]): 当前工作消息窗口.
        working_summary (str): 当前工作摘要.
        last_event_at (int): 最近事件时间.
        metadata (dict[str, Any]): 附加信息.
    """

    thread_id: str
    channel_scope: str
    thread_kind: str = "channel"
    working_messages: list[dict[str, Any]] = field(default_factory=list)
    working_summary: str = ""
    last_event_at: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ThreadState:
    """thread 的运行时状态容器.

    Attributes:
        thread_id (str): thread 主键.
        channel_scope (str): 当前 scope.
        thread_kind (str): thread 类型.
        working_messages (list[dict[str, Any]]): 当前工作消息窗口.
        working_summary (str): 当前工作摘要.
        last_event_at (int): 最近事件时间.
        metadata (dict[str, Any]): 附加信息.
        lock (asyncio.Lock): thread 级别锁.
    """

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
    """一次 agent 执行的生命周期记录.

    Attributes:
        run_id (str): run 主键.
        thread_id (str): 所属 thread.
        actor_id (str): 触发者身份键.
        agent_id (str): 当前 agent.
        trigger_event_id (str): 触发事件.
        status (RunStatus): 当前状态.
        started_at (int): 开始时间.
        finished_at (int | None): 结束时间.
        error (str | None): 错误描述.
        approval_context (dict[str, Any]): 审批上下文.
        metadata (dict[str, Any]): 附加信息.
    """

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
    """重启恢复后识别出的 pending approval 记录.

    Attributes:
        run_id (str): run 主键.
        thread_id (str): 所属 thread.
        actor_id (str): 触发者身份键.
        agent_id (str): 当前 agent.
        reason (str): 等待审批原因.
        approval_context (dict[str, Any]): 审批上下文.
    """

    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    reason: str
    approval_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RecoveryReport:
    """一次 startup recovery 的汇总结果.

    Attributes:
        interrupted_run_ids (list[str]): 被收尾的 run 列表.
        pending_approvals (list[PendingApprovalRecord]): 保留下来的审批记录.
    """

    interrupted_run_ids: list[str] = field(default_factory=list)
    pending_approvals: list[PendingApprovalRecord] = field(default_factory=list)


__all__ = [
    "ChannelEventRecord",
    "MessageRecord",
    "PendingApprovalRecord",
    "RecoveryReport",
    "RunRecord",
    "SequencedChannelEventRecord",
    "SequencedMessageRecord",
    "ThreadRecord",
    "ThreadState",
]
