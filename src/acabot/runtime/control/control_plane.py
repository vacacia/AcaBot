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

import os
import time
from dataclasses import asdict

from ..app import RuntimeApp
from ..computer import (
    ComputerRuntime,
    WorkspaceFileEntry,
    WorkspaceSandboxStatus,
    WorkspaceState,
)
from .config_control_plane import RuntimeConfigControlPlane
from ..model.model_registry import (
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
from ..contracts import ChannelEventRecord, MessageRecord, RunRecord
from ..plugin_manager import RuntimePluginManager
from .profile_loader import AgentProfileRegistry
from ..references import (
    ReferenceBackend,
    ReferenceBodyLevel,
    ReferenceDocument,
    ReferenceDocumentInput,
    ReferenceDocumentRef,
    ReferenceHit,
    ReferenceMode,
    ReferenceSpace,
)
from ..storage.runs import RunManager
from ..skills import SkillPackageManifest
from ..skills import SkillCatalog
from ..storage.stores import ChannelEventStore, MemoryStore, MessageStore
from ..subagents import RegisteredSubagentExecutor, SubagentExecutorRegistry
from ..soul import SoulSource
from ..memory.file_backed import StickyNotesSource
from ..storage.threads import ThreadManager
from ..tool_broker import ToolBroker
from .model_ops import RuntimeModelControlOps
from .bot_shell import BotShellControlOps
from .reference_ops import RuntimeReferenceControlOps
from .session_shell import SessionShellControlOps
from .snapshots import (
    ActiveRunSnapshot,
    AgentSkillSnapshot,
    AgentSwitchSnapshot,
    BackendStatusSnapshot,
    GatewayStatusSnapshot,
    MemoryQuerySnapshot,
    PluginReloadSnapshot,
    RuntimeStatusSnapshot,
    SkillSnapshot,
    SubagentExecutorSnapshot,
)
from .ui_catalog import build_ui_options
from .log_buffer import InMemoryLogBuffer
from .workspace_ops import RuntimeWorkspaceControlOps


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
        message_store: MessageStore | None = None,
        channel_event_store: ChannelEventStore | None = None,
        soul_source: SoulSource | None = None,
        sticky_notes_source: StickyNotesSource | None = None,
        profile_registry: AgentProfileRegistry | None = None,
        plugin_manager: RuntimePluginManager | None = None,
        skill_catalog: SkillCatalog | None = None,
        subagent_executor_registry: SubagentExecutorRegistry | None = None,
        tool_broker: ToolBroker | None = None,
        model_registry_manager: FileSystemModelRegistryManager | None = None,
        computer_runtime: ComputerRuntime | None = None,
        reference_backend: ReferenceBackend | None = None,
        config_control_plane: RuntimeConfigControlPlane | None = None,
        log_buffer: InMemoryLogBuffer | None = None,
    ) -> None:
        """初始化 RuntimeControlPlane.

        Args:
            app: 当前 runtime app.
            run_manager: run 生命周期管理器.
            thread_manager: 可选的 thread 状态管理器.
            memory_store: 可选的长期记忆存储.
            message_store: 可选的 delivered message store.
            channel_event_store: 可选的 inbound event store.
            soul_source: 可选的 soul 文件真源服务.
            sticky_notes_source: 可选的 sticky note 文件真源服务.
            profile_registry: 可选的 profile registry, 用于校验 agent 是否存在.
            plugin_manager: 可选的 runtime plugin manager.
            skill_catalog: 可选的统一 skill catalog.
            subagent_executor_registry: 可选的 subagent executor 注册表.
            tool_broker: 可选的 tool broker, 用于给 WebUI 提供工具目录.
            model_registry_manager: 可选的模型注册表管理器.
            computer_runtime: 可选的 computer 基础设施入口.
            reference_backend: 可选的 reference backend.
            config_control_plane: 可选的 runtime 配置控制面.
        """

        self.app = app
        self.run_manager = run_manager
        self.thread_manager = thread_manager
        self.memory_store = memory_store
        self.message_store = message_store
        self.channel_event_store = channel_event_store
        self.soul_source = soul_source
        self.sticky_notes_source = sticky_notes_source
        self.profile_registry = profile_registry
        self.plugin_manager = plugin_manager
        self.skill_catalog = skill_catalog
        self.subagent_executor_registry = subagent_executor_registry
        self.tool_broker = tool_broker
        self.model_registry_manager = model_registry_manager
        self.computer_runtime = computer_runtime
        self.reference_backend = reference_backend
        self.config_control_plane = config_control_plane
        self.log_buffer = log_buffer
        self.model_ops = RuntimeModelControlOps(
            model_registry_manager=model_registry_manager,
            profile_registry=profile_registry,
        )
        self.workspace_ops = RuntimeWorkspaceControlOps(
            run_manager=run_manager,
            thread_manager=thread_manager,
            computer_runtime=computer_runtime,
        )
        self.reference_ops = RuntimeReferenceControlOps(reference_backend=reference_backend)
        self.bot_shell_ops = BotShellControlOps(
            config_control_plane=config_control_plane,
            model_ops=self.model_ops,
            profile_registry=profile_registry,
        )
        self.session_shell_ops = SessionShellControlOps(
            config_control_plane=config_control_plane,
            model_ops=self.model_ops,
            profile_registry=profile_registry,
        )

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
                    delegate_agent_id=str(run.metadata.get("delegate_agent_id", "") or ""),
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

    async def get_gateway_status(self) -> GatewayStatusSnapshot:
        """读取当前 gateway 监听和连接状态."""

        gateway = getattr(self.app, "gateway", None)
        if gateway is None:
            return GatewayStatusSnapshot()
        host = str(getattr(gateway, "host", "") or "")
        port = int(getattr(gateway, "port", 0) or 0)
        return GatewayStatusSnapshot(
            gateway_type=type(gateway).__name__,
            connection_mode="reverse_ws_server",
            listen_host=host,
            listen_port=port,
            listen_url=f"ws://{host}:{port}" if host and port else "",
            server_running=bool(getattr(gateway, "_server", None)),
            connected=bool(getattr(gateway, "_ws", None)),
            self_id=str(getattr(gateway, "_self_id", "") or ""),
            supports_call_api=callable(getattr(gateway, "call_api", None)),
            token_configured=bool(str(getattr(gateway, "token", "") or "")),
        )

    async def switch_thread_agent(
        self,
        *,
        thread_id: str,
        agent_id: str,
    ) -> AgentSwitchSnapshot:
        """返回 thread agent override 已删除的提示.

        Args:
            thread_id: 目标 thread 标识.
            agent_id: 请求切换到的 agent 标识.

        Returns:
            AgentSwitchSnapshot: 固定返回不支持.
        """

        _ = agent_id
        return AgentSwitchSnapshot(
            ok=False,
            thread_id=thread_id,
            message="thread agent override removed; edit session config instead",
        )

    async def clear_thread_agent_override(self, *, thread_id: str) -> AgentSwitchSnapshot:
        """返回 thread agent override 已删除的提示.

        Args:
            thread_id: 目标 thread 标识.

        Returns:
            AgentSwitchSnapshot: 固定返回不支持.
        """

        return AgentSwitchSnapshot(
            ok=False,
            thread_id=thread_id,
            message="thread agent override removed; edit session config instead",
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

    async def approve_pending_approval(
        self,
        *,
        run_id: str,
        metadata: dict[str, object] | None = None,
    ):
        return await self.app.approve_pending_approval(run_id, metadata=metadata)

    async def reject_pending_approval(
        self,
        *,
        run_id: str,
        reason: str = "approval rejected",
        metadata: dict[str, object] | None = None,
    ):
        return await self.app.reject_pending_approval(
            run_id,
            reason=reason,
            metadata=metadata,
        )

    async def list_profiles(self) -> list[dict[str, object]]:
        if self.config_control_plane is None:
            return []
        return self.config_control_plane.list_profiles()

    async def get_profile(self, agent_id: str) -> dict[str, object] | None:
        if self.config_control_plane is None:
            return None
        return self.config_control_plane.get_profile(agent_id)

    async def upsert_profile(self, payload: dict[str, object]) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        return await self.config_control_plane.upsert_profile(payload)

    async def get_gateway_config(self) -> dict[str, object]:
        if self.config_control_plane is None:
            return {}
        return self.config_control_plane.get_gateway_config()

    async def upsert_gateway_config(self, payload: dict[str, object]) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        return await self.config_control_plane.upsert_gateway_config(payload)

    async def delete_profile(self, agent_id: str) -> bool:
        if self.config_control_plane is None:
            return False
        return await self.config_control_plane.delete_profile(agent_id)

    async def list_prompts(self) -> list[dict[str, object]]:
        if self.config_control_plane is None:
            return []
        return self.config_control_plane.list_prompts()

    async def get_prompt(self, prompt_ref: str) -> dict[str, object] | None:
        if self.config_control_plane is None:
            return None
        return self.config_control_plane.get_prompt(prompt_ref)

    async def upsert_prompt(self, *, prompt_ref: str, content: str) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        return await self.config_control_plane.upsert_prompt(prompt_ref, content)

    async def delete_prompt(self, prompt_ref: str) -> bool:
        if self.config_control_plane is None:
            return False
        references = await self.list_prompt_references(prompt_ref)
        if references:
            names = ", ".join(sorted(str(item["agent_id"]) for item in references))
            raise ValueError(f"prompt 仍被这些 profile 引用: {names}")
        return await self.config_control_plane.delete_prompt(prompt_ref)

    async def list_prompt_references(self, prompt_ref: str) -> list[dict[str, object]]:
        """列出仍在引用某个 prompt 的 profile 摘要."""

        normalized = str(prompt_ref or "").strip()
        if not normalized or self.config_control_plane is None:
            return []
        items: list[dict[str, object]] = []
        for profile in self.config_control_plane.list_profiles():
            if str(profile.get("prompt_ref", "") or "").strip() != normalized:
                continue
            items.append(
                {
                    "agent_id": str(profile.get("agent_id", "") or ""),
                    "name": str(profile.get("name", "") or ""),
                }
            )
        return items

    async def list_binding_rules(self) -> list[dict[str, object]]:
        if self.config_control_plane is None:
            return []
        return self.config_control_plane.list_binding_rules()

    async def get_binding_rule(self, rule_id: str) -> dict[str, object] | None:
        if self.config_control_plane is None:
            return None
        return self.config_control_plane.get_binding_rule(rule_id)

    async def upsert_binding_rule(self, payload: dict[str, object]) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        return await self.config_control_plane.upsert_binding_rule(payload)

    async def delete_binding_rule(self, rule_id: str) -> bool:
        if self.config_control_plane is None:
            return False
        return await self.config_control_plane.delete_binding_rule(rule_id)

    async def list_inbound_rules(self) -> list[dict[str, object]]:
        if self.config_control_plane is None:
            return []
        return self.config_control_plane.list_inbound_rules()

    async def get_inbound_rule(self, rule_id: str) -> dict[str, object] | None:
        if self.config_control_plane is None:
            return None
        return self.config_control_plane.get_inbound_rule(rule_id)

    async def upsert_inbound_rule(self, payload: dict[str, object]) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        return await self.config_control_plane.upsert_inbound_rule(payload)

    async def delete_inbound_rule(self, rule_id: str) -> bool:
        if self.config_control_plane is None:
            return False
        return await self.config_control_plane.delete_inbound_rule(rule_id)

    async def list_event_policies(self) -> list[dict[str, object]]:
        if self.config_control_plane is None:
            return []
        return self.config_control_plane.list_event_policies()

    async def get_event_policy(self, policy_id: str) -> dict[str, object] | None:
        if self.config_control_plane is None:
            return None
        return self.config_control_plane.get_event_policy(policy_id)

    async def upsert_event_policy(self, payload: dict[str, object]) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        return await self.config_control_plane.upsert_event_policy(payload)

    async def delete_event_policy(self, policy_id: str) -> bool:
        if self.config_control_plane is None:
            return False
        return await self.config_control_plane.delete_event_policy(policy_id)

    async def reload_runtime_configuration(self) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        result = await self.config_control_plane.reload_runtime_configuration()
        admins = await self.get_admins()
        self.app.backend_admin_actor_ids = {
            str(value)
            for value in list(admins.get("admin_actor_ids", []) or [])
            if str(value)
        }
        return result

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
            for item in self.skill_catalog.visible_skills(profile)
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

    async def list_available_tools(self) -> list[dict[str, object]]:
        """列出当前 runtime 已注册工具目录."""

        if self.tool_broker is None:
            return []
        return [dict(item) for item in self.tool_broker.list_registered_tools()]

    async def list_recent_logs(
        self,
        *,
        after_seq: int = 0,
        level: str = "",
        keyword: str = "",
        limit: int = 500,
    ) -> dict[str, object]:
        """返回最近日志, 供 WebUI 首页和系统日志页使用."""

        if self.log_buffer is None:
            return {"items": [], "next_seq": 0, "reset_required": False}
        return self.log_buffer.list_entries(
            after_seq=after_seq,
            level=level,
            keyword=keyword,
            limit=limit,
        )

    async def list_plugin_configs(self) -> dict[str, object]:
        """返回可供 WebUI 编辑的 plugin 配置列表."""

        if self.config_control_plane is None:
            return {"items": []}
        return {"items": self.config_control_plane.list_plugin_configs()}

    async def replace_plugin_configs(self, items: list[dict[str, object]]) -> dict[str, object]:
        """整批替换 plugin 配置并热刷新."""

        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        updated = await self.config_control_plane.replace_plugin_configs(list(items))
        return {"items": updated}

    async def list_soul_files(self) -> dict[str, object]:
        """返回 soul 文件列表."""

        if self.soul_source is None:
            raise RuntimeError("soul source unavailable")
        return {"items": self.soul_source.list_files()}

    async def get_soul_file(self, *, name: str) -> dict[str, object]:
        """读取一个 soul 文件.

        Args:
            name: 文件名.

        Returns:
            文件内容对象.
        """

        if self.soul_source is None:
            raise RuntimeError("soul source unavailable")
        return self.soul_source.read_file(name)

    async def put_soul_file(self, *, name: str, content: str) -> dict[str, object]:
        """写入一个 soul 文件.

        Args:
            name: 文件名.
            content: 新内容.

        Returns:
            写入后的文件对象.
        """

        if self.soul_source is None:
            raise RuntimeError("soul source unavailable")
        return self.soul_source.write_file(name, content)

    async def post_soul_file(self, *, name: str, content: str = "") -> dict[str, object]:
        """创建一个 soul 附加文件.

        Args:
            name: 文件名.
            content: 初始内容.

        Returns:
            新文件对象.
        """

        if self.soul_source is None:
            raise RuntimeError("soul source unavailable")
        return self.soul_source.create_file(name, content)

    async def list_self_files(self) -> dict[str, object]:
        """兼容旧接口: 返回 soul 文件列表."""

        return await self.list_soul_files()

    async def get_self_file(self, *, name: str) -> dict[str, object]:
        """兼容旧接口: 读取 soul 文件."""

        return await self.get_soul_file(name=name)

    async def put_self_file(self, *, name: str, content: str) -> dict[str, object]:
        """兼容旧接口: 写入 soul 文件."""

        return await self.put_soul_file(name=name, content=content)

    async def post_self_file(self, *, name: str, content: str = "") -> dict[str, object]:
        """兼容旧接口: 创建 soul 文件."""

        return await self.post_soul_file(name=name, content=content)

    async def list_sticky_note_scopes(self) -> dict[str, object]:
        """列出 sticky note 的 scope 列表."""

        if self.sticky_notes_source is None:
            raise RuntimeError("sticky notes source unavailable")
        return {"items": self.sticky_notes_source.list_scopes()}

    async def list_sticky_notes(self, *, scope: str, scope_key: str) -> dict[str, object]:
        """列出 sticky note 列表.

        Args:
            scope: scope 名称.
            scope_key: scope 键.

        Returns:
            note 列表.
        """

        if self.sticky_notes_source is None:
            raise RuntimeError("sticky notes source unavailable")
        return {
            "scope": scope,
            "scope_key": scope_key,
            "items": self.sticky_notes_source.list_notes(scope=scope, scope_key=scope_key),
        }

    async def get_sticky_note_item(self, *, scope: str, scope_key: str, key: str) -> dict[str, object]:
        """读取一个 sticky note 双区对象.

        Args:
            scope: scope 名称.
            scope_key: scope 键.
            key: note 键.

        Returns:
            sticky note 双区对象.
        """

        if self.sticky_notes_source is None:
            raise RuntimeError("sticky notes source unavailable")
        return self.sticky_notes_source.read_pair(
            scope=scope,
            scope_key=scope_key,
            key=key,
        )

    async def put_sticky_note_editable(
        self,
        *,
        scope: str,
        scope_key: str,
        key: str,
        content: str,
    ) -> dict[str, object]:
        """写入 sticky note 可编辑区."""

        if self.sticky_notes_source is None:
            raise RuntimeError("sticky notes source unavailable")
        return self.sticky_notes_source.write_editable(
            scope=scope,
            scope_key=scope_key,
            key=key,
            content=content,
        )

    async def put_sticky_note_readonly(
        self,
        *,
        scope: str,
        scope_key: str,
        key: str,
        content: str,
    ) -> dict[str, object]:
        """写入 sticky note 只读区."""

        if self.sticky_notes_source is None:
            raise RuntimeError("sticky notes source unavailable")
        return self.sticky_notes_source.write_readonly(
            scope=scope,
            scope_key=scope_key,
            key=key,
            content=content,
        )

    async def create_sticky_note(
        self,
        *,
        scope: str,
        scope_key: str,
        key: str,
    ) -> dict[str, object]:
        """创建 sticky note.

        Args:
            scope: scope 名称.
            scope_key: scope 键.
            key: note 键.

        Returns:
            新建后的 sticky note 双区对象.
        """

        if self.sticky_notes_source is None:
            raise RuntimeError("sticky notes source unavailable")
        return self.sticky_notes_source.create_note(
            scope=scope,
            scope_key=scope_key,
            key=key,
        )

    async def get_bot(self) -> dict[str, object]:
        """返回默认 Bot 的产品壳对象.

        Returns:
            默认 Bot 的产品字段对象.
        """

        return await self.bot_shell_ops.get_bot()

    async def get_admins(self) -> dict[str, object]:
        """返回共享管理员设置.

        Returns:
            只包含共享管理员列表的设置对象.
        """

        bot = await self.bot_shell_ops.get_bot()
        return {
            "admin_actor_ids": [
                str(value)
                for value in list(bot.get("admin_actor_ids", []) or [])
                if str(value)
            ]
        }

    async def put_bot(self, *, payload: dict[str, object]) -> dict[str, object]:
        """保存默认 Bot 的产品壳对象.

        Args:
            payload: 前端提交的 Bot 设置.

        Returns:
            保存后的默认 Bot 对象.
        """

        saved = await self.bot_shell_ops.upsert_bot(payload=dict(payload))
        self.app.backend_admin_actor_ids = {
            str(value)
            for value in list(saved.get("admin_actor_ids", []) or [])
            if str(value)
        }
        return saved

    async def put_admins(self, *, payload: dict[str, object]) -> dict[str, object]:
        """保存共享管理员设置.

        Args:
            payload: 前端提交的管理员设置.

        Returns:
            保存后的管理员设置对象.
        """

        saved = await self.bot_shell_ops.upsert_admins(
            [
                str(value)
                for value in list(payload.get("admin_actor_ids", []) or [])
                if str(value)
            ]
        )
        admin_actor_ids = {str(value) for value in saved if str(value)}
        self.app.backend_admin_actor_ids = admin_actor_ids
        return {
            "admin_actor_ids": [str(value) for value in saved if str(value)],
        }

    async def list_sessions(self) -> dict[str, object]:
        """返回 session shell 已下线的提示.

        Returns:
            dict[str, object]: 固定抛错, 提示 session shell 正在重设计.
        """

        raise NotImplementedError("session shell redesign pending; legacy /api/sessions removed")

    async def get_session(self, *, channel_scope: str) -> dict[str, object] | None:
        """返回 session shell 已下线的提示.

        Args:
            channel_scope: Session 对应的 channel scope.

        Returns:
            dict[str, object] | None: 固定抛错.
        """

        _ = channel_scope
        raise NotImplementedError("session shell redesign pending; legacy /api/sessions removed")

    async def put_session(self, *, channel_scope: str, payload: dict[str, object]) -> dict[str, object]:
        """返回 session shell 已下线的提示.

        Args:
            channel_scope: Session 对应的 channel scope.
            payload: 前端提交的数据.

        Returns:
            dict[str, object]: 固定抛错.
        """

        _ = channel_scope, payload
        raise NotImplementedError("session shell redesign pending; legacy /api/sessions removed")

    async def get_backend_status(self) -> BackendStatusSnapshot:
        """返回后台维护面的最小状态快照."""

        app = self.app
        session_service = getattr(app.backend_bridge, "session", None) if app.backend_bridge is not None else None
        binding = None
        session_path = ""
        if session_service is not None:
            load_binding = getattr(session_service, "load_binding", None)
            if callable(load_binding):
                loaded = load_binding()
                if loaded is not None:
                    binding = asdict(loaded)
            get_binding_path = getattr(session_service, "get_binding_path", None)
            if callable(get_binding_path):
                session_path = str(get_binding_path() or "")
        active_modes = []
        if app.backend_mode_registry is not None:
            active_modes = list(app.backend_mode_registry.list_active_modes())
        return BackendStatusSnapshot(
            configured=bool(
                session_service is not None
                and callable(getattr(session_service, "is_configured", None))
                and session_service.is_configured()
            ),
            admin_actor_ids=sorted(app.backend_admin_actor_ids),
            session_binding=binding,
            session_path=session_path,
            active_modes=active_modes,
        )

    async def get_backend_session_binding(self) -> dict[str, object] | None:
        """返回当前 canonical backend session binding."""

        status = await self.get_backend_status()
        return status.session_binding

    async def get_backend_session_path(self) -> str:
        """返回 backend session binding 文件路径."""

        status = await self.get_backend_status()
        return status.session_path

    async def get_ui_catalog(self) -> dict[str, object]:
        """返回 WebUI 表单所需的选择项元数据."""

        prompts = await self.list_prompts()
        profiles = await self.list_profiles()
        default_agent_id = ""
        if self.profile_registry is not None:
            default_agent_id = str(getattr(self.profile_registry, "default_agent_id", "") or "")
        if not default_agent_id and profiles:
            default_agent_id = str(profiles[0].get("agent_id", "") or "")
        bot_profile = next((item for item in profiles if item.get("agent_id") == default_agent_id), None)
        skills = await self.list_skills()
        executors = await self.list_subagent_executors()
        providers = await self.list_model_providers()
        presets = await self.list_model_presets()
        bindings = await self.list_model_bindings()
        return {
            "bot": {
                "agent_id": default_agent_id,
                "name": bot_profile.get("name", default_agent_id) if bot_profile is not None else default_agent_id,
            },
            "agents": [
                {
                    "agent_id": item["agent_id"],
                    "name": item.get("name", item["agent_id"]),
                }
                for item in profiles
            ],
            "prompts": [
                {
                    "prompt_ref": item.get("prompt_ref", ""),
                    "prompt_name": str(item.get("prompt_ref", "")).removeprefix("prompt/"),
                    "source": item.get("source", ""),
                }
                for item in prompts
            ],
            "tools": await self.list_available_tools(),
            "skills": [asdict(item) for item in skills],
            "subagent_executors": [asdict(item) for item in executors],
            "model_providers": [
                {
                    "provider_id": item.provider_id,
                    "name": item.name or item.provider_id,
                    "kind": item.kind,
                }
                for item in providers
            ],
            "model_presets": [
                {
                    "preset_id": item.preset_id,
                    "provider_id": item.provider_id,
                    "model": item.model,
                }
                for item in presets
            ],
            "model_bindings": [item.to_dict() for item in bindings],
            "options": build_ui_options(
                api_key_env_names=[key for key in os.environ if key.endswith("_API_KEY")]
            ),
        }

    async def list_threads(self, *, limit: int = 100):
        if self.thread_manager is None:
            return []
        return await self.thread_manager.list_threads(limit=limit)

    async def get_thread(self, thread_id: str):
        if self.thread_manager is None:
            return None
        return await self.thread_manager.get(thread_id)

    async def list_runs(
        self,
        *,
        limit: int = 100,
        statuses: list[str] | None = None,
        thread_id: str | None = None,
    ) -> list[RunRecord]:
        status_set = {str(item) for item in list(statuses or []) if str(item).strip()}
        return await self.run_manager.list_runs(
            limit=limit,
            statuses=status_set or None,
            thread_id=thread_id,
        )

    async def get_run(self, run_id: str) -> RunRecord | None:
        return await self.run_manager.get(run_id)

    async def list_run_steps(
        self,
        *,
        run_id: str,
        limit: int = 100,
        step_types: list[str] | None = None,
    ):
        return await self.run_manager.list_steps(
            run_id,
            limit=limit,
            step_types=step_types,
        )

    async def list_thread_events(
        self,
        *,
        thread_id: str,
        limit: int = 100,
        since: int | None = None,
        event_types: list[str] | None = None,
    ) -> list[ChannelEventRecord]:
        if self.channel_event_store is None:
            return []
        return await self.channel_event_store.get_thread_events(
            thread_id,
            limit=limit,
            since=since,
            event_types=event_types,
        )

    async def list_thread_messages(
        self,
        *,
        thread_id: str,
        limit: int = 100,
        since: int | None = None,
    ) -> list[MessageRecord]:
        if self.message_store is None:
            return []
        return await self.message_store.get_thread_messages(
            thread_id,
            limit=limit,
            since=since,
        )

    async def list_model_providers(self) -> list[ModelProvider]:
        return await self.model_ops.list_model_providers()

    async def list_model_presets(self) -> list[ModelPreset]:
        return await self.model_ops.list_model_presets()

    async def list_model_bindings(self) -> list[ModelBinding]:
        return await self.model_ops.list_model_bindings()

    async def get_model_provider(self, provider_id: str) -> ModelProvider | None:
        return await self.model_ops.get_model_provider(provider_id)

    async def get_model_preset(self, preset_id: str) -> ModelPreset | None:
        return await self.model_ops.get_model_preset(preset_id)

    async def get_model_binding(self, binding_id: str) -> ModelBinding | None:
        return await self.model_ops.get_model_binding(binding_id)

    async def get_model_provider_impact(self, provider_id: str) -> ModelImpactSnapshot:
        return await self.model_ops.get_model_provider_impact(provider_id)

    async def get_model_preset_impact(self, preset_id: str) -> ModelImpactSnapshot:
        return await self.model_ops.get_model_preset_impact(preset_id)

    async def get_model_binding_impact(self, binding_id: str) -> ModelImpactSnapshot:
        return await self.model_ops.get_model_binding_impact(binding_id)

    async def preview_effective_agent_model(self, agent_id: str) -> EffectiveModelSnapshot:
        return await self.model_ops.preview_effective_agent_model(agent_id)

    async def preview_effective_summary_model(self) -> EffectiveModelSnapshot:
        return await self.model_ops.preview_effective_summary_model()

    async def upsert_model_provider(self, provider: ModelProvider) -> ModelMutationResult:
        return await self.model_ops.upsert_model_provider(provider)

    async def upsert_model_preset(self, preset: ModelPreset) -> ModelMutationResult:
        return await self.model_ops.upsert_model_preset(preset)

    async def upsert_model_binding(self, binding: ModelBinding) -> ModelMutationResult:
        return await self.model_ops.upsert_model_binding(binding)

    async def delete_model_provider(
        self,
        provider_id: str,
        *,
        force: bool = False,
    ) -> ModelMutationResult:
        return await self.model_ops.delete_model_provider(provider_id, force=force)

    async def delete_model_preset(
        self,
        preset_id: str,
        *,
        force: bool = False,
    ) -> ModelMutationResult:
        return await self.model_ops.delete_model_preset(preset_id, force=force)

    async def delete_model_binding(self, binding_id: str) -> ModelMutationResult:
        return await self.model_ops.delete_model_binding(binding_id)

    async def health_check_model_preset(self, preset_id: str) -> ModelHealthCheckResult:
        return await self.model_ops.health_check_model_preset(preset_id)

    async def reload_models(self) -> ModelReloadSnapshot:
        return await self.model_ops.reload_models()

    async def get_model_registry_status(self) -> ModelRegistryStatusSnapshot:
        return await self.model_ops.get_model_registry_status()

    async def list_workspaces(self) -> list[WorkspaceState]:
        return await self.workspace_ops.list_workspaces()

    async def list_workspace_entries(
        self,
        *,
        thread_id: str,
        relative_path: str = "/",
    ) -> list[WorkspaceFileEntry]:
        return await self.workspace_ops.list_workspace_entries(
            thread_id=thread_id,
            relative_path=relative_path,
        )

    async def read_workspace_file(
        self,
        *,
        thread_id: str,
        relative_path: str,
    ) -> str:
        return await self.workspace_ops.read_workspace_file(
            thread_id=thread_id,
            relative_path=relative_path,
        )

    async def list_workspace_sessions(self, *, thread_id: str) -> list[str]:
        return await self.workspace_ops.list_workspace_sessions(thread_id=thread_id)

    async def list_workspace_attachments(self, *, thread_id: str) -> list[WorkspaceFileEntry]:
        return await self.workspace_ops.list_workspace_attachments(thread_id=thread_id)

    async def get_sandbox_status(self, *, thread_id: str) -> WorkspaceSandboxStatus:
        return await self.workspace_ops.get_sandbox_status(thread_id=thread_id)

    async def list_mirrored_skills(self, *, thread_id: str) -> list[str]:
        return await self.workspace_ops.list_mirrored_skills(thread_id=thread_id)

    async def list_reference_spaces(
        self,
        *,
        tenant_id: str | None = None,
        mode: ReferenceMode | None = None,
    ) -> list[ReferenceSpace]:
        return await self.reference_ops.list_reference_spaces(tenant_id=tenant_id, mode=mode)

    async def search_reference(
        self,
        *,
        query: str,
        tenant_id: str,
        space_id: str | None = None,
        mode: ReferenceMode | None = None,
        limit: int = 10,
        body: ReferenceBodyLevel = "none",
        min_score: float = 0.0,
    ) -> list[ReferenceHit]:
        return await self.reference_ops.search_reference(
            query=query,
            tenant_id=tenant_id,
            space_id=space_id,
            mode=mode,
            limit=limit,
            body=body,
            min_score=min_score,
        )

    async def get_reference_document(
        self,
        *,
        ref_id: str,
        tenant_id: str,
        body: ReferenceBodyLevel = "full",
    ) -> ReferenceDocument | None:
        return await self.reference_ops.get_reference_document(
            ref_id=ref_id,
            tenant_id=tenant_id,
            body=body,
        )

    async def add_reference_documents(
        self,
        *,
        tenant_id: str,
        space_id: str,
        mode: ReferenceMode,
        documents: list[ReferenceDocumentInput],
    ) -> list[ReferenceDocumentRef]:
        return await self.reference_ops.add_reference_documents(
            tenant_id=tenant_id,
            space_id=space_id,
            mode=mode,
            documents=documents,
        )

    async def list_workspace_activity(
        self,
        *,
        thread_id: str,
        limit: int = 50,
        step_types: list[str] | None = None,
    ):
        return await self.workspace_ops.list_workspace_activity(
            thread_id=thread_id,
            limit=limit,
            step_types=step_types,
        )


    async def prune_workspace(self, *, thread_id: str, force: bool = False) -> AgentSwitchSnapshot:
        return await self.workspace_ops.prune_workspace(thread_id=thread_id, force=force)

    async def stop_workspace_sandbox(self, *, thread_id: str, force: bool = False) -> AgentSwitchSnapshot:
        return await self.workspace_ops.stop_workspace_sandbox(thread_id=thread_id, force=force)

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
        item: SkillPackageManifest,
    ) -> AgentSkillSnapshot:
        """把 SkillPackageManifest 转成 AgentSkillSnapshot.

        Args:
            agent_id: 当前 agent 标识.
            item: 当前 skill manifest.

        Returns:
            对应的 AgentSkillSnapshot.
        """

        return AgentSkillSnapshot(
            agent_id=agent_id,
            skill_name=item.skill_name,
            display_name=item.display_name,
            description=item.description,
            has_references=item.has_references,
            has_scripts=item.has_scripts,
            has_assets=item.has_assets,
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
