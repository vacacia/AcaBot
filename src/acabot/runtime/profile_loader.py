"""runtime.profile_loader 定义 profile, prompt 和 binding rule 相关接口.

这一层解决 3 个问题:
- 按 agent_id 取到 AgentProfile.
- 按 prompt_ref 取到 system prompt 文本.
- 按 event + canonical id 解析当前应绑定哪个 agent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from acabot.types import StandardEvent

from .models import AgentProfile, BindingRule, RouteDecision


class PromptLoader(ABC):
    """system prompt 加载接口."""

    def __call__(self, prompt_ref: str) -> str:
        """允许把 loader 当作普通 callable 使用.

        Args:
            prompt_ref: profile 中声明的 prompt 引用.

        Returns:
            对应的 system prompt 文本.
        """

        return self.load(prompt_ref)

    @abstractmethod
    def load(self, prompt_ref: str) -> str:
        """按 prompt_ref 加载 system prompt 文本.

        Args:
            prompt_ref: profile 中声明的 prompt 引用.

        Returns:
            对应的 system prompt 文本.
        """

        ...


class StaticPromptLoader(PromptLoader):
    """基于内存映射的 prompt loader."""

    def __init__(self, prompts: dict[str, str]) -> None:
        """初始化静态 prompt loader.

        Args:
            prompts: `prompt_ref -> prompt text` 的映射表.
        """

        self.prompts = dict(prompts)

    def load(self, prompt_ref: str) -> str:
        """从内存映射中读取 prompt 文本.

        Args:
            prompt_ref: profile 中声明的 prompt 引用.

        Returns:
            对应的 system prompt 文本.

        Raises:
            KeyError: 当 prompt_ref 不存在时抛出.
        """

        return self.prompts[prompt_ref]


class ProfileLoader(ABC):
    """AgentProfile 加载接口."""

    def __call__(self, decision: RouteDecision) -> AgentProfile:
        """允许把 loader 当作普通 callable 使用.

        Args:
            decision: router 产出的路由决策.

        Returns:
            对应这次 run 的 AgentProfile.
        """

        return self.load(decision)

    @abstractmethod
    def load(self, decision: RouteDecision) -> AgentProfile:
        """根据 RouteDecision 加载 AgentProfile.

        Args:
            decision: router 产出的路由决策.

        Returns:
            对应这次 run 的 AgentProfile.
        """

        ...


class StaticProfileLoader(ProfileLoader):
    """基于内存映射的 profile loader."""

    def __init__(
        self,
        *,
        profiles: dict[str, AgentProfile],
        default_agent_id: str | None = None,
    ) -> None:
        """初始化静态 profile loader.

        Args:
            profiles: `agent_id -> AgentProfile` 的映射表.
            default_agent_id: 当 decision.agent_id 未命中时可回退到的默认 agent_id.
        """

        self.profiles = dict(profiles)
        self.default_agent_id = default_agent_id

    def load(self, decision: RouteDecision) -> AgentProfile:
        """从内存映射中选择一个 AgentProfile.

        Args:
            decision: router 产出的路由决策.

        Returns:
            对应这次 run 的 AgentProfile.

        Raises:
            KeyError: 当目标 agent_id 和默认 agent_id 都不存在时抛出.
        """

        if decision.agent_id in self.profiles:
            return self.profiles[decision.agent_id]
        if self.default_agent_id is not None:
            return self.profiles[self.default_agent_id]
        raise KeyError(f"Unknown agent_id: {decision.agent_id}")


class AgentProfileRegistry(ProfileLoader):
    """同时管理 profile 和 binding rule 的最小 registry.

    这是 runtime v1 的正式 route authority.
    router 负责把 event 变成 canonical id, 具体该落到哪个 agent 由这里决定.
    当前规则选择策略是:
    - 先筛出所有命中的 rule
    - 取 `priority` 最高的 rule
    - 同优先级时取 `specificity` 更高的 rule
    - 再相同则保留先注册的 rule
    """

    def __init__(
        self,
        *,
        profiles: dict[str, AgentProfile],
        default_agent_id: str,
        rules: list[BindingRule] | None = None,
    ) -> None:
        """初始化 AgentProfileRegistry.

        Args:
            profiles: `agent_id -> AgentProfile` 的映射表.
            default_agent_id: 默认 agent_id. 当没有任何 binding 命中时使用.
            rules: 预加载的 rule 列表.

        Raises:
            ValueError: profiles 为空.
            KeyError: default_agent_id 或某条 rule 指向了未知 profile.
        """

        if not profiles:
            raise ValueError("profiles must not be empty")
        if default_agent_id not in profiles:
            raise KeyError(f"Unknown default_agent_id: {default_agent_id}")

        self.profiles = dict(profiles)
        self.default_agent_id = default_agent_id
        self.rules: list[BindingRule] = []

        for rule in rules or []:
            self.add_rule(rule)

    def add_rule(self, rule: BindingRule) -> None:
        """注册一条 binding rule.

        Args:
            rule: 待注册的 rule.

        Raises:
            KeyError: rule 指向未知 agent_id.
            ValueError: rule 没有任何 match 条件.
        """

        if rule.agent_id not in self.profiles:
            raise KeyError(f"Unknown agent_id in rule: {rule.agent_id}")
        if not rule.match_keys():
            raise ValueError("BindingRule must declare at least one match condition")
        self.rules.append(rule)

    def resolve_agent(
        self,
        *,
        event: StandardEvent,
        thread_id: str,
        actor_id: str,
        channel_scope: str,
    ) -> tuple[str, dict[str, Any]]:
        """根据 event 和 canonical id 解析当前应绑定的 agent.

        Args:
            event: 当前标准化消息事件.
            thread_id: 当前消息所属 thread_id.
            actor_id: 当前消息发送方的 actor_id.
            channel_scope: 当前消息所在 channel_scope.

        Returns:
            一个二元组.
            第一个值是命中的 agent_id.
            第二个值是写回 RouteDecision.metadata 的 binding 信息.
        """

        matched_rules = [
            rule for rule in self.rules
            if rule.matches(
                event=event,
                thread_id=thread_id,
                actor_id=actor_id,
                channel_scope=channel_scope,
            )
        ]
        if not matched_rules:
            return self.default_agent_id, self._default_metadata()

        best_rule = matched_rules[0]
        best_key = (best_rule.priority, best_rule.specificity())
        for rule in matched_rules[1:]:
            current_key = (rule.priority, rule.specificity())
            if current_key > best_key:
                best_rule = rule
                best_key = current_key

        return best_rule.agent_id, self._rule_metadata(best_rule)

    def load(self, decision: RouteDecision) -> AgentProfile:
        """根据 RouteDecision 加载最终 profile.

        Args:
            decision: router 产出的路由决策.

        Returns:
            命中的 AgentProfile.

        Raises:
            KeyError: decision.agent_id 未注册.
        """

        return self.profiles[decision.agent_id]

    @staticmethod
    def _default_metadata() -> dict[str, Any]:
        """构造 default fallback 的 metadata.

        Returns:
            default route 的 metadata 片段.
        """

        return {
            "binding_kind": "default",
            "binding_rule_id": "",
            "binding_priority": -1,
            "binding_match_keys": [],
        }

    @staticmethod
    def _rule_metadata(rule: BindingRule) -> dict[str, Any]:
        """把 BindingRule 转成 RouteDecision.metadata 片段.

        Args:
            rule: 已命中的 binding rule.

        Returns:
            可直接写入 `RouteDecision.metadata` 的轻量元数据.
        """

        return {
            "binding_kind": "rule",
            "binding_rule_id": rule.rule_id,
            "binding_priority": rule.priority,
            "binding_match_keys": rule.match_keys(),
        }
