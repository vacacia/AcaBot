"""runtime.control_plane 提供本地 control plane 入口.

组件关系:

    RuntimeApp / RunManager / PluginManager
                   |
                   v
            RuntimeControlPlane
                   |
                   v
          local ops / future WebUI

不处理具体业务执行.
它只暴露最小的运行时运维接口, 例如 status 和 plugin reload.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .app import RuntimeApp
from .models import MemoryItem, PendingApprovalRecord
from .plugin_manager import RuntimePluginManager
from .profile_loader import AgentProfileRegistry
from .runs import RunManager
from .skills import RegisteredSkill, SkillRegistry
from .stores import MemoryStore
from .threads import ThreadManager


# region 状态模型
@dataclass(slots=True)
class ActiveRunSnapshot:
    """一条活跃 run 的轻量快照.

    Attributes:
        run_id (str): 当前 run 标识.
        thread_id (str): 当前 run 所属 thread.
        actor_id (str): 触发当前 run 的 actor.
        agent_id (str): 当前 run 使用的 agent.
        status (str): 当前 run 状态.
        started_at (int): 当前 run 开始时间.
    """

    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    status: str
    started_at: int


@dataclass(slots=True)
class RuntimeStatusSnapshot:
    """本地 control plane 返回的最小状态快照.

    Attributes:
        active_runs (list[ActiveRunSnapshot]): 当前活跃 runs.
        pending_approvals (list[PendingApprovalRecord]): 当前待审批 runs.
        loaded_plugins (list[str]): 当前已加载插件名列表.
        loaded_skills (list[str]): 当前已加载 skill 名列表.
        interrupted_run_ids (list[str]): 启动恢复阶段识别出的中断 run 列表.
    """

    active_runs: list[ActiveRunSnapshot] = field(default_factory=list)
    pending_approvals: list[PendingApprovalRecord] = field(default_factory=list)
    loaded_plugins: list[str] = field(default_factory=list)
    loaded_skills: list[str] = field(default_factory=list)
    interrupted_run_ids: list[str] = field(default_factory=list)

    @property
    def active_run_count(self) -> int:
        """返回当前活跃 run 数量.

        Returns:
            活跃 run 数量.
        """

        return len(self.active_runs)

    @property
    def pending_approval_count(self) -> int:
        """返回当前待审批数量.

        Returns:
            待审批数量.
        """

        return len(self.pending_approvals)


@dataclass(slots=True)
class PluginReloadSnapshot:
    """一次 plugin reload 的最小结果.

    Attributes:
        requested_plugins (list[str]): 当前请求重载的插件名列表. 为空表示全量重载.
        loaded_plugins (list[str]): reload 后成功加载的插件名列表.
        missing_plugins (list[str]): 配置里不存在的插件名列表.
    """

    requested_plugins: list[str] = field(default_factory=list)
    loaded_plugins: list[str] = field(default_factory=list)
    missing_plugins: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AgentSwitchSnapshot:
    """一次 thread agent switch 的结果.

    Attributes:
        ok (bool): 是否成功应用切换.
        thread_id (str): 目标 thread 标识.
        agent_id (str): 当前设置的 agent 标识.
        message (str): 附加说明信息.
    """

    ok: bool
    thread_id: str
    agent_id: str = ""
    message: str = ""


@dataclass(slots=True)
class MemoryQuerySnapshot:
    """一次 memory show 查询结果, 可查看任何级别的 memory.

    Attributes:
        scope (str): 当前查询的 scope.
        scope_key (str): 当前 scope 对应的 key.
        items (list[MemoryItem]): 查询到的 memory items.
    """

    scope: str
    scope_key: str
    items: list[MemoryItem] = field(default_factory=list)


@dataclass(slots=True)
class SkillSnapshot:
    """一次 skill 查询返回的轻量快照.

    Attributes:
        skill_name (str): skill 标识.
        skill_type (str): skill 类型.
        title (str): 展示标题.
        tool_names (list[str]): skill 暴露的工具列表.
        source (str): 注册来源.
        delegated_agent_id (str): 未来 delegation 默认 agent.
    """

    skill_name: str
    skill_type: str
    title: str
    tool_names: list[str] = field(default_factory=list)
    source: str = ""
    delegated_agent_id: str = ""


# endregion


# region control plane
class RuntimeControlPlane:
    """runtime 的最小本地 control plane.

    当前暴露:
    - `get_status`
    - `reload_plugins`
    - `switch_thread_agent`
    - `clear_thread_agent_override`
    - `show_memory`

    后续 `/status`, `/reload_plugin`, WebUI 都应优先通过这层进入 runtime.
    """

    def __init__(
        self,
        *,
        app: RuntimeApp,
        run_manager: RunManager,
        thread_manager: ThreadManager | None = None,
        memory_store: MemoryStore | None = None,
        profile_registry: AgentProfileRegistry | None = None,
        plugin_manager: RuntimePluginManager | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        """初始化 RuntimeControlPlane.

        Args:
            app: 当前 runtime app.
            run_manager: run 生命周期管理器.
            thread_manager: 可选的 thread 状态管理器.
            memory_store: 可选的长期记忆存储.
            profile_registry: 可选的 profile registry, 用于校验 agent 是否存在.
            plugin_manager: 可选的 runtime plugin manager.
            skill_registry: 可选的显式 skill 注册表.
        """

        self.app = app
        self.run_manager = run_manager
        self.thread_manager = thread_manager
        self.memory_store = memory_store
        self.profile_registry = profile_registry
        self.plugin_manager = plugin_manager
        self.skill_registry = skill_registry

    async def get_status(self) -> RuntimeStatusSnapshot:
        """读取当前 runtime 的最小状态快照.

        Returns:
            一份 RuntimeStatusSnapshot.
        """

        active_runs = await self.run_manager.list_active()
        return RuntimeStatusSnapshot(
            active_runs=[
                ActiveRunSnapshot(
                    run_id=run.run_id,
                    thread_id=run.thread_id,
                    actor_id=run.actor_id,
                    agent_id=run.agent_id,
                    status=run.status,
                    started_at=run.started_at,
                )
                for run in active_runs
            ],
            pending_approvals=self.app.list_pending_approvals(),
            loaded_plugins=self._list_loaded_plugins(),
            loaded_skills=self._list_loaded_skills(),
            interrupted_run_ids=list(self.app.last_recovery_report.interrupted_run_ids),
        )

    async def reload_plugins(self, plugin_names: list[str] | None = None) -> PluginReloadSnapshot:
        """按当前配置重载 runtime plugins.

        Args:
            plugin_names: 可选的插件名列表. 为空时执行全量重载.

        Returns:
            一份 PluginReloadSnapshot.
        """

        loaded, missing = await self.app.reload_plugins(plugin_names)
        return PluginReloadSnapshot(
            requested_plugins=list(plugin_names or []),
            loaded_plugins=list(loaded),
            missing_plugins=list(missing),
        )

    async def switch_thread_agent(
        self,
        *,
        thread_id: str,
        agent_id: str,
    ) -> AgentSwitchSnapshot:
        """为指定 thread 设置临时 agent override.

        
        Args:
            thread_id: 目标 thread 标识.
            agent_id: 要切换到的 agent 标识.

        Returns:
            一份 AgentSwitchSnapshot.
        """

        if self.profile_registry is not None and not self.profile_registry.has_agent(agent_id):
            return AgentSwitchSnapshot(
                ok=False,
                thread_id=thread_id,
                agent_id=agent_id,
                message="unknown agent_id",
            )
        if self.thread_manager is None:
            return AgentSwitchSnapshot(
                ok=False,
                thread_id=thread_id,
                agent_id=agent_id,
                message="thread manager unavailable",
            )

        thread = await self.thread_manager.get(thread_id)
        if thread is None:
            return AgentSwitchSnapshot(
                ok=False,
                thread_id=thread_id,
                agent_id=agent_id,
                message="thread not found",
            )

        # Thread Metadata Infection
        # 实际运行时在 _apply_thread_agent_override 生效
        thread.metadata["thread_agent_override"] = agent_id
        thread.metadata["thread_agent_override_set_at"] = int(time.time())
        await self.thread_manager.save(thread)
        return AgentSwitchSnapshot(
            ok=True,
            thread_id=thread_id,
            agent_id=agent_id,
        )

    async def clear_thread_agent_override(self, *, thread_id: str) -> AgentSwitchSnapshot:
        """清除指定 thread 的临时 agent override.

        Args:
            thread_id: 目标 thread 标识.

        Returns:
            一份 AgentSwitchSnapshot.
        """

        if self.thread_manager is None:
            return AgentSwitchSnapshot(
                ok=False,
                thread_id=thread_id,
                message="thread manager unavailable",
            )

        thread = await self.thread_manager.get(thread_id)
        if thread is None:
            return AgentSwitchSnapshot(
                ok=False,
                thread_id=thread_id,
                message="thread not found",
            )

        thread.metadata.pop("thread_agent_override", None)
        thread.metadata.pop("thread_agent_override_set_at", None)
        await self.thread_manager.save(thread)
        return AgentSwitchSnapshot(
            ok=True,
            thread_id=thread_id,
            message="cleared",
        )

    async def show_memory(
        self,
        *,
        scope: str,
        scope_key: str,
        memory_types: list[str] | None = None,
        limit: int = 20,
    ) -> MemoryQuerySnapshot:
        """按 scope 查询长期记忆.

        Args:
            scope: 当前查询的 scope.
            scope_key: 当前 scope 对应的 key.
            memory_types: 可选的 memory_type 过滤列表.
            limit: 最多返回多少条记忆.

        Returns:
            一份 MemoryQuerySnapshot.
        """

        if self.memory_store is None:
            return MemoryQuerySnapshot(scope=scope, scope_key=scope_key)

        items = await self.memory_store.find(
            scope=scope,
            scope_key=scope_key,
            memory_types=memory_types,
            limit=limit,
        )
        return MemoryQuerySnapshot(
            scope=scope,
            scope_key=scope_key,
            items=items,
        )

    async def list_skills(self) -> list[SkillSnapshot]:
        """列出当前已注册的显式 skills.

        Returns:
            SkillSnapshot 列表.
        """

        if self.skill_registry is None:
            return []
        return [self._to_skill_snapshot(item) for item in self.skill_registry.list_all()]

    def _list_loaded_plugins(self) -> list[str]:
        """返回当前已加载插件名列表.

        Returns:
            已加载插件名列表.
        """

        if self.plugin_manager is None:
            return []
        return [plugin.name for plugin in self.plugin_manager.loaded]

    def _list_loaded_skills(self) -> list[str]:
        """列出当前已注册 skill 名列表.

        Returns:
            skill_name 列表.
        """

        if self.skill_registry is None:
            return []
        return [item.spec.skill_name for item in self.skill_registry.list_all()]

    @staticmethod
    def _to_skill_snapshot(item: RegisteredSkill) -> SkillSnapshot:
        """把 RegisteredSkill 转成 SkillSnapshot.

        Args:
            item: 当前注册的 skill.

        Returns:
            对应的 SkillSnapshot.
        """

        return SkillSnapshot(
            skill_name=item.spec.skill_name,
            skill_type=item.spec.skill_type,
            title=item.spec.title,
            tool_names=list(item.spec.tool_names),
            source=item.source,
            delegated_agent_id=item.spec.delegated_agent_id,
        )


# endregion
