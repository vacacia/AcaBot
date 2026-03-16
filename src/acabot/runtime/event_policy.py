"""runtime.event_policy 定义 inbound event policy 解析器.

组件关系:

    StandardEvent
        |
        v
    EventPolicyRegistry
        |
        v
    EventPolicyDecision
        |
        v
    RouteDecision.metadata

负责把 "是否写 event log" 和 "是否参与 memory extraction" 变成正式控制面.
"""

from __future__ import annotations

from typing import Any

from acabot.types import StandardEvent

from .models import EventPolicy, EventPolicyDecision


# region event策略
class EventPolicyRegistry:
    """基于规则的 event policy 解析器.

    当前层负责两件事:
    - 判断当前 event 是否应该持久化到 ChannelEventStore
    - 判断当前 event 是否应该参与后续 memory extraction
    """

    def __init__(self, policies: list[EventPolicy] | None = None) -> None:
        """初始化 EventPolicyRegistry.

        Args:
            policies: 预加载的 EventPolicy 列表.

        Raises:
            ValueError: policy_id 重复, policy 没有 match 条件, 或与已有 policy 形成歧义冲突.
        """

        self.policies: list[EventPolicy] = []
        self._policy_ids: set[str] = set()
        for policy in policies or []:
            self.add_policy(policy)

    def add_policy(self, policy: EventPolicy) -> None:
        """注册一条 event policy.

        Args:
            policy: 待注册策略.

        Raises:
            ValueError: policy_id 重复, policy 没有 match 条件, 或与已有 policy 形成歧义冲突.
        """

        if policy.policy_id in self._policy_ids:
            raise ValueError(f"Duplicate event policy_id: {policy.policy_id}")
        if not policy.match_keys():
            raise ValueError("EventPolicy must declare at least one match condition")
        self._validate_no_conflict(policy)
        self.policies.append(policy)
        self._policy_ids.add(policy.policy_id)

    def reload(self, policies: list[EventPolicy] | None = None) -> None:
        """用一组新的 event policies 原子替换当前注册表."""

        self.policies = []
        self._policy_ids = set()
        for policy in policies or []:
            self.add_policy(policy)

    def get(self, policy_id: str) -> EventPolicy | None:
        """按 policy_id 读取一条 event policy."""

        for policy in self.policies:
            if policy.policy_id == policy_id:
                return policy
        return None

    def list_all(self) -> list[EventPolicy]:
        """返回当前全部 event policies."""

        return list(self.policies)

    def resolve(
        self,
        *,
        event: StandardEvent,
        actor_id: str,
        channel_scope: str,
    ) -> EventPolicyDecision:
        """根据规则解析当前事件的 event policy.

        Args:
            event: 当前标准化事件.
            actor_id: 当前事件的 actor_id.
            channel_scope: 当前事件的 channel_scope.

        Returns:
            一份 EventPolicyDecision.
        """

        matched = [
            policy for policy in self.policies
            if policy.matches(
                event=event,
                actor_id=actor_id,
                channel_scope=channel_scope,
            )
        ]
        if not matched:
            return EventPolicyDecision()

        best = matched[0]
        best_key = (best.priority, best.specificity())
        for policy in matched[1:]:
            current_key = (policy.priority, policy.specificity())
            if current_key > best_key:
                best = policy
                best_key = current_key

        return EventPolicyDecision(
            policy_id=best.policy_id,
            priority=best.priority,
            match_keys=best.match_keys(),
            persist_event=best.persist_event,
            extract_to_memory=best.extract_to_memory,
            memory_scopes=list(best.memory_scopes),
            tags=list(best.tags),
            metadata=dict(best.metadata),
        )

    def _validate_no_conflict(self, candidate: EventPolicy) -> None:
        """检查新策略是否和已有策略形成歧义冲突.

        Args:
            candidate: 待注册策略.

        Raises:
            ValueError: 当新策略会和已有策略产生不稳定 tie-break 时抛出.
        """

        for existing in self.policies:
            if not self._policies_conflict(existing, candidate):
                continue
            raise ValueError(
                "Ambiguous event policies: "
                f"{existing.policy_id} conflicts with {candidate.policy_id}"
            )

    @staticmethod
    def _policies_conflict(left: EventPolicy, right: EventPolicy) -> bool:
        """判断两条策略是否会形成歧义冲突.

        Args:
            left: 已存在的策略.
            right: 待注册的策略.

        Returns:
            如果两条策略在当前选择策略下会形成不稳定冲突, 返回 True.
        """

        if left.priority != right.priority:
            return False
        if left.specificity() != right.specificity():
            return False
        if not EventPolicyRegistry._scalar_overlap(left.platform, right.platform):
            return False
        if not EventPolicyRegistry._scalar_overlap(left.event_type, right.event_type):
            return False
        if not EventPolicyRegistry._scalar_overlap(left.message_subtype, right.message_subtype):
            return False
        if not EventPolicyRegistry._scalar_overlap(left.notice_type, right.notice_type):
            return False
        if not EventPolicyRegistry._scalar_overlap(left.notice_subtype, right.notice_subtype):
            return False
        if not EventPolicyRegistry._scalar_overlap(left.actor_id, right.actor_id):
            return False
        if not EventPolicyRegistry._scalar_overlap(left.channel_scope, right.channel_scope):
            return False
        if not EventPolicyRegistry._scalar_overlap(left.targets_self, right.targets_self):
            return False
        if not EventPolicyRegistry._scalar_overlap(left.mentions_self, right.mentions_self):
            return False
        if not EventPolicyRegistry._scalar_overlap(left.mentioned_everyone, right.mentioned_everyone):
            return False
        if not EventPolicyRegistry._scalar_overlap(left.reply_targets_self, right.reply_targets_self):
            return False
        if not EventPolicyRegistry._roles_overlap(left.sender_roles, right.sender_roles):
            return False
        return True

    @staticmethod
    def _scalar_overlap(left: str | None, right: str | None) -> bool:
        """判断两个标量匹配条件是否有重叠空间.

        Args:
            left: 左侧标量匹配值.
            right: 右侧标量匹配值.

        Returns:
            如果存在某种输入能同时满足这两个条件, 返回 True.
        """

        if left is None or right is None:
            return True
        return left == right

    @staticmethod
    def _roles_overlap(left: list[str], right: list[str]) -> bool:
        """判断两个 sender_roles 条件是否有重叠空间.

        Args:
            left: 左侧 sender_roles.
            right: 右侧 sender_roles.

        Returns:
            如果存在某个 sender_role 能同时满足两条策略, 返回 True.
        """

        if not left or not right:
            return True
        return bool(set(left) & set(right))


# endregion
