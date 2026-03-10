"""runtime.models 定义 runtime 的核心数据对象.

这里的对象只表达系统状态和约定, 不负责具体业务逻辑.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

from acabot.types import Action, StandardEvent

RunStatus = Literal[
    "queued",
    "running",
    "waiting_approval",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
]
RunMode = Literal["respond", "record_only"]
CommitWhen = Literal["success", "failure", "waiting_approval", "always"]


@dataclass(slots=True)
class MessageRecord:
    """MessageRecord, 对应持久化层的 messages 表.

    存储外部世界实际发生过的内容, 不是 working memory 里的草稿.
    """

    message_uid: str
    thread_id: str  # 所属 thread
    actor_id: str  # 发言者标识
    platform: str
    role: str  # user/assistant/system
    content_text: str  # 便于查询的纯文本内容
    content_json: dict[str, Any]  # 完整的结构化内容
    timestamp: int
    run_id: str | None = None  # 关联的 run 标识, 用户消息可以为空
    platform_message_id: str = ""  # 平台侧返回的消息 ID
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ThreadRecord:
    """thread 的持久化记录, 运行时上下文单元.

    偏向数据库存储, 只保留容易恢复和查询的轻量状态.
    """

    thread_id: str# thread 标识
    channel_scope: str# 渠道范围
    thread_kind: str = "channel"
    working_summary: str = ""# 工作记忆摘要
    last_event_at: int = 0# 最后事件时间戳
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ThreadState:
    """thread 的运行时状态容器.

    持有 working memory, 摘要和并发锁. 这是 ThreadManager 真正操作的对象.
    """

    thread_id: str
    channel_scope: str
    thread_kind: str = "channel"
    working_messages: list[dict[str, Any]] = field(default_factory=list) # 工作记忆消息列表
    working_summary: str = ""
    last_event_at: int = 0 # 最后事件时间戳
    metadata: dict[str, Any] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)


@dataclass(slots=True)
class AgentProfile:
    """agent 的静态配置 snapshot.

    agent 是谁? 默认用什么模型? 可以看到哪些工具? 
    """

    agent_id: str # 唯一标识
    name: str 
    prompt_ref: str # prompt 文件引用
    default_model: str
    enabled_tools: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BindingRule:
    """一条用于 route 解析的 binding rule.

    rule 通过显式 match 条件决定当前消息应该落到哪个 agent.
    这比固定的 `thread > actor > channel > default` 更适合 QQ-first 场景.

    常见用法:
    - 只匹配 `channel_scope`, 表示某个群或私聊默认使用哪个 agent.
    - 匹配 `actor_id + channel_scope`, 表示某个用户在某个群里走特殊 agent.
    - 匹配 `channel_scope + sender_roles`, 表示群管理员在该群里走特殊 agent.
    - 匹配 `thread_id`, 表示 runtime 临时 thread override.
    """

    rule_id: str
    agent_id: str
    priority: int = 100
    thread_id: str | None = None
    actor_id: str | None = None
    channel_scope: str | None = None
    sender_roles: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches(
        self,
        *,
        event: StandardEvent,
        thread_id: str,
        actor_id: str,
        channel_scope: str,
    ) -> bool:
        """判断这条 rule 是否命中当前消息.

        Args:
            event: 当前标准化消息事件.
            thread_id: 当前消息所属 thread_id.
            actor_id: 当前消息发送方的 actor_id.
            channel_scope: 当前消息所在 channel_scope.

        Returns:
            当前 rule 是否命中.
        """

        if self.thread_id is not None and self.thread_id != thread_id:
            return False
        if self.actor_id is not None and self.actor_id != actor_id:
            return False
        if self.channel_scope is not None and self.channel_scope != channel_scope:
            return False
        if self.sender_roles:
            sender_role = event.sender_role or ""
            if sender_role not in self.sender_roles:
                return False
        return True

    def match_keys(self) -> list[str]:
        """返回这条 rule 当前声明了哪些 match 条件.

        Returns:
            当前 rule 使用的 match key 列表.
        """

        keys: list[str] = []
        if self.thread_id is not None:
            keys.append("thread_id")
        if self.actor_id is not None:
            keys.append("actor_id")
        if self.channel_scope is not None:
            keys.append("channel_scope")
        if self.sender_roles:
            keys.append("sender_roles")
        return keys

    def specificity(self) -> int:
        """返回这条 rule 的匹配特异度.

        Returns:
            match 条件数量. 值越大表示规则越具体.
        """

        return len(self.match_keys())


@dataclass(slots=True)
class RouteDecision:
    """router 的解析结果.

    这条消息属于哪个 thread? 由哪个 agent 处理? 这次 run 是 respond 还是 record_only?
    """

    thread_id: str
    actor_id: str # 消息发送者标识
    agent_id: str # 应使用的 agent
    channel_scope: str
    run_mode: RunMode = "respond"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlannedAction:
    """一次待出站动作的规划结果 - AgentRuntime 和 Outbox 之间的契约.
    Args:
        `action` 表示真正要发送的动作.
        `thread_content` 表示成功送达后, thread 里应该追加什么内容(可能不同于 action).
        `commit_when` 表示这个动作在哪种 run 终态下算正式提交.
    """

    action_id: str
    action: Action
    thread_content: str | None = None
    commit_when: CommitWhen = "success"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PendingApproval:
    """待审批上下文.

    当运行被高风险工具打断时, 需要把恢复这次审批所需的关键信息集中带出去.
    """

    approval_id: str
    reason: str
    tool_name: str
    tool_call_id: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    required_action_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentRuntimeResult:
    """一次 agent runtime 执行后的系统级结果.

    ThreadPipeline 和 AgentRuntime 之间的正式契约.
    包含文本, 动作, 状态, 错误和审批上下文.
    """

    status: Literal["completed", "waiting_approval", "failed"] = "completed"
    text: str = ""
    actions: list["PlannedAction"] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model_used: str = ""
    error: str | None = None
    pending_approval: PendingApproval | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: Any = None


@dataclass(slots=True)
class DeliveryResult:
    """单个 action 的投递结果."""

    action_id: str
    ok: bool
    platform_message_id: str = ""
    error: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class OutboxItem:
    """Outbox 实际发送的最小单位.

    将 run, thread, agent 和具体 action plan 绑在一起, 便于发送和写库.
    """

    thread_id: str
    run_id: str
    agent_id: str
    plan: PlannedAction
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DispatchReport:
    """一批出站动作的投递汇总结果."""

    results: list[DeliveryResult] = field(default_factory=list)
    delivered_items: list[OutboxItem] = field(default_factory=list)
    failed_action_ids: list[str] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        """返回这批出站是否存在任何失败动作."""

        return bool(self.failed_action_ids)


@dataclass(slots=True)
class RunRecord:
    """一次 agent 执行的生命周期记录.

    它是 run manager 管理的正式对象, 用来承载状态迁移, 错误信息和审批上下文.
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
class RunStep:
    """run 内部的可审计步骤记录.

    例如 route, retrieve, llm, tool, send 都可以拆成独立步骤.
    """

    step_id: str
    run_id: str
    step_type: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0


@dataclass(slots=True)
class RunContext:
    """ThreadPipeline 执行一次 run 时共享的上下文对象.

    它把 event, route 决策, thread 状态, profile 和执行中间产物装进同一个容器.
    """

    run: RunRecord
    event: StandardEvent
    decision: RouteDecision
    thread: ThreadState
    profile: AgentProfile
    messages: list[dict[str, Any]] = field(default_factory=list)
    system_prompt: str = ""
    response: Any | None = None
    actions: list[PlannedAction] = field(default_factory=list)
    delivery_report: DispatchReport | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
