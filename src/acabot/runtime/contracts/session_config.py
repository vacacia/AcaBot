"""Session config 与 Work World 相关的运行时契约."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EventFacts:
    """标准化后的事件事实."""

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
    """针对 EventFacts 的共享匹配条件."""

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
        return len(self.match_keys())


@dataclass(slots=True)
class SessionLocatorResult:
    """session config 的定位结果."""

    session_id: str
    template_id: str = ""
    config_path: str = ""
    channel_scope: str = ""
    thread_id: str = ""


@dataclass(slots=True)
class DomainCase:
    """某个决策域下的一条局部 case."""

    case_id: str
    when: MatchSpec | None = None
    when_ref: str = ""
    use: dict[str, Any] = field(default_factory=dict)
    priority: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DomainConfig:
    """某个决策域的 default + cases 配置."""

    default: dict[str, Any] = field(default_factory=dict)
    cases: list[DomainCase] = field(default_factory=list)


@dataclass(slots=True)
class RoutingDomainConfig(DomainConfig):
    pass


@dataclass(slots=True)
class AdmissionDomainConfig(DomainConfig):
    pass


@dataclass(slots=True)
class ContextDomainConfig(DomainConfig):
    pass


@dataclass(slots=True)
class PersistenceDomainConfig(DomainConfig):
    pass


@dataclass(slots=True)
class ExtractionDomainConfig(DomainConfig):
    pass


@dataclass(slots=True)
class ComputerDomainConfig(DomainConfig):
    pass


@dataclass(slots=True)
class SurfaceConfig:
    """某个 surface 下的各决策域配置."""

    routing: RoutingDomainConfig | None = None
    admission: AdmissionDomainConfig | None = None
    context: ContextDomainConfig | None = None
    persistence: PersistenceDomainConfig | None = None
    extraction: ExtractionDomainConfig | None = None
    computer: ComputerDomainConfig | None = None


@dataclass(slots=True)
class SessionConfig:
    """会话级配置真源."""

    session_id: str
    template_id: str
    title: str = ""
    frontstage_profile: str = ""
    selectors: dict[str, MatchSpec] = field(default_factory=dict)
    surfaces: dict[str, SurfaceConfig] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SurfaceResolution:
    """当前事件命中的 surface 结果."""

    surface_id: str
    exists: bool = True
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RoutingDecision:
    actor_lane: str = "frontstage"
    profile_id: str = ""
    reason: str = ""
    source_case_id: str = ""
    priority: int = 100
    specificity: int = 0


@dataclass(slots=True)
class AdmissionDecision:
    mode: str = "respond"
    reason: str = ""
    source_case_id: str = ""
    priority: int = 100
    specificity: int = 0


@dataclass(slots=True)
class ContextDecision:
    sticky_note_scopes: list[str] = field(default_factory=list)
    prompt_slots: list[dict[str, Any]] = field(default_factory=list)
    retrieval_tags: list[str] = field(default_factory=list)
    context_labels: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PersistenceDecision:
    persist_event: bool = True
    reason: str = ""
    source_case_id: str = ""
    priority: int = 100
    specificity: int = 0


@dataclass(slots=True)
class ExtractionDecision:
    extract_to_memory: bool = False
    memory_scopes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    reason: str = ""
    source_case_id: str = ""
    priority: int = 100
    specificity: int = 0


@dataclass(slots=True)
class ComputerPolicyDecision:
    actor_kind: str = "frontstage_agent"
    backend: str = "host"
    allow_exec: bool = True
    allow_sessions: bool = True
    roots: dict[str, dict[str, bool]] = field(default_factory=dict)
    visible_skills: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


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
