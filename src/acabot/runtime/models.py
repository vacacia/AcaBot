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
    "interrupted",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
]
RunMode = Literal["respond", "record_only", "silent_drop"]
CommitWhen = Literal["success", "failure", "waiting_approval", "always"]
ApprovalDecision = Literal["approved", "rejected"]


@dataclass(slots=True)
class ChannelEventRecord:
    """ChannelEventRecord, 对应持久化层的 channel_events 表.

    Attributes:
        event_uid (str): 平台事件唯一 ID.
        thread_id (str): 当前事件归属的 thread ID.
        actor_id (str): 当前事件主 actor 标识.
        channel_scope (str): 当前事件所在 channel scope.
        platform (str): 平台名.
        event_type (str): canonical 事件类型.
        message_type (str): 会话类型, 例如 `private` 或 `group`.
        content_text (str): 便于检索的简短文本投影.
        payload_json (dict[str, Any]): 结构化 canonical event payload.
        timestamp (int): 事件时间戳.
        run_id (str | None): 关联 run_id. `silent_drop` 之外通常会有值.
        raw_message_id (str): 平台 message_id. notice event 可能为空.
        operator_id (str | None): 操作者 ID.
        target_message_id (str | None): 目标消息 ID.
        metadata (dict[str, Any]): 控制面附加元数据.
        raw_event (dict[str, Any]): 平台原始 payload.
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
    working_messages: list[dict[str, Any]] = field(default_factory=list)
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
    - 匹配 `event_type + channel_scope`, 表示某类平台事件在某个群里走特殊 agent.
    - 匹配 `thread_id`, 表示 runtime 临时 thread override.
    """

    rule_id: str
    agent_id: str
    priority: int = 100
    thread_id: str | None = None
    event_type: str | None = None
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
        if self.event_type is not None and self.event_type != event.event_type:
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
        if self.event_type is not None:
            keys.append("event_type")
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
class InboundRule:
    """一条 inbound 事件控制规则.

    Attributes:
        rule_id (str): 当前规则唯一 ID.
        run_mode (RunMode): 命中后的运行模式.
        priority (int): 优先级. 越大越先命中.
        platform (str | None): 平台过滤条件.
        event_type (str | None): 事件类型过滤条件.
        actor_id (str | None): actor 过滤条件.
        channel_scope (str | None): channel 过滤条件.
        sender_roles (list[str]): 群角色过滤条件.
        metadata (dict[str, Any]): 附加元数据.
    """

    rule_id: str
    run_mode: RunMode
    priority: int = 100
    platform: str | None = None
    event_type: str | None = None
    actor_id: str | None = None
    channel_scope: str | None = None
    sender_roles: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches(
        self,
        *,
        event: StandardEvent,
        actor_id: str,
        channel_scope: str,
    ) -> bool:
        """判断这条 inbound rule 是否命中当前事件.

        Args:
            event: 当前标准化事件.
            actor_id: 当前事件的 actor_id.
            channel_scope: 当前事件的 channel_scope.

        Returns:
            当前 rule 是否命中.
        """

        if self.platform is not None and self.platform != event.platform:
            return False
        if self.event_type is not None and self.event_type != event.event_type:
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
        """返回当前 inbound rule 使用的 match key 列表.

        Returns:
            当前规则的 match key 列表.
        """

        keys: list[str] = []
        if self.platform is not None:
            keys.append("platform")
        if self.event_type is not None:
            keys.append("event_type")
        if self.actor_id is not None:
            keys.append("actor_id")
        if self.channel_scope is not None:
            keys.append("channel_scope")
        if self.sender_roles:
            keys.append("sender_roles")
        return keys

    def specificity(self) -> int:
        """返回当前 inbound rule 的特异度.

        Returns:
            当前规则声明的 match key 数量.
        """

        return len(self.match_keys())


@dataclass(slots=True)
class EventPolicy:
    """一条 inbound event policy.

    Attributes:
        policy_id (str): 当前策略唯一 ID.
        priority (int): 优先级. 越大越先命中.
        platform (str | None): 平台过滤条件.
        event_type (str | None): 事件类型过滤条件.
        actor_id (str | None): actor 过滤条件.
        channel_scope (str | None): channel 过滤条件.
        sender_roles (list[str]): 群角色过滤条件.
        persist_event (bool): 是否写入 ChannelEventStore.
        extract_to_memory (bool): 后续是否参与 memory extraction.
        memory_scopes (list[str]): 建议写入的 memory scope 列表.
        tags (list[str]): 上层可消费的 event tags.
        metadata (dict[str, Any]): 附加元数据.
    """

    policy_id: str
    priority: int = 100
    platform: str | None = None
    event_type: str | None = None
    actor_id: str | None = None
    channel_scope: str | None = None
    sender_roles: list[str] = field(default_factory=list)
    persist_event: bool = True
    extract_to_memory: bool = False
    memory_scopes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches(
        self,
        *,
        event: StandardEvent,
        actor_id: str,
        channel_scope: str,
    ) -> bool:
        """判断这条 event policy 是否命中当前事件.

        命中 = 这条策略的配置条件全部满足当前事件的属性, 策略对该事件生效

        Args:
            event: 当前标准化事件.
            actor_id: 当前事件的 actor_id.
            channel_scope: 当前事件的 channel_scope.

        Returns:
            当前策略是否命中.
        """

        if self.platform is not None and self.platform != event.platform:
            return False
        if self.event_type is not None and self.event_type != event.event_type:
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
        """返回当前 event policy 使用的 match key 列表.

        Returns:
            当前策略声明的 match key 列表.
        """

        keys: list[str] = []
        if self.platform is not None:
            keys.append("platform")
        if self.event_type is not None:
            keys.append("event_type")
        if self.actor_id is not None:
            keys.append("actor_id")
        if self.channel_scope is not None:
            keys.append("channel_scope")
        if self.sender_roles:
            keys.append("sender_roles")
        return keys

    def specificity(self) -> int:
        """返回当前 event policy 的特异度.

        Returns:
            当前策略声明的 match key 数量.
        """

        return len(self.match_keys())


@dataclass(slots=True)
class EventPolicyDecision:
    """一次 inbound event policy 解析结果.

    Attributes:
        policy_id (str): 命中的策略 ID. 默认策略时为空.
        priority (int): 命中策略的优先级. 默认策略时为 -1.
        match_keys (list[str]): 命中策略使用的 match key 列表.
        persist_event (bool): 是否持久化到 ChannelEventStore.
        extract_to_memory (bool): 是否参与后续 memory extraction.
        memory_scopes (list[str]): 后续建议写入的 memory scope 列表.
        tags (list[str]): 当前事件附带的 tags.
        metadata (dict[str, Any]): 附加元数据.
    """

    policy_id: str = ""
    priority: int = -1
    match_keys: list[str] = field(default_factory=list)
    persist_event: bool = True
    extract_to_memory: bool = False
    memory_scopes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        """把策略决策转成 RouteDecision.metadata 片段.

        Returns:
            可直接并入 RouteDecision.metadata 的轻量元数据.
        """

        return {
            "event_policy_id": self.policy_id,
            "event_policy_priority": self.priority,
            "event_policy_match_keys": list(self.match_keys),
            "event_persist": self.persist_event,
            "event_extract_to_memory": self.extract_to_memory,
            "event_memory_scopes": list(self.memory_scopes),
            "event_tags": list(self.tags),
            **dict(self.metadata),
        }


@dataclass(slots=True)
class RouteDecision:
    """router 的解析结果.

    这条消息属于哪个 thread? 由哪个 agent 处理? 这次 run 是 respond, record_only 还是 silent_drop?
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


class ApprovalRequired(Exception):
    """表示当前 run 被工具打断并进入待审批状态.

    Attributes:
        pending_approval (PendingApproval): 当前待审批上下文.
    """

    def __init__(self, *, pending_approval: PendingApproval) -> None:
        """初始化 ApprovalRequired.

        Args:
            pending_approval: 当前待审批上下文.
        """

        super().__init__(pending_approval.reason)
        self.pending_approval = pending_approval


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

    Attributes:
        run_id (str): Run 唯一标识符.
        thread_id (str): 关联的 thread ID, 标识对话上下文.
        actor_id (str): 触发本次 run 的用户/实体标识.
        agent_id (str): 处理本次 run 的 agent ID.
        trigger_event_id (str): 触发本次 run 的事件 ID.
        status (RunStatus): 当前运行状态 (queued/running/waiting_approval/completed/failed/cancelled).
        started_at (int): Run 创建时间戳 (Unix timestamp).
        finished_at (int | None): Run 结束时间戳, None 表示尚未结束.
        error (str | None): 错误信息, None 表示无错误.
        approval_context (dict[str, Any]): 审批上下文数据, 包含审批原因、tool 信息等.
        metadata (dict[str, Any]): 扩展元数据, 用于存储额外业务信息.
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


# region recovery
@dataclass(slots=True)
class PendingApprovalRecord:
    """重启恢复后识别出的 pending approval 记录.

    这是 RuntimeApp 暴露给上层查看的稳定对象, 用于 Web 界面展示待审批列表

    Attributes:
        run_id (str): 关联的 run ID, 标识本次待审批的执行记录
        thread_id (str): 关联的 thread ID, 用于定位对话上下文
        actor_id (str): 触发本次审批请求的用户/实体标识
        agent_id (str): 请求执行操作的 agent ID
        reason (str): 需要审批的原因说明
        approval_context (dict[str, Any]): 审批上下文数据, 包含 tool 信息、参数等执行细节
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

    系统重启后, RuntimeApp 通过此报告告知上层有哪些中断的 run 需要处理.

    Attributes:
        interrupted_run_ids (list[str]): 状态异常的非自然结束 run ID 列表.
        pending_approvals (list[PendingApprovalRecord]): 重启前等待审批、重启后需恢复的审批记录列表.
    """

    interrupted_run_ids: list[str] = field(default_factory=list)
    pending_approvals: list[PendingApprovalRecord] = field(default_factory=list)


@dataclass(slots=True)
class ApprovalDecisionResult:
    """一次 approval decision 的返回结果.

    管理员批准或拒绝 run 后, RuntimeApp 返回此结果说明操作是否成功及最终状态.

    Attributes:
        run_id (str): 被操作的 run ID.
        decision (ApprovalDecision): 决策类型 (approved/rejected).
        ok (bool): 操作是否成功完成.
        run_status (RunStatus | None): 操作后的 run 最终状态 (completed/failed/cancelled 等), 失败时可能为 None.
        message (str): 附加说明信息, 失败原因或成功提示.
        pending_approval (PendingApprovalRecord | None): 如果 run 再次进入 waiting_approval 状态, 返回新的待审批记录.
    """

    run_id: str
    decision: ApprovalDecision
    ok: bool
    run_status: RunStatus | None = None
    message: str = ""
    pending_approval: PendingApprovalRecord | None = None


# endregion


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
