"""runtime.profile_loader 定义最小 profile 和 prompt 加载接口.

解决两个问题: 按 agent_id 取到 AgentProfile, 按 prompt_ref 取到 system prompt 文本.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import AgentProfile, RouteDecision


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
