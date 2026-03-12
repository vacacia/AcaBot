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

from dataclasses import dataclass, field

from .app import RuntimeApp
from .models import PendingApprovalRecord
from .plugin_manager import RuntimePluginManager
from .runs import RunManager


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
        interrupted_run_ids (list[str]): 启动恢复阶段识别出的中断 run 列表.
    """

    active_runs: list[ActiveRunSnapshot] = field(default_factory=list)
    pending_approvals: list[PendingApprovalRecord] = field(default_factory=list)
    loaded_plugins: list[str] = field(default_factory=list)
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
        loaded_plugins (list[str]): reload 后成功加载的插件名列表.
    """

    loaded_plugins: list[str] = field(default_factory=list)


# endregion


# region control plane
class RuntimeControlPlane:
    """runtime 的最小本地 control plane.

    当前只暴露:
    - `get_status`
    - `reload_plugins`

    后续 `/status`, `/reload_plugin`, WebUI 都应优先通过这层进入 runtime.
    """

    def __init__(
        self,
        *,
        app: RuntimeApp,
        run_manager: RunManager,
        plugin_manager: RuntimePluginManager | None = None,
    ) -> None:
        """初始化 RuntimeControlPlane.

        Args:
            app: 当前 runtime app.
            run_manager: run 生命周期管理器.
            plugin_manager: 可选的 runtime plugin manager.
        """

        self.app = app
        self.run_manager = run_manager
        self.plugin_manager = plugin_manager

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
            interrupted_run_ids=list(self.app.last_recovery_report.interrupted_run_ids),
        )

    async def reload_plugins(self) -> PluginReloadSnapshot:
        """按当前配置重载 runtime plugins.

        Returns:
            一份 PluginReloadSnapshot.
        """

        loaded = await self.app.reload_plugins()
        return PluginReloadSnapshot(loaded_plugins=list(loaded))

    def _list_loaded_plugins(self) -> list[str]:
        """返回当前已加载插件名列表.

        Returns:
            已加载插件名列表.
        """

        if self.plugin_manager is None:
            return []
        return [plugin.name for plugin in self.plugin_manager.loaded]


# endregion
