"""runtime.profile_loader 定义 profile, prompt 和 binding rule 相关接口.

这一层解决 3 个问题:
- 按 agent_id 取到 AgentProfile.
- 按 prompt_ref 取到 system prompt 文本.
- 按 event + canonical id 解析当前应绑定哪个 agent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

from acabot.types import StandardEvent

from .computer import ComputerPolicy, parse_computer_policy
from .models import AgentProfile, BindingRule, RouteDecision, SkillAssignment


def parse_skill_assignments(raw_items: object) -> list[SkillAssignment]:
    """把 profile 配置里的 skill assignment 归一化.

    Args:
        raw_items: 原始 `skill_assignments` 配置.

    Returns:
        归一化后的 SkillAssignment 列表.

    Raises:
        ValueError: 配置项不是合法的 mapping 或字符串时抛出.
    """

    allowed_modes = {"inline", "prefer_delegate", "must_delegate", "manual"}
    assignments: list[SkillAssignment] = []
    for item in list(raw_items or []):
        if isinstance(item, str):
            assignments.append(SkillAssignment(skill_name=str(item)))
            continue
        if not isinstance(item, dict):
            raise ValueError("Skill assignment must be a mapping or string")
        delegation_mode = str(item.get("delegation_mode", "inline") or "inline")
        if delegation_mode not in allowed_modes:
            raise ValueError(f"Unsupported delegation_mode: {delegation_mode}")
        assignments.append(
            SkillAssignment(
                skill_name=str(item.get("skill_name", "") or ""),
                delegation_mode=delegation_mode,
                delegate_agent_id=str(item.get("delegate_agent_id", "") or ""),
                notes=str(item.get("notes", "") or ""),
                metadata={
                    key: value
                    for key, value in dict(item).items()
                    if key not in {"skill_name", "delegation_mode", "delegate_agent_id", "notes"}
                },
            )
        )
    return [item for item in assignments if item.skill_name]


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


class ChainedPromptLoader(PromptLoader):
    """加载器回退.

    Attributes:
        loaders (list[PromptLoader]): 按顺序尝试的 prompt loaders.
    """

    def __init__(self, loaders: list[PromptLoader]) -> None:
        """初始化 chained prompt loader.

        Args:
            loaders: 按顺序尝试的 prompt loader 列表.
        """

        self.loaders = list(loaders)

    def load(self, prompt_ref: str) -> str:
        """按顺序尝试加载 prompt.
        
        FileSystemPromptLoader > static_loader

        Args:
            prompt_ref: profile 中声明的 prompt 引用.

        Returns:
            对应的 system prompt 文本.

        Raises:
            KeyError: 所有 loader 都未命中时抛出.
        """

        for loader in self.loaders:
            try:
                return loader.load(prompt_ref)
            except KeyError:
                continue
        raise KeyError(f"Unknown prompt_ref: {prompt_ref}")


class FileSystemPromptLoader(PromptLoader):
    """从 `prompts/` 目录加载 prompt 的 loader.

    Attributes:
        root (Path): prompt 根目录.
        extensions (tuple[str, ...]): 允许尝试的文件扩展名.
    """

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
            对应 prompt 文件的文本.

        Raises:
            KeyError: 目标 prompt 文件不存在时抛出.
        """

        path = self._resolve_prompt_path(prompt_ref)
        if path is None:
            raise KeyError(f"Unknown prompt_ref: {prompt_ref}")
        return path.read_text(encoding="utf-8")

    def _resolve_prompt_path(self, prompt_ref: str) -> Path | None:
        """把 prompt_ref 解析成实际文件路径.
            - 显式路径: "prompt/system.txt" → 直接查找 system.txt
            - 省略扩展名: "prompt/system" → 尝试 system.md, system.txt 等
            - 目录简写: "prompt/role" → 尝试 role/index.md, role/index.txt 等

        Args:
            prompt_ref: profile 中声明的 prompt 引用, 通常以 "prompt/" 开头.

        Returns:
            命中的文件路径. 未命中时返回 None.
        """

        # 去掉 "prompt/" 前缀
        relative = prompt_ref.removeprefix("prompt/")

        candidate = self.root / relative
        candidates: list[Path] = []

        # 自带后缀
        if candidate.suffix:
            candidates.append(candidate)
        else:
            # 后缀猜测
            candidates.extend(candidate.with_suffix(ext) for ext in self.extensions)
            # 尝试该目录下的 index 文件
            candidates.extend((candidate / f"index{ext}") for ext in self.extensions)

        # 按优先级返回
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


class FileSystemProfileLoader:
    """从 `profiles/` 目录读取 AgentProfile 映射.

    Attributes:
        root (Path): profile 根目录.
        default_model (str): profile 文件未声明模型时的默认模型.
        prompt_prefix (str): 默认 prompt_ref 前缀.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        default_model: str,
        default_computer_policy: ComputerPolicy | None = None,
        prompt_prefix: str = "prompt",
    ) -> None:
        """初始化文件系统 profile loader.

        Args:
            root: profile 根目录.
            default_model: profile 文件未声明模型时的默认模型.
            default_computer_policy: profile 文件未声明 computer 时的默认 computer policy.
            prompt_prefix: 默认 prompt_ref 前缀.
        """

        self.root = Path(root)
        self.default_model = default_model
        self.default_computer_policy = default_computer_policy
        self.prompt_prefix = prompt_prefix.strip("/")

    def load_all(self) -> dict[str, AgentProfile]:
        """扫描目录并加载全部 profile 文件.

        Returns:
            `agent_id -> AgentProfile` 映射表.
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
        """

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Profile file must be a mapping: {path}")
        agent_id = str(raw.get("agent_id", "") or path.stem)
        return AgentProfile(
            agent_id=agent_id,
            name=str(raw.get("name", "") or agent_id),
            prompt_ref=str(
                raw.get("prompt_ref", "") or f"{self.prompt_prefix}/{agent_id}"
            ),
            default_model=str(raw.get("default_model", "") or self.default_model),
            enabled_tools=[str(item) for item in list(raw.get("enabled_tools", []) or [])],
            skill_assignments=parse_skill_assignments(raw.get("skill_assignments", [])),
            computer_policy=parse_computer_policy(
                raw.get("computer"),
                defaults=self.default_computer_policy,
            ),
            config=dict(raw),
        )


class FileSystemBindingLoader:
    """从 `bindings/` 目录读取 binding rule 配置.

    Attributes:
        root (Path): binding 配置根目录.
    """

    def __init__(self, root: str | Path) -> None:
        """初始化文件系统 binding loader.

        Args:
            root: binding 配置根目录.
        """

        self.root = Path(root)

    def load_all(self) -> list[dict[str, Any]]:
        """扫描目录并加载全部 binding 配置.

        Returns:
            归一化后的 rule 配置列表.
        """

        return self._load_rule_files()

    def _load_rule_files(self) -> list[dict[str, Any]]:
        """扫描目录并读取全部 rule 文件.

        Returns:
            归一化后的 rule 配置列表.
        """

        rules: list[dict[str, Any]] = []
        if not self.root.exists():
            return rules
        for path in sorted(self.root.glob("*.y*ml")):
            rules.extend(self._load_file(path))
        return rules

    def _load_file(self, path: Path) -> list[dict[str, Any]]:
        """从单个 YAML 文件加载 rule 配置.

        支持 3 种格式:
        - 顶层是单条 rule mapping.
        - 顶层是 rule list.
        - 顶层是 `{rules: [...]}`.

        Args:
            path: 当前 YAML 文件路径.

        Returns:
            归一化后的 rule 配置列表.

        Raises:
            ValueError: 文件格式不是合法 mapping 或 list 时抛出.
        """

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            nested = raw.get("rules")
            items = nested if isinstance(nested, list) else [raw]
        else:
            raise ValueError(f"Binding file must be a mapping or list: {path}")

        rules: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"Binding rule must be a mapping: {path}")
            rule_conf = dict(item)
            rule_conf.setdefault(
                self._default_id_field(),
                self._default_rule_id(path, index, len(items)),
            )
            rules.append(rule_conf)
        return rules

    @staticmethod
    def _default_rule_id(path: Path, index: int, total: int) -> str:
        """为缺省 rule_id 生成稳定值.

        Args:
            path: 当前规则来源文件.
            index: 规则在文件中的序号.
            total: 当前文件中的规则总数.

        Returns:
            生成后的默认 rule_id.
        """

        if total == 1:
            return f"fs:{path.stem}"
        return f"fs:{path.stem}:{index}"

    @staticmethod
    def _default_id_field() -> str:
        """返回当前规则类型的默认 ID 字段名.

        Returns:
            默认 ID 字段名.
        """

        return "rule_id"


class FileSystemInboundRuleLoader(FileSystemBindingLoader):
    """从 `inbound_rules/` 目录读取 inbound rule 配置.

    Attributes:
        root (Path): inbound rule 配置根目录.
    """

    def load_all(self) -> list[dict[str, Any]]:
        """扫描目录并加载全部 inbound rule 配置.

        Returns:
            归一化后的 inbound rule 配置列表.
        """

        return self._load_rule_files()


class FileSystemEventPolicyLoader(FileSystemBindingLoader):
    """从 `event_policies/` 目录读取 event policy 配置.

    Attributes:
        root (Path): event policy 配置根目录.
    """

    def load_all(self) -> list[dict[str, Any]]:
        """扫描目录并加载全部 event policy 配置.

        Returns:
            归一化后的 event policy 配置列表.
        """

        return self._load_rule_files()

    @staticmethod
    def _default_id_field() -> str:
        """返回 event policy 的默认 ID 字段名.

        Returns:
            默认的 policy_id 字段名.
        """

        return "policy_id"


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
        self._rule_ids: set[str] = set()

        for rule in rules or []:
            self.add_rule(rule)

    def add_rule(self, rule: BindingRule) -> None:
        """注册一条 binding rule.

        Args:
            rule: 待注册的 rule.

        Raises:
            KeyError: rule 指向未知 agent_id.
            ValueError: rule 没有任何 match 条件, rule_id 重复, 或与已有 rule 形成歧义冲突.
        """

        if rule.agent_id not in self.profiles:
            raise KeyError(f"Unknown agent_id in rule: {rule.agent_id}")
        if not rule.match_keys():
            raise ValueError("BindingRule must declare at least one match condition")
        if rule.rule_id in self._rule_ids:
            raise ValueError(f"Duplicate rule_id: {rule.rule_id}")
        self._validate_no_conflict(rule)
        self.rules.append(rule)
        self._rule_ids.add(rule.rule_id)

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

    def has_agent(self, agent_id: str) -> bool:
        """判断某个 agent_id 是否已注册.

        Args:
            agent_id: 待检查的 agent_id.

        Returns:
            当前 registry 是否包含该 agent.
        """

        return agent_id in self.profiles

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

    def _validate_no_conflict(self, candidate: BindingRule) -> None:
        """检查新 rule 是否和已有 rule 形成歧义冲突.

        Args:
            candidate: 待注册的 rule.

        Raises:
            ValueError: 当新 rule 会和已有 rule 产生不稳定 tie-break 时抛出.
        """

        for existing in self.rules:
            if not self._rules_conflict(existing, candidate):
                continue
            raise ValueError(
                "Ambiguous binding rules: "
                f"{existing.rule_id} conflicts with {candidate.rule_id}"
            )

    @staticmethod
    def _rules_conflict(left: BindingRule, right: BindingRule) -> bool:
        """判断两条 rule 是否会形成歧义冲突.

        Args:
            left: 已存在的 rule.
            right: 待注册的 rule.

        Returns:
            如果两条 rule 在当前选择策略下会形成不稳定冲突, 返回 True.
        """

        if left.priority != right.priority:
            return False
        if left.specificity() != right.specificity():
            return False
        if not AgentProfileRegistry._scalar_overlap(left.thread_id, right.thread_id):
            return False
        if not AgentProfileRegistry._scalar_overlap(left.event_type, right.event_type):
            return False
        if not AgentProfileRegistry._scalar_overlap(left.message_subtype, right.message_subtype):
            return False
        if not AgentProfileRegistry._scalar_overlap(left.notice_type, right.notice_type):
            return False
        if not AgentProfileRegistry._scalar_overlap(left.notice_subtype, right.notice_subtype):
            return False
        if not AgentProfileRegistry._scalar_overlap(left.actor_id, right.actor_id):
            return False
        if not AgentProfileRegistry._scalar_overlap(left.channel_scope, right.channel_scope):
            return False
        if not AgentProfileRegistry._scalar_overlap(left.targets_self, right.targets_self):
            return False
        if not AgentProfileRegistry._scalar_overlap(left.mentioned_everyone, right.mentioned_everyone):
            return False
        if not AgentProfileRegistry._roles_overlap(left.sender_roles, right.sender_roles):
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
            如果存在某个 sender_role 能同时满足两条 rule, 返回 True.
        """

        if not left or not right:
            return True
        return bool(set(left) & set(right))
