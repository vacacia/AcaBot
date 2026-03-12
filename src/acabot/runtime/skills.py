"""runtime.skills 定义显式 skill 层.

组件关系:

    RuntimePlugin
        |
        v
     SkillRegistry
        |
        +--> ToolBroker.visible_tools()
        |
        `--> RuntimeControlPlane.list_skills()

这一层先解决两类问题:
- 工具组织型 skill, 负责把一组相关 tools 变成显式能力包
- 工作流协议型 skill, 负责携带 workflow guide 和可选 delegation hint

当前这一版故意不直接执行 subagent.
但会先把 delegated subagent 的请求和结果边界定义出来.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .models import AgentProfile

SkillType = Literal["capability", "workflow", "delegated"]


# region 数据对象
@dataclass(slots=True)
class SkillSpec:
    """一条显式 skill 定义.

    Attributes:
        skill_name (str): skill 的稳定标识.
        skill_type (SkillType): 当前 skill 类型.
        title (str): skill 的展示标题.
        description (str): 对 skill 的简短说明.
        tool_names (list[str]): 这个 skill 会暴露的工具列表.
        workflow_guide (str): 可选的工作流指引.
        reference_hint (str): 可选的 reference 使用提示.
        delegated_agent_id (str): 未来 delegated subagent 的默认 agent_id.
        metadata (dict[str, Any]): 附加元数据.
    """

    skill_name: str
    skill_type: SkillType
    title: str
    description: str
    tool_names: list[str] = field(default_factory=list)
    workflow_guide: str = ""
    reference_hint: str = ""
    delegated_agent_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RegisteredSkill:
    """SkillRegistry 内部持有的注册 skill.

    Attributes:
        spec (SkillSpec): 当前 skill 的声明.
        source (str): 当前 skill 来源, 通常是 plugin 名或内置来源.
        metadata (dict[str, Any]): 附加注册元数据.
    """

    spec: SkillSpec
    source: str = "runtime"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DelegatedSubagentRequest:
    """未来 delegated subagent 调用的请求边界.

    Attributes:
        skill_name (str): 本次委派对应的 skill.
        parent_run_id (str): 发起委派的父 run 标识.
        actor_id (str): 当前 actor.
        channel_scope (str): 当前 channel scope.
        delegated_agent_id (str): 目标 subagent 标识.
        payload (dict[str, Any]): 委派输入载荷.
        metadata (dict[str, Any]): 附加元数据.
    """

    skill_name: str
    parent_run_id: str
    actor_id: str
    channel_scope: str
    delegated_agent_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DelegatedSubagentResult:
    """未来 delegated subagent 调用的返回边界.

    Attributes:
        skill_name (str): 对应的 skill 名.
        ok (bool): 当前委派是否成功.
        delegated_run_id (str): 子 run 标识.
        summary (str): 面向父 agent 的结果摘要.
        artifacts (list[dict[str, Any]]): 子 agent 产出的结构化 artifacts.
        metadata (dict[str, Any]): 附加元数据.
    """

    skill_name: str
    ok: bool
    delegated_run_id: str = ""
    summary: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# endregion


# region registry
class SkillRegistry:
    """显式 skill 注册表.

    Attributes:
        _skills (dict[str, RegisteredSkill]): 当前已注册 skills.
    """

    def __init__(self) -> None:
        """初始化空的 SkillRegistry."""

        self._skills: dict[str, RegisteredSkill] = {}

    def register_skill(
        self,
        spec: SkillSpec,
        *,
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册一条 skill.

        Args:
            spec: 目标 skill 定义.
            source: 注册来源.
            metadata: 附加元数据.
        """

        self._skills[spec.skill_name] = RegisteredSkill(
            spec=spec,
            source=source,
            metadata=dict(metadata or {}),
        )

    def unregister_source(self, source: str) -> list[str]:
        """按 source 卸载 skill.

        Args:
            source: 注册来源标识.

        Returns:
            被删除的 skill 名列表.
        """

        removed: list[str] = []
        for skill_name, registered in list(self._skills.items()):
            if registered.source != source:
                continue
            removed.append(skill_name)
            del self._skills[skill_name]
        return removed

    def get(self, skill_name: str) -> RegisteredSkill | None:
        """读取一条 skill 注册记录.

        Args:
            skill_name: 目标 skill_name.

        Returns:
            命中的 RegisteredSkill. 不存在时返回 None.
        """

        return self._skills.get(skill_name)

    def list_all(self) -> list[RegisteredSkill]:
        """列出全部已注册 skill.

        Returns:
            按 skill_name 排序的 RegisteredSkill 列表.
        """

        return [self._skills[name] for name in sorted(self._skills)]

    def visible_skills(self, profile: AgentProfile) -> list[SkillSpec]:
        """返回当前 profile 显式启用的 skills.

        Args:
            profile: 当前 run 命中的 AgentProfile.

        Returns:
            按 profile 声明顺序过滤后的 SkillSpec 列表.
        """

        visible: list[SkillSpec] = []
        for skill_name in profile.enabled_skills:
            registered = self._skills.get(skill_name)
            if registered is None:
                continue
            visible.append(registered.spec)
        return visible

    def visible_tool_names(self, profile: AgentProfile) -> list[str]:
        """根据 profile 的 enabled_skills 展开可见工具名.

        Args:
            profile: 当前 run 命中的 AgentProfile.

        Returns:
            去重后的工具名列表.
        """

        tool_names: list[str] = []
        for spec in self.visible_skills(profile):
            for tool_name in spec.tool_names:
                if tool_name in tool_names:
                    continue
                tool_names.append(tool_name)
        return tool_names


# endregion
