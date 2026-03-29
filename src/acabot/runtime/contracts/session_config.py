"""runtime.contracts.session_config 定义 Session Config 主线使用的运行时契约.

这个文件和下面几层直接相连:

- `runtime.control.session_loader` 负责把 YAML 读成这里定义的数据对象
- `runtime.control.session_runtime` 负责把 `StandardEvent` 变成 `EventFacts`, 再算出各决策结果
- `runtime.router` / `runtime.app` 后续会消费这些决策结果
- `runtime.computer` 后续会消费 `ComputerPolicyDecision` 和 world input bundle

这里不负责读取文件, 也不负责执行决策. 它只负责把“会话配置”和“运行时决策结果”收成稳定的数据对象.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# region facts 和 matcher
@dataclass(slots=True)
class EventFacts:
    """标准化后的事件事实.

    Attributes:
        platform (str): 平台名, 例如 `qq`.
        event_kind (str): 事件大类, 例如 `message`.
        scene (str): 当前场景, 例如 `private` `group` `notice`.
        actor_id (str): 当前发送者的 canonical actor_id.
        channel_scope (str): 当前消息所在会话的 canonical scope.
        thread_id (str): 当前消息落到的 thread 标识.
        targets_self (bool): 当前事件是否明确指向 bot 自身.
        mentions_self (bool): 当前消息是否显式提到了 bot.
        reply_targets_self (bool): 当前消息是否在回复 bot.
        mentioned_everyone (bool): 当前消息是否 @ 全体.
        sender_roles (list[str]): 当前发送者命中的角色列表.
        attachments_present (bool): 当前事件是否带附件.
        attachment_kinds (list[str]): 附件类型列表, 例如 `image` `file`.
        message_subtype (str): 消息子类型.
        notice_type (str): notice 主类型.
        notice_subtype (str): notice 子类型.
        metadata (dict[str, Any]): 其他暂时还没收正式字段的补充信息.
    """

    platform: str = ""
    event_kind: str = ""
    scene: str = ""
    actor_id: str = ""
    channel_scope: str = ""
    thread_id: str = ""
    targets_self: bool = False
    mentions_self: bool = False
    reply_targets_self: bool = False
    mentioned_everyone: bool = False
    sender_roles: list[str] = field(default_factory=list)
    attachments_present: bool = False
    attachment_kinds: list[str] = field(default_factory=list)
    message_subtype: str = ""
    notice_type: str = ""
    notice_subtype: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MatchSpec:
    """针对 `EventFacts` 的共享匹配条件.

    Attributes:
        platform (str | None): 限制平台.
        event_kind (str | None): 限制事件大类.
        scene (str | None): 限制场景.
        actor_id (str | None): 限制发送者 actor_id.
        channel_scope (str | None): 限制会话范围.
        thread_id (str | None): 限制 thread.
        targets_self (bool | None): 是否要求事件明确指向 bot.
        mentions_self (bool | None): 是否要求显式提到 bot.
        reply_targets_self (bool | None): 是否要求回复 bot.
        mentioned_everyone (bool | None): 是否要求 @ 全体.
        sender_roles (list[str]): 允许命中的发送者角色集合.
        attachments_present (bool | None): 是否要求存在附件.
        attachment_kinds (list[str]): 允许命中的附件类型集合.
        message_subtype (str | None): 限制消息子类型.
        notice_type (str | None): 限制 notice 主类型.
        notice_subtype (str | None): 限制 notice 子类型.
    """

    platform: str | None = None
    event_kind: str | None = None
    scene: str | None = None
    actor_id: str | None = None
    channel_scope: str | None = None
    thread_id: str | None = None
    targets_self: bool | None = None
    mentions_self: bool | None = None
    reply_targets_self: bool | None = None
    mentioned_everyone: bool | None = None
    sender_roles: list[str] = field(default_factory=list)
    attachments_present: bool | None = None
    attachment_kinds: list[str] = field(default_factory=list)
    message_subtype: str | None = None
    notice_type: str | None = None
    notice_subtype: str | None = None

    def matches(self, facts: EventFacts) -> bool:
        """判断这条匹配条件是否命中当前事实.

        Args:
            facts (EventFacts): 当前事件已经标准化后的事实对象.

        Returns:
            bool: 命中返回 `True`, 否则返回 `False`.
        """

        if self.platform is not None and self.platform != facts.platform:
            return False
        if self.event_kind is not None and self.event_kind != facts.event_kind:
            return False
        if self.scene is not None and self.scene != facts.scene:
            return False
        if self.actor_id is not None and self.actor_id != facts.actor_id:
            return False
        if self.channel_scope is not None and self.channel_scope != facts.channel_scope:
            return False
        if self.thread_id is not None and self.thread_id != facts.thread_id:
            return False
        if self.targets_self is not None and self.targets_self != facts.targets_self:
            return False
        if self.mentions_self is not None and self.mentions_self != facts.mentions_self:
            return False
        if self.reply_targets_self is not None and self.reply_targets_self != facts.reply_targets_self:
            return False
        if self.mentioned_everyone is not None and self.mentioned_everyone != facts.mentioned_everyone:
            return False
        if self.attachments_present is not None and self.attachments_present != facts.attachments_present:
            return False
        if self.message_subtype is not None and self.message_subtype != facts.message_subtype:
            return False
        if self.notice_type is not None and self.notice_type != facts.notice_type:
            return False
        if self.notice_subtype is not None and self.notice_subtype != facts.notice_subtype:
            return False
        if self.sender_roles and not set(self.sender_roles).intersection(facts.sender_roles):
            return False
        if self.attachment_kinds and not set(self.attachment_kinds).intersection(facts.attachment_kinds):
            return False
        return True

    def match_keys(self) -> list[str]:
        """返回当前声明了哪些匹配字段.

        Returns:
            list[str]: 所有已声明条件的字段名列表.
        """

        keys: list[str] = []
        if self.platform is not None:
            keys.append("platform")
        if self.event_kind is not None:
            keys.append("event_kind")
        if self.scene is not None:
            keys.append("scene")
        if self.actor_id is not None:
            keys.append("actor_id")
        if self.channel_scope is not None:
            keys.append("channel_scope")
        if self.thread_id is not None:
            keys.append("thread_id")
        if self.targets_self is not None:
            keys.append("targets_self")
        if self.mentions_self is not None:
            keys.append("mentions_self")
        if self.reply_targets_self is not None:
            keys.append("reply_targets_self")
        if self.mentioned_everyone is not None:
            keys.append("mentioned_everyone")
        if self.sender_roles:
            keys.append("sender_roles")
        if self.attachments_present is not None:
            keys.append("attachments_present")
        if self.attachment_kinds:
            keys.append("attachment_kinds")
        if self.message_subtype is not None:
            keys.append("message_subtype")
        if self.notice_type is not None:
            keys.append("notice_type")
        if self.notice_subtype is not None:
            keys.append("notice_subtype")
        return keys

    def specificity(self) -> int:
        """返回当前匹配条件的特异性.

        Returns:
            int: 当前声明字段的数量. 字段越多, 特异性越高.
        """

        return len(self.match_keys())


@dataclass(slots=True)
class SessionLocatorResult:
    """session config 的定位结果.

    Attributes:
        session_id (str): 当前事件命中的会话 ID.
        template_id (str): 这份会话配置声明的模板 ID.
        config_path (str): 实际命中的配置文件路径.
        channel_scope (str): 当前事件的 canonical channel scope.
        thread_id (str): 当前事件对应的 thread ID.
    """

    session_id: str
    template_id: str = ""
    config_path: str = ""
    channel_scope: str = ""
    thread_id: str = ""


# endregion


# region session config 原始形状
@dataclass(slots=True)
class DomainCase:
    """某个决策域下的一条局部 case.

    Attributes:
        case_id (str): 这条 case 的稳定 ID.
        when (MatchSpec | None): 内联匹配条件.
        when_ref (str): 指向 `SessionConfig.selectors` 的引用名.
        use (dict[str, Any]): 命中后要覆盖到当前决策域的字段.
        priority (int): case 的优先级. 数字越大越优先.
        metadata (dict[str, Any]): 额外调试信息.
    """

    case_id: str
    when: MatchSpec | None = None
    when_ref: str = ""
    use: dict[str, Any] = field(default_factory=dict)
    priority: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DomainConfig:
    """某个决策域的 `default + cases` 配置.

    Attributes:
        default (dict[str, Any]): 当前决策域的默认配置.
        cases (list[DomainCase]): 当前决策域的局部修正规则.
    """

    default: dict[str, Any] = field(default_factory=dict)
    cases: list[DomainCase] = field(default_factory=list)


@dataclass(slots=True)
class RoutingDomainConfig(DomainConfig):
    """路由域配置.

    Attributes:
        default (dict[str, Any]): 默认路由配置, 常见字段是 `profile` 和 `actor_lane`.
        cases (list[DomainCase]): 路由域下的局部 case.
    """


@dataclass(slots=True)
class AdmissionDomainConfig(DomainConfig):
    """准入域配置.

    Attributes:
        default (dict[str, Any]): 默认准入配置, 常见字段是 `mode`.
        cases (list[DomainCase]): 准入域下的局部 case.
    """


@dataclass(slots=True)
class ContextDomainConfig(DomainConfig):
    """上下文域配置.

    Attributes:
        default (dict[str, Any]): 默认上下文配置.
        cases (list[DomainCase]): 上下文域下的局部 case.
    """


@dataclass(slots=True)
class PersistenceDomainConfig(DomainConfig):
    """持久化域配置.

    Attributes:
        default (dict[str, Any]): 默认事件持久化配置.
        cases (list[DomainCase]): 持久化域下的局部 case.
    """


@dataclass(slots=True)
class ExtractionDomainConfig(DomainConfig):
    """长期记忆标签域配置.

    Attributes:
        default (dict[str, Any]): 默认标签配置.
        cases (list[DomainCase]): 标签域下的局部 case.
    """


@dataclass(slots=True)
class ComputerDomainConfig(DomainConfig):
    """computer / world policy 域配置.

    Attributes:
        default (dict[str, Any]): 默认 computer 配置.
        cases (list[DomainCase]): computer 域下的局部 case.
    """


@dataclass(slots=True)
class SurfaceConfig:
    """某个 surface 下的各决策域配置.

    Attributes:
        routing (RoutingDomainConfig | None): 路由域配置.
        admission (AdmissionDomainConfig | None): 准入域配置.
        context (ContextDomainConfig | None): 上下文域配置.
        persistence (PersistenceDomainConfig | None): 持久化域配置.
        extraction (ExtractionDomainConfig | None): 记忆提取域配置.
        computer (ComputerDomainConfig | None): computer 域配置.
    """

    routing: RoutingDomainConfig | None = None
    admission: AdmissionDomainConfig | None = None
    context: ContextDomainConfig | None = None
    persistence: PersistenceDomainConfig | None = None
    extraction: ExtractionDomainConfig | None = None
    computer: ComputerDomainConfig | None = None


@dataclass(slots=True)
class SessionConfig:
    """会话级配置真源.

    Attributes:
        session_id (str): 当前会话配置的稳定 ID.
        template_id (str): 使用的模板 ID.
        title (str): 可读标题.
        frontstage_profile (str): 会话默认前台 profile.
        selectors (dict[str, MatchSpec]): 可复用的匹配条件表.
        surfaces (dict[str, SurfaceConfig]): 按 surface 划分的配置矩阵.
        metadata (dict[str, Any]): 加载来源等补充信息.
    """

    session_id: str
    template_id: str
    title: str = ""
    frontstage_profile: str = ""
    selectors: dict[str, MatchSpec] = field(default_factory=dict)
    surfaces: dict[str, SurfaceConfig] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SurfaceResolution:
    """当前事件命中的 surface.

    Attributes:
        surface_id (str): 命中的 surface 名.
        exists (bool): 这条 surface 是否在当前 session config 里存在.
        source (str): 这次解析是按什么规则得到的.
        metadata (dict[str, Any]): 解析时留下的补充信息.
    """

    surface_id: str
    exists: bool = True
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# endregion


# region domain decisions
@dataclass(slots=True)
class RoutingDecision:
    """路由结果.

    Attributes:
        actor_lane (str): 当前消息进入哪个 actor lane.
        profile_id (str): 当前消息使用哪个 profile.
        reason (str): 这次决策为什么是这个结果.
        source_case_id (str): 命中的 case ID. 没命中时为空.
        priority (int): 命中 case 的优先级.
        specificity (int): 命中条件的特异性.
    """

    actor_lane: str = "frontstage"
    profile_id: str = ""
    reason: str = ""
    source_case_id: str = ""
    priority: int = 100
    specificity: int = 0


@dataclass(slots=True)
class AdmissionDecision:
    """准入结果.

    Attributes:
        mode (str): 当前消息的准入模式, 例如 `respond`.
        reason (str): 这次决策为什么是这个结果.
        source_case_id (str): 命中的 case ID. 没命中时为空.
        priority (int): 命中 case 的优先级.
        specificity (int): 命中条件的特异性.
    """

    mode: str = "respond"
    reason: str = ""
    source_case_id: str = ""
    priority: int = 100
    specificity: int = 0


@dataclass(slots=True)
class ContextDecision:
    """上下文补充结果.

    Attributes:
        sticky_note_targets (list[str]): 要注入的 sticky note 实体引用列表.
        retrieval_tags (list[str]): retrieval tag.
        context_labels (list[str]): 额外上下文标签.
        notes (list[str]): 其他说明.
    """

    sticky_note_targets: list[str] = field(default_factory=list)
    retrieval_tags: list[str] = field(default_factory=list)
    context_labels: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PersistenceDecision:
    """事件持久化结果.

    Attributes:
        persist_event (bool): 当前事件是否写入事件存储.
        reason (str): 这次决策为什么是这个结果.
        source_case_id (str): 命中的 case ID. 没命中时为空.
        priority (int): 命中 case 的优先级.
        specificity (int): 命中条件的特异性.
    """

    persist_event: bool = True
    reason: str = ""
    source_case_id: str = ""
    priority: int = 100
    specificity: int = 0


@dataclass(slots=True)
class ExtractionDecision:
    """长期记忆标签结果.

    Attributes:
        tags (list[str]): 当前 event 附带的长期记忆标签.
        reason (str): 这次决策为什么是这个结果.
        source_case_id (str): 命中的 case ID. 没命中时为空.
        priority (int): 命中 case 的优先级.
        specificity (int): 命中条件的特异性.
    """

    tags: list[str] = field(default_factory=list)
    reason: str = ""
    source_case_id: str = ""
    priority: int = 100
    specificity: int = 0


@dataclass(slots=True)
class ComputerPolicyDecision:
    """computer / Work World 相关决策结果.

    Attributes:
        actor_kind (str): 当前 actor 的计算机世界身份.
        backend (str): 当前使用的 backend.
        allow_exec (bool): 是否允许执行一次性命令.
        allow_sessions (bool): 是否允许开启 shell session.
        roots (dict[str, dict[str, bool]]): 每个 world root 的可见性定义.
        visible_skills (list[str] | None): 当前 actor 真正可见的技能列表.
            传入 `None` 表示继续沿用 profile / capability 默认值.
        visible_subagents (list[str]): 当前 actor 真正可见的 subagent 列表.
        notes (list[str]): 其他说明.
        reason (str): 这次决策为什么是这个结果.
        source_case_id (str): 命中的 case ID. 没命中时为空.
        priority (int): 命中 case 的优先级.
        specificity (int): 命中条件的特异性.
    """

    actor_kind: str = "frontstage_agent"
    backend: str = "host"
    allow_exec: bool = True
    allow_sessions: bool = True
    roots: dict[str, dict[str, bool]] = field(default_factory=dict)
    visible_skills: list[str] | None = None
    visible_subagents: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    reason: str = ""
    source_case_id: str = ""
    priority: int = 100
    specificity: int = 0


# endregion


__all__ = [
    "AdmissionDecision",
    "AdmissionDomainConfig",
    "ComputerDomainConfig",
    "ComputerPolicyDecision",
    "ContextDecision",
    "ContextDomainConfig",
    "DomainCase",
    "DomainConfig",
    "EventFacts",
    "ExtractionDecision",
    "ExtractionDomainConfig",
    "MatchSpec",
    "PersistenceDecision",
    "PersistenceDomainConfig",
    "RoutingDecision",
    "RoutingDomainConfig",
    "SessionConfig",
    "SessionLocatorResult",
    "SurfaceConfig",
    "SurfaceResolution",
]
