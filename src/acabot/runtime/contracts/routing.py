"""runtime.contracts.routing 定义 profile、路由和事件策略对象."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from acabot.types import StandardEvent

from .common import RunMode
from .session_config import (
    AdmissionDecision,
    ComputerPolicyDecision,
    ContextDecision,
    EventFacts,
    ExtractionDecision,
    PersistenceDecision,
    RoutingDecision,
    SurfaceResolution,
)

if TYPE_CHECKING:
    from ..computer import ComputerPolicy


@dataclass(slots=True)
class AgentProfile:
    """agent 的静态配置 snapshot."""

    agent_id: str
    name: str
    prompt_ref: str
    default_model: str
    enabled_tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    computer_policy: "ComputerPolicy | None" = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BindingRule:
    """一条用于 route 解析的 binding rule."""

    rule_id: str
    agent_id: str
    priority: int = 100
    thread_id: str | None = None
    event_type: str | None = None
    message_subtype: str | None = None
    notice_type: str | None = None
    notice_subtype: str | None = None
    actor_id: str | None = None
    channel_scope: str | None = None
    targets_self: bool | None = None
    mentions_self: bool | None = None
    mentioned_everyone: bool | None = None
    reply_targets_self: bool | None = None
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
        if self.thread_id is not None and self.thread_id != thread_id:
            return False
        if self.event_type is not None and self.event_type != event.event_type:
            return False
        if self.message_subtype is not None and self.message_subtype != event.message_subtype:
            return False
        if self.notice_type is not None and self.notice_type != event.notice_type:
            return False
        if self.notice_subtype is not None and self.notice_subtype != event.notice_subtype:
            return False
        if self.actor_id is not None and self.actor_id != actor_id:
            return False
        if self.channel_scope is not None and self.channel_scope != channel_scope:
            return False
        if self.targets_self is not None and self.targets_self != event.targets_self:
            return False
        if self.mentions_self is not None and self.mentions_self != event.mentions_self:
            return False
        if self.mentioned_everyone is not None and self.mentioned_everyone != event.mentioned_everyone:
            return False
        if self.reply_targets_self is not None and self.reply_targets_self != event.reply_targets_self:
            return False
        if self.sender_roles:
            sender_role = event.sender_role or ""
            if sender_role not in self.sender_roles:
                return False
        return True

    def match_keys(self) -> list[str]:
        keys: list[str] = []
        if self.thread_id is not None:
            keys.append("thread_id")
        if self.event_type is not None:
            keys.append("event_type")
        if self.message_subtype is not None:
            keys.append("message_subtype")
        if self.notice_type is not None:
            keys.append("notice_type")
        if self.notice_subtype is not None:
            keys.append("notice_subtype")
        if self.actor_id is not None:
            keys.append("actor_id")
        if self.channel_scope is not None:
            keys.append("channel_scope")
        if self.targets_self is not None:
            keys.append("targets_self")
        if self.mentions_self is not None:
            keys.append("mentions_self")
        if self.mentioned_everyone is not None:
            keys.append("mentioned_everyone")
        if self.reply_targets_self is not None:
            keys.append("reply_targets_self")
        if self.sender_roles:
            keys.append("sender_roles")
        return keys

    def specificity(self) -> int:
        return len(self.match_keys())


@dataclass(slots=True)
class InboundRule:
    """一条 inbound 事件控制规则."""

    rule_id: str
    run_mode: RunMode
    priority: int = 100
    platform: str | None = None
    event_type: str | None = None
    message_subtype: str | None = None
    notice_type: str | None = None
    notice_subtype: str | None = None
    actor_id: str | None = None
    channel_scope: str | None = None
    targets_self: bool | None = None
    mentions_self: bool | None = None
    mentioned_everyone: bool | None = None
    reply_targets_self: bool | None = None
    sender_roles: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches(
        self,
        *,
        event: StandardEvent,
        actor_id: str,
        channel_scope: str,
    ) -> bool:
        if self.platform is not None and self.platform != event.platform:
            return False
        if self.event_type is not None and self.event_type != event.event_type:
            return False
        if self.message_subtype is not None and self.message_subtype != event.message_subtype:
            return False
        if self.notice_type is not None and self.notice_type != event.notice_type:
            return False
        if self.notice_subtype is not None and self.notice_subtype != event.notice_subtype:
            return False
        if self.actor_id is not None and self.actor_id != actor_id:
            return False
        if self.channel_scope is not None and self.channel_scope != channel_scope:
            return False
        if self.targets_self is not None and self.targets_self != event.targets_self:
            return False
        if self.mentions_self is not None and self.mentions_self != event.mentions_self:
            return False
        if self.mentioned_everyone is not None and self.mentioned_everyone != event.mentioned_everyone:
            return False
        if self.reply_targets_self is not None and self.reply_targets_self != event.reply_targets_self:
            return False
        if self.sender_roles:
            sender_role = event.sender_role or ""
            if sender_role not in self.sender_roles:
                return False
        return True

    def match_keys(self) -> list[str]:
        keys: list[str] = []
        if self.platform is not None:
            keys.append("platform")
        if self.event_type is not None:
            keys.append("event_type")
        if self.message_subtype is not None:
            keys.append("message_subtype")
        if self.notice_type is not None:
            keys.append("notice_type")
        if self.notice_subtype is not None:
            keys.append("notice_subtype")
        if self.actor_id is not None:
            keys.append("actor_id")
        if self.channel_scope is not None:
            keys.append("channel_scope")
        if self.targets_self is not None:
            keys.append("targets_self")
        if self.mentions_self is not None:
            keys.append("mentions_self")
        if self.mentioned_everyone is not None:
            keys.append("mentioned_everyone")
        if self.reply_targets_self is not None:
            keys.append("reply_targets_self")
        if self.sender_roles:
            keys.append("sender_roles")
        return keys

    def specificity(self) -> int:
        return len(self.match_keys())


@dataclass(slots=True)
class EventPolicy:
    """一条 inbound event policy."""

    policy_id: str
    priority: int = 100
    platform: str | None = None
    event_type: str | None = None
    message_subtype: str | None = None
    notice_type: str | None = None
    notice_subtype: str | None = None
    actor_id: str | None = None
    channel_scope: str | None = None
    targets_self: bool | None = None
    mentions_self: bool | None = None
    mentioned_everyone: bool | None = None
    reply_targets_self: bool | None = None
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
        if self.platform is not None and self.platform != event.platform:
            return False
        if self.event_type is not None and self.event_type != event.event_type:
            return False
        if self.message_subtype is not None and self.message_subtype != event.message_subtype:
            return False
        if self.notice_type is not None and self.notice_type != event.notice_type:
            return False
        if self.notice_subtype is not None and self.notice_subtype != event.notice_subtype:
            return False
        if self.actor_id is not None and self.actor_id != actor_id:
            return False
        if self.channel_scope is not None and self.channel_scope != channel_scope:
            return False
        if self.targets_self is not None and self.targets_self != event.targets_self:
            return False
        if self.mentions_self is not None and self.mentions_self != event.mentions_self:
            return False
        if self.mentioned_everyone is not None and self.mentioned_everyone != event.mentioned_everyone:
            return False
        if self.reply_targets_self is not None and self.reply_targets_self != event.reply_targets_self:
            return False
        if self.sender_roles:
            sender_role = event.sender_role or ""
            if sender_role not in self.sender_roles:
                return False
        return True

    def match_keys(self) -> list[str]:
        keys: list[str] = []
        if self.platform is not None:
            keys.append("platform")
        if self.event_type is not None:
            keys.append("event_type")
        if self.message_subtype is not None:
            keys.append("message_subtype")
        if self.notice_type is not None:
            keys.append("notice_type")
        if self.notice_subtype is not None:
            keys.append("notice_subtype")
        if self.actor_id is not None:
            keys.append("actor_id")
        if self.channel_scope is not None:
            keys.append("channel_scope")
        if self.targets_self is not None:
            keys.append("targets_self")
        if self.mentions_self is not None:
            keys.append("mentions_self")
        if self.mentioned_everyone is not None:
            keys.append("mentioned_everyone")
        if self.reply_targets_self is not None:
            keys.append("reply_targets_self")
        if self.sender_roles:
            keys.append("sender_roles")
        return keys

    def specificity(self) -> int:
        return len(self.match_keys())


@dataclass(slots=True)
class EventPolicyDecision:
    """一次 inbound event policy 解析结果."""

    policy_id: str = ""
    priority: int = -1
    match_keys: list[str] = field(default_factory=list)
    persist_event: bool = True
    extract_to_memory: bool = False
    memory_scopes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
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

    这层仍然是 app / run manager 当前主线使用的路由对象,
    但它现在还会带上 session-config 主线算出来的细化决策,
    这样 app 和 pipeline 可以逐步改成直接消费正式决策对象.
    """

    thread_id: str
    actor_id: str
    agent_id: str
    channel_scope: str
    run_mode: RunMode = "respond"
    metadata: dict[str, Any] = field(default_factory=dict)
    event_facts: EventFacts | None = None
    surface_resolution: SurfaceResolution | None = None
    routing_decision: RoutingDecision | None = None
    admission_decision: AdmissionDecision | None = None
    context_decision: ContextDecision | None = None
    persistence_decision: PersistenceDecision | None = None
    extraction_decision: ExtractionDecision | None = None
    computer_policy_decision: ComputerPolicyDecision | None = None


__all__ = [
    "AgentProfile",
    "BindingRule",
    "EventPolicy",
    "EventPolicyDecision",
    "InboundRule",
    "RouteDecision",
]
