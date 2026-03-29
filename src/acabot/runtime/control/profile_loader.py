"""runtime.profile_loader 定义 profile 与 prompt 加载接口.

这一层只解决两件事:

- 按 `agent_id` 取到 `AgentProfile`
- 按 `prompt_ref` 取到 system prompt 文本
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

from ..computer import ComputerPolicy, parse_computer_policy
from ..contracts import AgentProfile, RouteDecision


def parse_skills(raw_items: object) -> list[str]:
    """把 profile 配置里的 skills 归一化成 skill 名列表.

    Args:
        raw_items: 原始 `skills` 配置.

    Returns:
        list[str]: 去重后的 skill 名列表.

    Raises:
        ValueError: 配置项不是字符串时抛出.
    """

    skills: list[str] = []
    seen: set[str] = set()
    for item in list(raw_items or []):
        if not isinstance(item, str):
            raise ValueError("Skill must be a string")
        skill_name = str(item or "").strip()
        if not skill_name or skill_name in seen:
            continue
        skills.append(skill_name)
        seen.add(skill_name)
    return skills


def resolve_profile_skills(raw_profile: dict[str, Any]) -> list[str]:
    """从 profile 配置里解析技能列表.

    Args:
        raw_profile: 原始 profile 配置.

    Returns:
        list[str]: 去重后的 skill 名列表.
    """

    if "skills" not in raw_profile:
        return []
    return parse_skills(raw_profile.get("skills", []))


def normalize_enabled_tools(raw_items: object) -> list[str]:
    """把 profile 配置里的 enabled_tools 归一化.

    Args:
        raw_items: 原始 `enabled_tools` 配置.

    Returns:
        list[str]: 去重后的工具名列表.
    """

    tools: list[str] = []
    seen: set[str] = set()
    for item in list(raw_items or []):
        tool_name = str(item or "").strip()
        if not tool_name or tool_name in seen:
            continue
        tools.append(tool_name)
        seen.add(tool_name)
    return tools


def normalize_profile_config(raw_profile: dict[str, Any]) -> dict[str, Any]:
    """把 profile 配置收口成当前运行时使用的字段形状.

    Args:
        raw_profile: 原始 profile 配置.

    Returns:
        dict[str, Any]: 规范化后的 profile 配置.
    """

    normalized = dict(raw_profile)
    normalized["skills"] = resolve_profile_skills(normalized)
    normalized["enabled_tools"] = normalize_enabled_tools(normalized.get("enabled_tools", []))
    normalized.pop("skill_assignments", None)
    return normalized


class PromptLoader(ABC):
    """system prompt 加载接口."""

    def __call__(self, prompt_ref: str) -> str:
        """允许把 loader 当作普通 callable 使用.

        Args:
            prompt_ref: profile 中声明的 prompt 引用.

        Returns:
            str: 对应的 system prompt 文本.
        """

        return self.load(prompt_ref)

    @abstractmethod
    def load(self, prompt_ref: str) -> str:
        """按 prompt_ref 加载 system prompt 文本.

        Args:
            prompt_ref: profile 中声明的 prompt 引用.

        Returns:
            str: 对应的 system prompt 文本.
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
            str: 对应的 system prompt 文本.

        Raises:
            KeyError: 当 prompt_ref 不存在时抛出.
        """

        return self.prompts[prompt_ref]

    def replace_prompts(self, prompts: dict[str, str]) -> None:
        """原地替换 prompt 映射, 供热刷新使用.

        Args:
            prompts: 新的 prompt 映射表.
        """

        self.prompts = dict(prompts)


class ChainedPromptLoader(PromptLoader):
    """按顺序回退的 prompt loader."""

    def __init__(self, loaders: list[PromptLoader]) -> None:
        """初始化 chained prompt loader.

        Args:
            loaders: 按顺序尝试的 prompt loader 列表.
        """

        self.loaders = list(loaders)

    def load(self, prompt_ref: str) -> str:
        """按顺序尝试加载 prompt.

        Args:
            prompt_ref: profile 中声明的 prompt 引用.

        Returns:
            str: 对应的 system prompt 文本.

        Raises:
            KeyError: 所有 loader 都未命中时抛出.
        """

        for loader in self.loaders:
            try:
                return loader.load(prompt_ref)
            except KeyError:
                continue
        raise KeyError(f"Unknown prompt_ref: {prompt_ref}")


class ReloadablePromptLoader(PromptLoader):
    """可在运行时替换底层 loader 的 prompt loader 代理."""

    def __init__(self, loader: PromptLoader) -> None:
        """初始化 reloadable prompt loader.

        Args:
            loader: 初始底层 loader.
        """

        self._loader = loader

    def replace_loader(self, loader: PromptLoader) -> None:
        """替换当前使用的底层 prompt loader.

        Args:
            loader: 新的底层 loader.
        """

        self._loader = loader

    def load(self, prompt_ref: str) -> str:
        """委托到底层 loader 读取 prompt.

        Args:
            prompt_ref: profile 中声明的 prompt 引用.

        Returns:
            str: 对应的 system prompt 文本.
        """

        return self._loader.load(prompt_ref)


class FileSystemPromptLoader(PromptLoader):
    """从 `prompts/` 目录加载 prompt 的 loader."""

    def __init__(
        self,
        root: str | Path,
        *,
        extensions: tuple[str, ...] = (".md", ".txt", ".prompt"),
    ) -> None:
        """初始化文件系统 prompt loader.

        Args:
            root: prompt 根目录.
            extensions: 当 prompt_ref 不带后缀时的候选扩展名.
        """

        self.root = Path(root)
        self.extensions = tuple(extensions)

    def load(self, prompt_ref: str) -> str:
        """从文件系统读取 prompt 文本.

        Args:
            prompt_ref: profile 中声明的 prompt 引用.

        Returns:
            str: 对应 prompt 文件的文本.

        Raises:
            KeyError: 目标 prompt 文件不存在时抛出.
        """

        path = self._resolve_prompt_path(prompt_ref)
        if path is None:
            raise KeyError(f"Unknown prompt_ref: {prompt_ref}")
        return path.read_text(encoding="utf-8")

    def _resolve_prompt_path(self, prompt_ref: str) -> Path | None:
        """把 prompt_ref 解析成实际文件路径.

        Args:
            prompt_ref: profile 中声明的 prompt 引用, 通常以 `prompt/` 开头.

        Returns:
            Path | None: 命中的文件路径. 未命中时返回 `None`.
        """

        # `subagent/*` 已经收口为 SUBAGENT.md 真源, 不再允许被 prompts/ 命名空间覆盖.
        if str(prompt_ref or "").strip().startswith("subagent/"):
            return None
        relative = prompt_ref.removeprefix("prompt/")
        candidate = self.root / relative
        candidates: list[Path] = []
        if candidate.suffix:
            candidates.append(candidate)
        else:
            candidates.extend(candidate.with_suffix(ext) for ext in self.extensions)
            candidates.extend((candidate / f"index{ext}") for ext in self.extensions)
        for path in candidates:
            if path.exists() and path.is_file():
                return path
        return None


class ProfileLoader(ABC):
    """AgentProfile 加载接口."""

    def __call__(self, decision: RouteDecision) -> AgentProfile:
        """允许把 loader 当作普通 callable 使用.

        Args:
            decision: router 产出的路由决策.

        Returns:
            AgentProfile: 对应这次 run 的 AgentProfile.
        """

        return self.load(decision)

    @abstractmethod
    def load(self, decision: RouteDecision) -> AgentProfile:
        """根据 RouteDecision 加载 AgentProfile.

        Args:
            decision: router 产出的路由决策.

        Returns:
            AgentProfile: 对应这次 run 的 AgentProfile.
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
            AgentProfile: 对应这次 run 的 AgentProfile.

        Raises:
            KeyError: 当目标 agent_id 和默认 agent_id 都不存在时抛出.
        """

        if decision.agent_id in self.profiles:
            return self.profiles[decision.agent_id]
        if self.default_agent_id is not None:
            return self.profiles[self.default_agent_id]
        raise KeyError(f"Unknown agent_id: {decision.agent_id}")


class FileSystemProfileLoader:
    """从 `profiles/` 目录读取 AgentProfile 映射."""

    def __init__(
        self,
        root: str | Path,
        *,
        default_computer_policy: ComputerPolicy | None = None,
        prompt_prefix: str = "prompt",
    ) -> None:
        """初始化文件系统 profile loader.

        Args:
            root: profile 根目录.
            default_computer_policy: profile 文件未声明 computer 时的默认 computer policy.
            prompt_prefix: 默认 prompt_ref 前缀.
        """

        self.root = Path(root)
        self.default_computer_policy = default_computer_policy
        self.prompt_prefix = prompt_prefix.strip("/")

    def load_all(self) -> dict[str, AgentProfile]:
        """扫描目录并加载全部 profile 文件.

        Returns:
            dict[str, AgentProfile]: `agent_id -> AgentProfile` 映射表.
        """

        profiles: dict[str, AgentProfile] = {}
        if not self.root.exists():
            return profiles
        for path in sorted(self.root.glob("*.y*ml")):
            profile = self._load_file(path)
            profiles[profile.agent_id] = profile
        return profiles

    def _load_file(self, path: Path) -> AgentProfile:
        """从单个 YAML 文件加载一条 AgentProfile.

        Args:
            path: 当前 YAML 文件路径.

        Returns:
            AgentProfile: 解析后的 profile.
        """

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Profile file must be a mapping: {path}")
        normalized = normalize_profile_config(raw)
        agent_id = str(normalized.get("agent_id", "") or path.stem)
        return AgentProfile(
            agent_id=agent_id,
            name=str(normalized.get("name", "") or agent_id),
            prompt_ref=str(normalized.get("prompt_ref", "") or f"{self.prompt_prefix}/{agent_id}"),
            enabled_tools=[str(item) for item in list(normalized.get("enabled_tools", []) or [])],
            skills=resolve_profile_skills(normalized),
            computer_policy=parse_computer_policy(
                normalized.get("computer"),
                defaults=self.default_computer_policy,
            ),
            config=dict(normalized),
        )


class AgentProfileRegistry(ProfileLoader):
    """同时管理 profile 列表和默认 profile 的最小 registry."""

    def __init__(
        self,
        *,
        profiles: dict[str, AgentProfile],
        default_agent_id: str,
    ) -> None:
        """初始化 AgentProfileRegistry.

        Args:
            profiles: `agent_id -> AgentProfile` 的映射表.
            default_agent_id: 默认 agent_id.

        Raises:
            ValueError: profiles 为空.
            KeyError: default_agent_id 未注册.
        """

        if not profiles:
            raise ValueError("profiles must not be empty")
        if default_agent_id not in profiles:
            raise KeyError(f"Unknown default_agent_id: {default_agent_id}")
        self.profiles = dict(profiles)
        self.default_agent_id = default_agent_id

    def reload(
        self,
        *,
        profiles: dict[str, AgentProfile],
        default_agent_id: str,
    ) -> None:
        """用一组新的 profiles 原子替换当前 registry.

        Args:
            profiles: 新的 profile 映射.
            default_agent_id: 新的默认 agent_id.
        """

        if not profiles:
            raise ValueError("profiles must not be empty")
        if default_agent_id not in profiles:
            raise KeyError(f"Unknown default_agent_id: {default_agent_id}")
        self.profiles = dict(profiles)
        self.default_agent_id = default_agent_id

    def list_profiles(self) -> list[AgentProfile]:
        """按 agent_id 排序返回全部 profiles.

        Returns:
            list[AgentProfile]: 当前全部 profiles.
        """

        return [self.profiles[agent_id] for agent_id in sorted(self.profiles)]

    def has_agent(self, agent_id: str) -> bool:
        """判断某个 agent_id 是否已注册.

        Args:
            agent_id: 待检查的 agent_id.

        Returns:
            bool: 当前 registry 是否包含该 agent.
        """

        return agent_id in self.profiles

    def load(self, decision: RouteDecision) -> AgentProfile:
        """根据 RouteDecision 加载最终 profile.

        Args:
            decision: router 产出的路由决策.

        Returns:
            AgentProfile: 命中的 AgentProfile.

        Raises:
            KeyError: decision.agent_id 未注册且默认 agent 也不存在时抛出.
        """

        if decision.agent_id in self.profiles:
            return self.profiles[decision.agent_id]
        return self.profiles[self.default_agent_id]


__all__ = [
    "AgentProfileRegistry",
    "ChainedPromptLoader",
    "FileSystemProfileLoader",
    "FileSystemPromptLoader",
    "ProfileLoader",
    "PromptLoader",
    "ReloadablePromptLoader",
    "StaticProfileLoader",
    "StaticPromptLoader",
    "normalize_profile_config",
    "parse_skills",
    "resolve_profile_skills",
]
