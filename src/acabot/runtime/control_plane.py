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
from .computer import (
    ComputerRuntimeOverride,
    ComputerRuntime,
    WorkspaceFileEntry,
    WorkspaceSandboxStatus,
    WorkspaceState,
)
from .model_registry import (
    EffectiveModelSnapshot,
    FileSystemModelRegistryManager,
    ModelBinding,
    ModelHealthCheckResult,
    ModelImpactSnapshot,
    ModelMutationResult,
    ModelProvider,
    ModelPreset,
    ModelRegistryStatusSnapshot,
    ModelReloadSnapshot,
)
from .models import MemoryItem, PendingApprovalRecord
from .plugin_manager import RuntimePluginManager
from .profile_loader import AgentProfileRegistry
from .runs import RunManager
from .skill_package import SkillPackageManifest
from .skills import ResolvedSkillAssignment, SkillCatalog
from .stores import MemoryStore
from .subagent_delegation import RegisteredSubagentExecutor, SubagentExecutorRegistry
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
        run_kind (str): 当前 run 类型, 例如 `user` 或 `subagent`.
        parent_run_id (str): 父 run 标识. 非 child run 时为空.
        delegated_skill (str): 当前 delegated skill 名. 非 child run 时为空.
    """

    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    status: str
    started_at: int
    run_kind: str = "user"
    parent_run_id: str = ""
    delegated_skill: str = ""


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
        display_name (str): 展示标题.
        description (str): 简短说明.
        has_references (bool): 是否带 references 目录.
        has_scripts (bool): 是否带 scripts 目录.
        has_assets (bool): 是否带 assets 目录.
    """

    skill_name: str
    display_name: str
    description: str
    has_references: bool = False
    has_scripts: bool = False
    has_assets: bool = False


@dataclass(slots=True)
class AgentSkillSnapshot:
    """某个 agent 当前绑定的 skill assignment 快照.

    Attributes:
        agent_id (str): 当前 agent 标识.
        skill_name (str): 目标 skill 标识.
        display_name (str): 展示标题.
        description (str): 简短说明.
        delegation_mode (str): 当前 assignment 的 delegation policy.
        delegate_agent_id (str): 目标 subagent 标识.
        notes (str): operator 附加说明.
        has_references (bool): 是否带 references 目录.
        has_scripts (bool): 是否带 scripts 目录.
        has_assets (bool): 是否带 assets 目录.
    """

    agent_id: str
    skill_name: str
    display_name: str
    description: str
    delegation_mode: str = "inline"
    delegate_agent_id: str = ""
    notes: str = ""
    has_references: bool = False
    has_scripts: bool = False
    has_assets: bool = False


@dataclass(slots=True)
class SubagentExecutorSnapshot:
    """当前已注册 subagent executor 的轻量快照.

    Attributes:
        agent_id (str): 对应的 subagent 标识.
        source (str): 注册来源.
        metadata (dict[str, object]): 附加元数据.
    """

    agent_id: str
    source: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


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
        skill_catalog: SkillCatalog | None = None,
        subagent_executor_registry: SubagentExecutorRegistry | None = None,
        model_registry_manager: FileSystemModelRegistryManager | None = None,
        computer_runtime: ComputerRuntime | None = None,
    ) -> None:
        """初始化 RuntimeControlPlane.

        Args:
            app: 当前 runtime app.
            run_manager: run 生命周期管理器.
            thread_manager: 可选的 thread 状态管理器.
            memory_store: 可选的长期记忆存储.
            profile_registry: 可选的 profile registry, 用于校验 agent 是否存在.
            plugin_manager: 可选的 runtime plugin manager.
            skill_catalog: 可选的统一 skill catalog.
            subagent_executor_registry: 可选的 subagent executor 注册表.
            model_registry_manager: 可选的模型注册表管理器.
            computer_runtime: 可选的 computer 基础设施入口.
        """

        self.app = app
        self.run_manager = run_manager
        self.thread_manager = thread_manager
        self.memory_store = memory_store
        self.profile_registry = profile_registry
        self.plugin_manager = plugin_manager
        self.skill_catalog = skill_catalog
        self.subagent_executor_registry = subagent_executor_registry
        self.model_registry_manager = model_registry_manager
        self.computer_runtime = computer_runtime

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
                    run_kind=str(run.metadata.get("run_kind", "user") or "user"),
                    parent_run_id=str(run.metadata.get("parent_run_id", "") or ""),
                    delegated_skill=str(run.metadata.get("delegated_skill", "") or ""),
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

        if self.skill_catalog is None:
            return []
        return [self._to_skill_snapshot(item) for item in self.skill_catalog.list_all()]

    async def list_agent_skills(self, agent_id: str) -> list[AgentSkillSnapshot]:
        """列出某个 agent 当前绑定的 skill assignment.

        Args:
            agent_id: 目标 agent 标识.

        Returns:
            AgentSkillSnapshot 列表.
        """

        if self.profile_registry is None or self.skill_catalog is None:
            return []
        if not self.profile_registry.has_agent(agent_id):
            return []
        profile = self.profile_registry.profiles[agent_id]
        return [
            self._to_agent_skill_snapshot(agent_id, item)
            for item in self.skill_catalog.resolve_assignments(profile)
        ]

    async def list_subagent_executors(self) -> list[SubagentExecutorSnapshot]:
        """列出当前已注册的 subagent executors.

        Returns:
            SubagentExecutorSnapshot 列表.
        """

        if self.subagent_executor_registry is None:
            return []
        return [
            self._to_subagent_executor_snapshot(item)
            for item in self.subagent_executor_registry.list_all()
        ]

    async def list_model_providers(self) -> list[ModelProvider]:
        if self.model_registry_manager is None:
            return []
        return self.model_registry_manager.list_providers()

    async def list_model_presets(self) -> list[ModelPreset]:
        if self.model_registry_manager is None:
            return []
        return self.model_registry_manager.list_presets()

    async def list_model_bindings(self) -> list[ModelBinding]:
        if self.model_registry_manager is None:
            return []
        return self.model_registry_manager.list_bindings()

    async def get_model_provider(self, provider_id: str) -> ModelProvider | None:
        if self.model_registry_manager is None:
            return None
        return self.model_registry_manager.get_provider(provider_id)

    async def get_model_preset(self, preset_id: str) -> ModelPreset | None:
        if self.model_registry_manager is None:
            return None
        return self.model_registry_manager.get_preset(preset_id)

    async def get_model_binding(self, binding_id: str) -> ModelBinding | None:
        if self.model_registry_manager is None:
            return None
        return self.model_registry_manager.get_binding(binding_id)

    async def get_model_provider_impact(self, provider_id: str) -> ModelImpactSnapshot:
        if self.model_registry_manager is None:
            return ModelImpactSnapshot(entity_type="provider", entity_id=provider_id)
        return self.model_registry_manager.get_provider_impact(provider_id)

    async def get_model_preset_impact(self, preset_id: str) -> ModelImpactSnapshot:
        if self.model_registry_manager is None:
            return ModelImpactSnapshot(entity_type="preset", entity_id=preset_id)
        return self.model_registry_manager.get_preset_impact(preset_id)

    async def get_model_binding_impact(self, binding_id: str) -> ModelImpactSnapshot:
        if self.model_registry_manager is None:
            return ModelImpactSnapshot(entity_type="binding", entity_id=binding_id)
        return self.model_registry_manager.get_binding_impact(binding_id)

    async def preview_effective_agent_model(self, agent_id: str) -> EffectiveModelSnapshot:
        if self.model_registry_manager is None:
            return EffectiveModelSnapshot(target_type="agent", target_id=agent_id, source="none")
        explicit = ""
        effective = ""
        if self.profile_registry is not None and self.profile_registry.has_agent(agent_id):
            profile = self.profile_registry.profiles[agent_id]
            explicit = str(profile.config.get("default_model", "") or "")
            effective = str(profile.default_model or "")
        return self.model_registry_manager.preview_effective_agent(
            agent_id=agent_id,
            explicit_profile_default_model=explicit,
            effective_profile_default_model=effective,
        )

    async def preview_effective_summary_model(self) -> EffectiveModelSnapshot:
        if self.model_registry_manager is None:
            return EffectiveModelSnapshot(
                target_type="system",
                target_id="compactor_summary",
                source="none",
            )
        return self.model_registry_manager.preview_effective_summary()

    async def upsert_model_provider(self, provider: ModelProvider) -> ModelMutationResult:
        if self.model_registry_manager is None:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="upsert",
                entity_type="provider",
                entity_id=provider.provider_id,
                message="model registry unavailable",
            )
        return await self.model_registry_manager.upsert_provider(provider)

    async def upsert_model_preset(self, preset: ModelPreset) -> ModelMutationResult:
        if self.model_registry_manager is None:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="upsert",
                entity_type="preset",
                entity_id=preset.preset_id,
                message="model registry unavailable",
            )
        return await self.model_registry_manager.upsert_preset(preset)

    async def upsert_model_binding(self, binding: ModelBinding) -> ModelMutationResult:
        if self.model_registry_manager is None:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="upsert",
                entity_type="binding",
                entity_id=binding.binding_id,
                message="model registry unavailable",
            )
        return await self.model_registry_manager.upsert_binding(binding)

    async def delete_model_provider(
        self,
        provider_id: str,
        *,
        force: bool = False,
    ) -> ModelMutationResult:
        if self.model_registry_manager is None:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="delete",
                entity_type="provider",
                entity_id=provider_id,
                message="model registry unavailable",
            )
        return await self.model_registry_manager.delete_provider(provider_id, force=force)

    async def delete_model_preset(
        self,
        preset_id: str,
        *,
        force: bool = False,
    ) -> ModelMutationResult:
        if self.model_registry_manager is None:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="delete",
                entity_type="preset",
                entity_id=preset_id,
                message="model registry unavailable",
            )
        return await self.model_registry_manager.delete_preset(preset_id, force=force)

    async def delete_model_binding(self, binding_id: str) -> ModelMutationResult:
        if self.model_registry_manager is None:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="delete",
                entity_type="binding",
                entity_id=binding_id,
                message="model registry unavailable",
            )
        return await self.model_registry_manager.delete_binding(binding_id)

    async def health_check_model_preset(self, preset_id: str) -> ModelHealthCheckResult:
        if self.model_registry_manager is None:
            return ModelHealthCheckResult(
                ok=False,
                provider_id="",
                preset_id=preset_id,
                model="",
                message="model registry unavailable",
            )
        return await self.model_registry_manager.health_check(preset_id=preset_id)

    async def reload_models(self) -> ModelReloadSnapshot:
        if self.model_registry_manager is None:
            return ModelReloadSnapshot(ok=False, error="model registry unavailable")
        return await self.model_registry_manager.reload()

    async def get_model_registry_status(self) -> ModelRegistryStatusSnapshot:
        if self.model_registry_manager is None:
            return ModelRegistryStatusSnapshot(last_error="model registry unavailable")
        return self.model_registry_manager.status()

    async def list_workspaces(self) -> list[WorkspaceState]:
        if self.computer_runtime is None:
            return []
        return await self.computer_runtime.list_workspaces()

    async def list_workspace_entries(
        self,
        *,
        thread_id: str,
        relative_path: str = "/",
    ) -> list[WorkspaceFileEntry]:
        if self.computer_runtime is None:
            return []
        return await self.computer_runtime.list_workspace_entries(
            thread_id=thread_id,
            relative_path=relative_path,
        )

    async def read_workspace_file(
        self,
        *,
        thread_id: str,
        relative_path: str,
    ) -> str:
        if self.computer_runtime is None:
            raise RuntimeError("computer runtime unavailable")
        return await self.computer_runtime.read_workspace_file(
            thread_id=thread_id,
            relative_path=relative_path,
        )

    async def list_workspace_sessions(self, *, thread_id: str) -> list[str]:
        if self.computer_runtime is None:
            return []
        return self.computer_runtime.list_session_ids(thread_id)

    async def list_workspace_attachments(self, *, thread_id: str) -> list[WorkspaceFileEntry]:
        if self.computer_runtime is None:
            return []
        return await self.computer_runtime.list_workspace_attachments(thread_id=thread_id)

    async def get_sandbox_status(self, *, thread_id: str) -> WorkspaceSandboxStatus:
        if self.computer_runtime is None:
            return WorkspaceSandboxStatus(
                thread_id=thread_id,
                backend_kind="",
                active=False,
                message="computer runtime unavailable",
            )
        return await self.computer_runtime.get_sandbox_status(thread_id)

    async def list_mirrored_skills(self, *, thread_id: str) -> list[str]:
        if self.computer_runtime is None:
            return []
        return self.computer_runtime.list_mirrored_skills(thread_id)

    async def list_workspace_activity(
        self,
        *,
        thread_id: str,
        limit: int = 50,
        step_types: list[str] | None = None,
    ):
        return await self.run_manager.list_thread_steps(
            thread_id,
            limit=limit,
            step_types=step_types,
        )

    async def set_thread_computer_override(
        self,
        *,
        thread_id: str,
        override: ComputerRuntimeOverride,
        force: bool = False,
    ) -> AgentSwitchSnapshot:
        if self.thread_manager is None:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="thread manager unavailable")
        if self.computer_runtime is None:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="computer runtime unavailable")
        thread = await self.thread_manager.get(thread_id)
        if thread is None:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="thread not found")
        active_runs = [
            run for run in await self.run_manager.list_active()
            if run.thread_id == thread_id
        ]
        active_sessions = self.computer_runtime.list_session_ids(thread_id)
        if (active_runs or active_sessions) and not force:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="thread in use")
        if force:
            await self.computer_runtime.close_all_sessions(thread_id)
            for run in active_runs:
                await self.run_manager.append_step(
                    self._control_plane_step(
                        run_id=run.run_id,
                        thread_id=thread_id,
                        step_type="computer_override",
                        status="cancelled",
                        payload={"reason": "computer override changed by operator"},
                    )
                )
                await self.run_manager.mark_cancelled(run.run_id, "computer override changed by operator")
            await self.computer_runtime.stop_workspace_sandbox(thread_id)
        await self.computer_runtime.set_thread_override(thread=thread, override=override)
        await self.thread_manager.save(thread)
        return AgentSwitchSnapshot(ok=True, thread_id=thread_id, message="computer override set")

    async def clear_thread_computer_override(self, *, thread_id: str, force: bool = False) -> AgentSwitchSnapshot:
        if self.thread_manager is None:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="thread manager unavailable")
        if self.computer_runtime is None:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="computer runtime unavailable")
        thread = await self.thread_manager.get(thread_id)
        if thread is None:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="thread not found")
        active_runs = [
            run for run in await self.run_manager.list_active()
            if run.thread_id == thread_id
        ]
        active_sessions = self.computer_runtime.list_session_ids(thread_id)
        if (active_runs or active_sessions) and not force:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="thread in use")
        if force:
            await self.computer_runtime.close_all_sessions(thread_id)
            for run in active_runs:
                await self.run_manager.append_step(
                    self._control_plane_step(
                        run_id=run.run_id,
                        thread_id=thread_id,
                        step_type="computer_override_clear",
                        status="cancelled",
                        payload={"reason": "computer override cleared by operator"},
                    )
                )
                await self.run_manager.mark_cancelled(run.run_id, "computer override cleared by operator")
            await self.computer_runtime.stop_workspace_sandbox(thread_id)
        await self.computer_runtime.clear_thread_override(thread=thread)
        await self.thread_manager.save(thread)
        return AgentSwitchSnapshot(ok=True, thread_id=thread_id, message="computer override cleared")

    async def prune_workspace(self, *, thread_id: str, force: bool = False) -> AgentSwitchSnapshot:
        if self.computer_runtime is None:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="computer runtime unavailable")
        active_runs = [
            run for run in await self.run_manager.list_active()
            if run.thread_id == thread_id
        ]
        active_sessions = self.computer_runtime.list_session_ids(thread_id)
        if (active_runs or active_sessions) and not force:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="workspace in use")
        if force:
            await self.computer_runtime.close_all_sessions(thread_id)
            for run in active_runs:
                await self.run_manager.append_step(
                    self._control_plane_step(
                        run_id=run.run_id,
                        thread_id=thread_id,
                        step_type="workspace_prune",
                        status="cancelled",
                        payload={"reason": "workspace pruned by operator"},
                    )
                )
                await self.run_manager.mark_cancelled(run.run_id, "workspace pruned by operator")
        await self.computer_runtime.prune_workspace(thread_id)
        return AgentSwitchSnapshot(ok=True, thread_id=thread_id, message="workspace pruned")

    async def stop_workspace_sandbox(self, *, thread_id: str, force: bool = False) -> AgentSwitchSnapshot:
        if self.computer_runtime is None:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="computer runtime unavailable")
        active_runs = [
            run for run in await self.run_manager.list_active()
            if run.thread_id == thread_id
        ]
        active_sessions = self.computer_runtime.list_session_ids(thread_id)
        if (active_runs or active_sessions) and not force:
            return AgentSwitchSnapshot(ok=False, thread_id=thread_id, message="sandbox in use")
        if force:
            await self.computer_runtime.close_all_sessions(thread_id)
            for run in active_runs:
                await self.run_manager.append_step(
                    self._control_plane_step(
                        run_id=run.run_id,
                        thread_id=thread_id,
                        step_type="sandbox_stop",
                        status="cancelled",
                        payload={"reason": "sandbox stopped by operator"},
                    )
                )
                await self.run_manager.mark_cancelled(run.run_id, "sandbox stopped by operator")
        await self.computer_runtime.stop_workspace_sandbox(thread_id)
        return AgentSwitchSnapshot(ok=True, thread_id=thread_id, message="sandbox stopped")

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

        if self.skill_catalog is None:
            return []
        return [item.skill_name for item in self.skill_catalog.list_all()]

    @staticmethod
    def _control_plane_step(
        *,
        run_id: str,
        thread_id: str,
        step_type: str,
        status: str,
        payload: dict[str, object],
    ):
        from .models import RunStep

        return RunStep(
            step_id=f"step:control:{int(time.time() * 1000)}:{step_type}:{run_id}",
            run_id=run_id,
            thread_id=thread_id,
            step_type=step_type,
            status=status,
            payload=payload,
            created_at=int(time.time()),
        )

    @staticmethod
    def _to_skill_snapshot(item: SkillPackageManifest) -> SkillSnapshot:
        """把 SkillPackageManifest 转成 SkillSnapshot.

        Args:
            item: 当前注册的 skill.

        Returns:
            对应的 SkillSnapshot.
        """

        return SkillSnapshot(
            skill_name=item.skill_name,
            display_name=item.display_name,
            description=item.description,
            has_references=item.has_references,
            has_scripts=item.has_scripts,
            has_assets=item.has_assets,
        )

    @staticmethod
    def _to_agent_skill_snapshot(
        agent_id: str,
        item: ResolvedSkillAssignment,
    ) -> AgentSkillSnapshot:
        """把 ResolvedSkillAssignment 转成 AgentSkillSnapshot.

        Args:
            agent_id: 当前 agent 标识.
            item: 已展开的 assignment.

        Returns:
            对应的 AgentSkillSnapshot.
        """

        return AgentSkillSnapshot(
            agent_id=agent_id,
            skill_name=item.skill.skill_name,
            display_name=item.skill.display_name,
            description=item.skill.description,
            delegation_mode=item.assignment.delegation_mode,
            delegate_agent_id=item.assignment.delegate_agent_id,
            notes=item.assignment.notes,
            has_references=item.skill.has_references,
            has_scripts=item.skill.has_scripts,
            has_assets=item.skill.has_assets,
        )

    @staticmethod
    def _to_subagent_executor_snapshot(item: RegisteredSubagentExecutor) -> SubagentExecutorSnapshot:
        """把 RegisteredSubagentExecutor 转成 SubagentExecutorSnapshot.

        Args:
            item: 当前注册的 subagent executor.

        Returns:
            对应的 SubagentExecutorSnapshot.
        """

        return SubagentExecutorSnapshot(
            agent_id=item.agent_id,
            source=item.source,
            metadata=dict(item.metadata),
        )


# endregion
