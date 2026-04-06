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
import uuid
from acabot.types import Action, ActionType, MsgSegment, StandardEvent

from ..app import RuntimeApp
from ..computer import (
    ComputerRuntime,
    WorkspaceFileEntry,
    WorkspaceSandboxStatus,
    WorkspaceState,
)
from .config_control_plane import RuntimeConfigControlPlane
from .extension_refresh import ExtensionRefreshService
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
from ..contracts import ChannelEventRecord, MessageRecord, OutboxItem, PlannedAction, RunRecord
from ..notification_send_context import prepare_notification_run_context
from ..send_intent import normalize_send_intent_payload, normalize_target, optional_text
from ..plugin_reconciler import PluginReconciler
from ..plugin_runtime_host import PluginRuntimeHost
from ..plugin_package import PackageCatalog
from ..plugin_spec import PluginSpec, SpecStore
from ..plugin_status import PluginStatus, StatusStore
from ..storage.runs import RunManager
from ..skills import SkillPackageManifest
from ..skills import SkillCatalog
from ..storage.stores import ChannelEventStore, MessageStore
from ..memory.file_backed.sticky_notes import StickyNoteRecord
from ..subagents import SubagentCatalog, SubagentPackageManifest
from ..soul import SoulSource
from ..memory.file_backed import StickyNoteFileStore
from ..memory.sticky_note_entities import normalize_sticky_note_entity_kind
from ..memory.sticky_notes import StickyNoteService
from ..storage.threads import ThreadManager
from ..tool_broker import ToolBroker
from ..ids import build_event_source_from_conversation_id, build_thread_id_from_conversation_id
from ..scheduler.service import ScheduledTaskService, ScheduledTaskUnavailableError
from .model_ops import RuntimeModelControlOps
from .snapshots import (
    ActiveRunSnapshot,
    AgentSkillSnapshot,
    AgentSwitchSnapshot,
    BackendStatusSnapshot,
    GatewayStatusSnapshot,
    RuntimeStatusSnapshot,
    SkillSnapshot,
    SubagentSnapshot,
)
from .ui_catalog import build_ui_options
from .log_buffer import InMemoryLogBuffer
from .workspace_ops import RuntimeWorkspaceControlOps
from .log_setup import sanitize_inspection_value


# region control plane
class RuntimeControlPlane:
    """runtime 的最小本地 control plane.

    当前暴露:
    - `get_status`
    - `reload_plugins`
    - `show_memory`

    后续 `/status`, `/reload_plugin`, WebUI 都应优先通过这层进入 runtime.
    """

    def __init__(
        self,
        *,
        app: RuntimeApp,
        run_manager: RunManager,
        thread_manager: ThreadManager | None = None,
        message_store: MessageStore | None = None,
        channel_event_store: ChannelEventStore | None = None,
        soul_source: SoulSource | None = None,
        sticky_notes_source: StickyNoteFileStore | None = None,
        sticky_notes: StickyNoteService | None = None,
        plugin_reconciler: PluginReconciler | None = None,
        plugin_runtime_host: PluginRuntimeHost | None = None,
        plugin_catalog: PackageCatalog | None = None,
        plugin_spec_store: SpecStore | None = None,
        plugin_status_store: StatusStore | None = None,
        skill_catalog: SkillCatalog | None = None,
        subagent_catalog: SubagentCatalog | None = None,
        tool_broker: ToolBroker | None = None,
        model_registry_manager: FileSystemModelRegistryManager | None = None,
        computer_runtime: ComputerRuntime | None = None,
        config_control_plane: RuntimeConfigControlPlane | None = None,
        extension_refresh_service: ExtensionRefreshService | None = None,
        log_buffer: InMemoryLogBuffer | None = None,
        ltm_store: object | None = None,
        scheduled_task_service: ScheduledTaskService | None = None,
    ) -> None:
        """初始化 RuntimeControlPlane.

        Args:
            app: 当前 runtime app.
            run_manager: run 生命周期管理器.
            thread_manager: 可选的 thread 状态管理器.
            message_store: 可选的 delivered message store.
            channel_event_store: 可选的 inbound event store.
            soul_source: 可选的 soul 文件真源服务.
            sticky_notes_source: 可选的 sticky note 文件真源服务.
            sticky_notes: 可选的 sticky note 服务层.
            plugin_reconciler: 可选的 plugin reconciler.
            plugin_runtime_host: 可选的 plugin runtime host.
            plugin_catalog: 可选的 plugin catalog.
            plugin_spec_store: 可选的 plugin spec store.
            plugin_status_store: 可选的 plugin status store.
            skill_catalog: 可选的统一 skill catalog.
            subagent_catalog: 可选的 subagent catalog.
            tool_broker: 可选的 tool broker, 用于给 WebUI 提供工具目录.
            model_registry_manager: 可选的模型注册表管理器.
            computer_runtime: 可选的 computer 基础设施入口.
            config_control_plane: 可选的 runtime 配置控制面.
            extension_refresh_service: 可选的扩展刷新服务.
            ltm_store: 可选的 LTM 存储实例 (LanceDbLongTermMemoryStore).
        """

        self.app = app
        self.run_manager = run_manager
        self.thread_manager = thread_manager
        self.message_store = message_store
        self.channel_event_store = channel_event_store
        self.soul_source = soul_source
        self.sticky_notes_source = sticky_notes_source
        self.sticky_notes = sticky_notes
        self.plugin_reconciler = plugin_reconciler
        self.plugin_runtime_host = plugin_runtime_host
        self.plugin_catalog = plugin_catalog
        self.plugin_spec_store = plugin_spec_store
        self.plugin_status_store = plugin_status_store
        self.skill_catalog = skill_catalog
        self.subagent_catalog = subagent_catalog
        self.tool_broker = tool_broker
        self.model_registry_manager = model_registry_manager
        self.computer_runtime = computer_runtime
        self.config_control_plane = config_control_plane
        self.extension_refresh_service = extension_refresh_service
        self.log_buffer = log_buffer
        self.ltm_store = ltm_store
        self.scheduled_task_service = scheduled_task_service
        self.model_ops = RuntimeModelControlOps(
            model_registry_manager=model_registry_manager,
        )
        self.workspace_ops = RuntimeWorkspaceControlOps(
            run_manager=run_manager,
            thread_manager=thread_manager,
            computer_runtime=computer_runtime,
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

    async def list_sessions(self) -> list[dict[str, object]]:
        if self.config_control_plane is None:
            return []
        return self.config_control_plane.list_sessions()

    async def create_session(self, payload: dict[str, object]) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        return await self.config_control_plane.create_session(payload)

    def _require_scheduled_task_service(self) -> ScheduledTaskService:
        service = self.scheduled_task_service
        if service is None:
            raise ScheduledTaskUnavailableError("scheduler service unavailable")
        return service

    async def list_conversation_wakeup_schedules(
        self,
        *,
        conversation_id: str = "",
        enabled: bool | None = None,
        limit: int = 200,
    ) -> dict[str, object]:
        service = self._require_scheduled_task_service()
        tasks = service.list_conversation_wakeup_tasks(
            conversation_id=conversation_id or None,
            enabled=enabled,
            limit=max(1, min(limit, 500)),
        )
        return {"items": [service.serialize_task(task) for task in tasks]}

    async def create_conversation_wakeup_schedule(self, payload: dict[str, object]) -> dict[str, object]:
        service = self._require_scheduled_task_service()
        conversation_id = str(payload.get("conversation_id", "") or "").strip()
        note = str(payload.get("note", "") or "")
        if not conversation_id:
            raise ValueError("conversation_id is required")
        if len(note) > 500:
            raise ValueError("note must be at most 500 characters")
        schedule_payload = payload.get("schedule")
        if not isinstance(schedule_payload, dict):
            raise ValueError("schedule is required")
        schedule_kind = str(schedule_payload.get("kind", "") or "").strip()
        schedule_spec = schedule_payload.get("spec")
        if schedule_kind == "one_shot" and isinstance(schedule_spec, dict):
            fire_at = schedule_spec.get("fire_at")
            try:
                resolved_fire_at = float(fire_at)
            except (TypeError, ValueError):
                resolved_fire_at = None
            if resolved_fire_at is not None and resolved_fire_at <= time.time():
                raise ValueError("one_shot fire_at must be in the future")
        task = await service.create_conversation_wakeup_task(
            owner=conversation_id,
            conversation_id=conversation_id,
            schedule_payload=schedule_payload,
            note=note,
            created_by="webui",
            source="webui:schedules",
        )
        return service.serialize_task(task)

    async def enable_conversation_wakeup_schedule(self, task_id: str) -> dict[str, object]:
        service = self._require_scheduled_task_service()
        task = await service.enable_conversation_wakeup_task(task_id)
        return service.serialize_task(task)

    async def disable_conversation_wakeup_schedule(self, task_id: str) -> dict[str, object]:
        service = self._require_scheduled_task_service()
        task = await service.disable_conversation_wakeup_task(task_id)
        return service.serialize_task(task)

    async def delete_conversation_wakeup_schedule(self, task_id: str) -> dict[str, object]:
        service = self._require_scheduled_task_service()
        deleted = await service.delete_conversation_wakeup_task(task_id)
        if not deleted:
            raise KeyError(task_id)
        return {"task_id": task_id, "deleted": True}

    async def get_session(self, session_id: str) -> dict[str, object] | None:
        if self.config_control_plane is None:
            return None
        return self.config_control_plane.get_session_bundle(session_id)

    async def update_session(self, session_id: str, payload: dict[str, object]) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        return await self.config_control_plane.update_session(session_id, payload)

    async def get_session_agent(self, session_id: str) -> dict[str, object] | None:
        if self.config_control_plane is None:
            return None
        bundle = self.config_control_plane.get_session_bundle(session_id)
        if bundle is None:
            return None
        return dict(bundle["agent"])

    async def update_session_agent(self, session_id: str, payload: dict[str, object]) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        return await self.config_control_plane.update_session_agent(session_id, payload)

    async def get_render_config(self) -> dict[str, object]:
        if self.config_control_plane is None:
            return {}
        return self.config_control_plane.get_render_config()

    async def upsert_render_config(self, payload: dict[str, object]) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        return await self.config_control_plane.upsert_render_config(payload)

    async def get_gateway_config(self) -> dict[str, object]:
        if self.config_control_plane is None:
            return {}
        return self.config_control_plane.get_gateway_config()

    async def upsert_gateway_config(self, payload: dict[str, object]) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        return await self.config_control_plane.upsert_gateway_config(payload)

    async def get_filesystem_scan_config(self) -> dict[str, object]:
        if self.config_control_plane is None:
            return {}
        return self.config_control_plane.get_filesystem_scan_config()

    async def upsert_filesystem_scan_config(self, payload: dict[str, object]) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        return await self.config_control_plane.upsert_filesystem_scan_config(payload)

    async def get_system_configuration_view(self) -> dict[str, object]:
        """返回系统页所需的统一系统配置快照."""

        if self.config_control_plane is None:
            return {
                "meta": {},
                "gateway": {},
                "render": {},
                "filesystem": {},
                "admins": await self.get_admins(),
                "paths": {},
            }
        path_overview = self.config_control_plane.get_runtime_path_overview()
        return {
            "meta": {
                "config_path": str(path_overview.get("config_path", "") or ""),
            },
            "gateway": self.config_control_plane.get_gateway_config(),
            "render": self.config_control_plane.get_render_config(),
            "filesystem": self.config_control_plane.get_filesystem_scan_config(),
            "admins": await self.get_admins(),
            "paths": path_overview,
        }

    async def get_long_term_memory_config(self) -> dict[str, object]:
        if self.config_control_plane is None:
            return {}
        return self.config_control_plane.get_long_term_memory_config()

    async def upsert_long_term_memory_config(self, payload: dict[str, object]) -> dict[str, object]:
        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        return await self.config_control_plane.upsert_long_term_memory_config(payload)

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
            names = ", ".join(sorted(str(item["session_id"]) for item in references))
            raise ValueError(f"prompt 仍被这些 session agents 引用: {names}")
        return await self.config_control_plane.delete_prompt(prompt_ref)

    async def list_prompt_references(self, prompt_ref: str) -> list[dict[str, object]]:
        """列出仍在引用某个 prompt 的 session-owned agent 摘要."""

        normalized = str(prompt_ref or "").strip()
        if not normalized or self.config_control_plane is None:
            return []
        items: list[dict[str, object]] = []
        for bundle in self.config_control_plane.list_session_bundles():
            agent = dict(bundle.get("agent", {}) or {})
            if str(agent.get("prompt_ref", "") or "").strip() != normalized:
                continue
            items.append(
                {
                    "session_id": str(bundle.get("session", {}).get("session_id", "") or ""),
                    "agent_id": str(agent.get("agent_id", "") or ""),
                }
            )
        return items

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
        self.app.router.session_runtime.set_shared_admin_actor_ids(self.app.backend_admin_actor_ids)
        return result

    async def refresh_extensions(self, *, kind: str, session_id: str) -> dict[str, object]:
        """执行窄范围的运行时扩展刷新。"""

        normalized_kind = str(kind or "").strip()
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("session_id is required")
        if normalized_kind != "skills":
            raise ValueError(f"unsupported extension refresh kind: {normalized_kind!r}")
        if self.extension_refresh_service is None:
            raise RuntimeError("extension refresh service unavailable")
        result = await self.extension_refresh_service.refresh_skills(session_id=normalized_session_id)
        return dict(result)

    async def install_skill_zip(self, *, filename: str, content: bytes) -> dict[str, object]:
        """安装一份上传的 skill zip 包。"""

        if self.extension_refresh_service is None:
            raise RuntimeError("extension refresh service unavailable")
        result = await self.extension_refresh_service.install_skill_zip(
            filename=filename,
            content=content,
        )
        return dict(result)

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

        if self.config_control_plane is None or self.skill_catalog is None:
            return []
        agent = self.config_control_plane.find_session_agent(agent_id)
        if agent is None:
            return []
        return [
            self._to_agent_skill_snapshot(agent_id, item)
            for item in self.skill_catalog.visible_skills(agent)
        ]

    async def list_subagents(self) -> list[SubagentSnapshot]:
        """列出当前 catalog subagents.

        Returns:
            SubagentSnapshot 列表.
        """

        if self.subagent_catalog is None:
            return []
        effective_ids: dict[str, str] = {}
        for item in self.subagent_catalog.list_all():
            winner = self.subagent_catalog.get(item.subagent_name)
            if winner is None:
                continue
            effective_ids[item.subagent_name] = winner.subagent_id
        return [
            self._to_subagent_snapshot(
                item,
                effective=effective_ids.get(item.subagent_name) == item.subagent_id,
            )
            for item in self.subagent_catalog.list_all()
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
        """创建 soul 文件."""

        return await self.post_soul_file(name=name, content=content)

    async def list_sticky_notes(self, *, entity_kind: str) -> dict[str, object]:
        """按实体分类列出 sticky note 记录.

        Args:
            entity_kind: 目标实体分类, 只能是 `user` 或 `conversation`.

        Returns:
            dict[str, object]: 当前分类下的列表结果.
        """

        normalized_entity_kind = normalize_sticky_note_entity_kind(entity_kind)
        service = self._require_sticky_notes()
        records = await service.list_records(entity_kind=normalized_entity_kind)
        return {
            "entity_kind": normalized_entity_kind,
            "items": [
                {
                    "entity_ref": record.entity_ref,
                    "updated_at": record.updated_at,
                }
                for record in records
            ],
        }

    async def get_sticky_note_record(self, *, entity_ref: str) -> dict[str, object] | None:
        """读取一张完整的 sticky note record.

        Args:
            entity_ref: 目标实体引用.

        Returns:
            dict[str, object] | None: 命中的记录. 不存在时返回 `None`.
        """

        service = self._require_sticky_notes()
        record = await service.load_record(entity_ref)
        if record is None:
            return None
        return self._sticky_note_record_payload(record)

    async def save_sticky_note_record(
        self,
        *,
        entity_ref: str,
        readonly: str,
        editable: str,
    ) -> dict[str, object]:
        """保存一张完整的 sticky note record.

        Args:
            entity_ref: 目标实体引用.
            readonly: 高可信内容.
            editable: 可编辑观察内容.

        Returns:
            dict[str, object]: 保存后的记录对象.
        """

        service = self._require_sticky_notes()
        record = await service.save_record(
            StickyNoteRecord(
                entity_ref=entity_ref,
                readonly=readonly,
                editable=editable,
            )
        )
        return self._sticky_note_record_payload(record)

    async def create_sticky_note(self, *, entity_ref: str) -> dict[str, object]:
        """创建一张空的 sticky note record.

        Args:
            entity_ref: 目标实体引用.

        Returns:
            dict[str, object]: 新建后的记录对象.
        """

        service = self._require_sticky_notes()
        record = await service.create_record(entity_ref)
        return self._sticky_note_record_payload(record)

    async def delete_sticky_note(self, *, entity_ref: str) -> bool:
        """删除一张 sticky note record.

        Args:
            entity_ref: 目标实体引用.

        Returns:
            bool: 目标存在并已删除时返回 `True`.
        """

        service = self._require_sticky_notes()
        return await service.delete_record(entity_ref)

    def _require_sticky_notes(self) -> StickyNoteService:
        """返回当前必需的 sticky note 服务层.

        Returns:
            StickyNoteService: 当前 sticky note 服务层.

        Raises:
            RuntimeError: sticky note 服务层不可用时抛错.
        """

        if self.sticky_notes is None:
            raise RuntimeError("sticky notes service unavailable")
        return self.sticky_notes

    @staticmethod
    def _sticky_note_record_payload(record: StickyNoteRecord) -> dict[str, object]:
        """把 `StickyNoteRecord` 转成 control plane 返回对象.

        Args:
            record: 待序列化的 sticky note record.

        Returns:
            dict[str, object]: 对应的返回对象.
        """

        return {
            "entity_ref": record.entity_ref,
            "readonly": record.readonly,
            "editable": record.editable,
            "updated_at": record.updated_at,
        }

    async def get_bot(self) -> dict[str, object]:
        """返回 bot shell 已下线的提示.

        Returns:
            dict[str, object]: 固定抛错, 提示 bot shell 正在重设计.
        """

        raise NotImplementedError("bot shell redesign pending; legacy /api/bot removed")

    async def get_admins(self) -> dict[str, object]:
        """返回共享管理员设置.

        Returns:
            只包含共享管理员列表的设置对象.
        """

        if self.config_control_plane is None:
            return {"admin_actor_ids": sorted(self.app.backend_admin_actor_ids)}
        runtime_conf = dict(self.config_control_plane.config.get("runtime", {}) or {})
        backend_conf = dict(runtime_conf.get("backend", {}) or {})
        configured = [
            str(value)
            for value in list(backend_conf.get("admin_actor_ids", []) or [])
            if str(value)
        ]
        if configured:
            return {"admin_actor_ids": configured}
        return {"admin_actor_ids": sorted(self.app.backend_admin_actor_ids)}

    async def put_bot(self, *, payload: dict[str, object]) -> dict[str, object]:
        """返回 bot shell 已下线的提示.

        Args:
            payload: 前端提交的 Bot 设置.

        Returns:
            dict[str, object]: 固定抛错.
        """

        _ = payload
        raise NotImplementedError("bot shell redesign pending; legacy /api/bot removed")

    async def put_admins(self, *, payload: dict[str, object]) -> dict[str, object]:
        """保存共享管理员设置.

        Args:
            payload: 前端提交的管理员设置.

        Returns:
            保存后的管理员设置对象.
        """

        if self.config_control_plane is None:
            raise RuntimeError("config control plane unavailable")
        admin_actor_ids = [
            str(value)
            for value in list(payload.get("admin_actor_ids", []) or [])
            if str(value)
        ]
        data = self.config_control_plane.config.to_dict()
        runtime_conf = dict(data.get("runtime", {}) or {})
        backend_conf = dict(runtime_conf.get("backend", {}) or {})
        backend_conf["admin_actor_ids"] = admin_actor_ids
        runtime_conf["backend"] = backend_conf
        data["runtime"] = runtime_conf
        self.config_control_plane.config.replace(data)
        self.config_control_plane.config.save()
        self.app.backend_admin_actor_ids = set(admin_actor_ids)
        self.app.router.session_runtime.set_shared_admin_actor_ids(self.app.backend_admin_actor_ids)
        return self.config_control_plane.with_apply_result(
            {
                "admin_actor_ids": list(admin_actor_ids),
            },
            apply_status="applied",
            restart_required=False,
            message="已保存并已生效",
        )

    async def inject_synthetic_event(self, *, payload: dict[str, object]) -> dict[str, object]:
        """向真实 runtime 注入一条 synthetic inbound event, 便于端到端回归测试."""

        conversation_id = str(payload.get("conversation_id", "") or "").strip()
        if not conversation_id:
            raise ValueError("conversation_id is required")
        conversation_id = normalize_target(conversation_id) or conversation_id
        text = optional_text(payload.get("text"))
        segments = self._normalize_synthetic_segments(payload.get("segments"), fallback_text=text)
        if not segments:
            raise ValueError("synthetic event requires text or segments")

        sender_user_id = str(payload.get("sender_user_id", "") or "").strip()
        scope_kind, scope_value = conversation_id.split(":", 2)[1:]
        if not sender_user_id:
            sender_user_id = scope_value if scope_kind == "user" else "synthetic-user"
        source = build_event_source_from_conversation_id(
            conversation_id,
            actor_user_id=sender_user_id,
        )
        raw_mentioned_user_ids = payload.get("mentioned_user_ids", [])
        mentioned_user_ids = [
            str(item).strip()
            for item in list(raw_mentioned_user_ids or [])
            if str(item).strip()
        ]
        event = StandardEvent(
            event_id=str(payload.get("event_id", "") or f"evt-synthetic-{uuid.uuid4().hex}"),
            event_type="message",
            platform="qq",
            timestamp=int(payload.get("timestamp") or time.time()),
            source=source,
            segments=segments,
            raw_message_id=str(payload.get("raw_message_id", "") or f"synthetic-msg-{uuid.uuid4().hex}"),
            sender_nickname=str(payload.get("sender_nickname", "") or "synthetic"),
            sender_role=(str(payload.get("sender_role")) if payload.get("sender_role") is not None else None),
            mentioned_user_ids=mentioned_user_ids,
            mentions_self=bool(payload.get("mentions_self", False)),
            mentioned_everyone=bool(payload.get("mentioned_everyone", False)),
            reply_targets_self=bool(payload.get("reply_targets_self", False)),
            targets_self=bool(payload.get("targets_self", True)),
            metadata={
                "synthetic": True,
                "injected_via": "http_api",
                **dict(payload.get("metadata", {}) or {}),
            },
            raw_event={
                "synthetic": True,
                "conversation_id": conversation_id,
                **dict(payload.get("raw_event", {}) or {}),
            },
        )
        await self.app.handle_event(event)
        thread_id = build_thread_id_from_conversation_id(conversation_id)
        related_run = None
        for run in await self.run_manager.list_runs(limit=100):
            if run.trigger_event_id == event.event_id:
                related_run = self._sanitize_run_record(run)
                break
        return {
            "event_id": event.event_id,
            "conversation_id": conversation_id,
            "thread_id": thread_id,
            "text": event.text,
            "segments": [{"type": segment.type, "data": dict(segment.data)} for segment in event.segments],
            "targets_self": event.targets_self,
            "synthetic": True,
            "run": related_run,
        }

    @staticmethod
    def _normalize_synthetic_segments(raw_segments: object, *, fallback_text: str | None) -> list[MsgSegment]:
        if raw_segments in (None, ""):
            if fallback_text is None:
                return []
            return [MsgSegment(type="text", data={"text": fallback_text})]
        if not isinstance(raw_segments, list):
            raise ValueError("segments must be a list")
        normalized: list[MsgSegment] = []
        for item in raw_segments:
            if not isinstance(item, dict):
                raise ValueError("segments items must be objects")
            seg_type = str(item.get("type", "") or "").strip()
            if not seg_type:
                raise ValueError("segments items require type")
            seg_data = item.get("data")
            if not isinstance(seg_data, dict):
                raise ValueError("segments items require object data")
            normalized.append(MsgSegment(type=seg_type, data=dict(seg_data)))
        return normalized

    async def post_notification(self, *, payload: dict[str, object]) -> dict[str, object]:
        """主动发送一条 bot 消息到指定会话."""

        conversation_id = str(payload.get("conversation_id", "") or "").strip()
        if not conversation_id:
            raise ValueError("conversation_id is required")
        normalized_target = normalize_target(payload.get("target"))
        if normalized_target is not None:
            conversation_id = normalized_target
        normalized = normalize_send_intent_payload(
            text=payload.get("text"),
            images=payload.get("images"),
            render=payload.get("render"),
            at_user=payload.get("at_user"),
            target=conversation_id,
        )

        outbox = getattr(self.app.pipeline, "outbox", None)
        if outbox is None:
            raise RuntimeError("outbox unavailable")

        gateway_self_id = str(getattr(self.app.gateway, "_self_id", "") or "").strip()
        target = build_event_source_from_conversation_id(
            conversation_id,
            actor_user_id=gateway_self_id,
        )
        thread_id = build_thread_id_from_conversation_id(conversation_id)
        notification_ctx = None
        if self.computer_runtime is not None:
            notification_ctx = await prepare_notification_run_context(
                computer_runtime=self.computer_runtime,
                conversation_id=conversation_id,
                gateway_self_id=gateway_self_id,
            )
            thread_id = notification_ctx.thread.thread_id
        elif any(str(item).startswith("/workspace/") for item in normalized["images"]):
            raise RuntimeError("computer runtime unavailable for workspace-backed notification send")
        run_id = f"notify:{uuid.uuid4().hex}"
        action_id = f"action:{uuid.uuid4().hex}"
        report = await outbox.send_items(
            [
                OutboxItem(
                    thread_id=thread_id,
                    run_id=run_id,
                    agent_id="system.notification",
                    origin_thread_id=thread_id,
                    destination_thread_id=thread_id,
                    destination_conversation_id=conversation_id,
                    plan=PlannedAction(
                        action_id=action_id,
                        action=Action(
                            action_type=ActionType.SEND_MESSAGE_INTENT,
                            target=target,
                            payload=normalized,
                        ),
                        metadata={
                            "message_action": "send",
                            "destination_conversation_id": conversation_id,
                            "notification_source": "control_plane",
                            "suppresses_default_reply": True,
                        },
                    ),
                    metadata={
                        "channel_scope": conversation_id,
                        "destination_conversation_id": conversation_id,
                        "notification_source": "control_plane",
                    },
                    world_view=(notification_ctx.world_view if notification_ctx is not None else None),
                )
            ]
        )
        result = report.results[0]
        raw_ack = dict(result.raw or {})
        if report.has_failures:
            return {
                "run_id": run_id,
                "action_id": action_id,
                "conversation_id": conversation_id,
                "thread_id": thread_id,
                "platform_message_id": "",
                "text": optional_text(normalized.get("text")),
                "images": list(normalized.get("images", []) or []),
                "render": optional_text(normalized.get("render")),
                "thread_content": "",
                "delivered": False,
                "error": result.error or "notification delivery failed",
                "ack": {
                    "status": str(raw_ack.get("status", "") or ""),
                    "retcode": raw_ack.get("retcode"),
                    "message_id": str(raw_ack.get("message_id", "") or ""),
                    "raw": raw_ack,
                },
            }

        delivered_item = report.delivered_items[0]
        thread_content = str(delivered_item.plan.thread_content or "").strip()
        if thread_content:
            await self._append_sent_message_to_thread(
                thread_id=thread_id,
                conversation_id=conversation_id,
                content=thread_content,
            )

        return {
            "run_id": run_id,
            "action_id": action_id,
            "conversation_id": conversation_id,
            "thread_id": thread_id,
            "platform_message_id": result.platform_message_id,
            "text": optional_text(normalized.get("text")),
            "images": list(normalized.get("images", []) or []),
            "render": optional_text(normalized.get("render")),
            "thread_content": thread_content,
            "delivered": True,
            "ack": {
                "status": str(raw_ack.get("status", "") or ""),
                "retcode": raw_ack.get("retcode"),
                "message_id": str(raw_ack.get("message_id", "") or result.platform_message_id),
                "raw": raw_ack,
            },
        }

    async def _append_sent_message_to_thread(
        self,
        *,
        thread_id: str,
        conversation_id: str,
        content: str,
    ) -> None:
        """把主动发送的 assistant 消息补进目标 thread working memory."""

        if self.thread_manager is None:
            return
        now = int(time.time())
        thread = await self.thread_manager.get_or_create(
            thread_id=thread_id,
            channel_scope=conversation_id,
            last_event_at=now,
        )
        async with thread.lock:
            thread.working_messages.append({"role": "assistant", "content": content})
            thread.last_event_at = now
        await self.thread_manager.save(thread)

    async def get_backend_status(self) -> BackendStatusSnapshot:
        """返回后台维护面的最小状态快照."""

        app = self.app
        session_service = getattr(app.backend_bridge, "session", None) if app.backend_bridge is not None else None
        binding = None
        session_path = ""
        if session_service is not None:
            load_binding = getattr(session_service, "load_binding", None)
            if callable(load_binding):
                    from ..model.model_registry import ModelBinding
                    loaded = load_binding()
                    if isinstance(loaded, ModelBinding):
                        binding = {
                            "binding_id": loaded.binding_id,
                            "target_id": loaded.target_id,
                            "preset_ids": list(loaded.preset_ids),
                            "timeout_sec": loaded.timeout_sec,
                        }
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
        session_bundles = (
            self.config_control_plane.list_session_bundles()
            if self.config_control_plane is not None
            else []
        )
        agent_items: list[dict[str, object]] = []
        seen_agent_ids: set[str] = set()
        for bundle in session_bundles:
            session = dict(bundle.get("session", {}) or {})
            agent = dict(bundle.get("agent", {}) or {})
            agent_id = str(agent.get("agent_id", "") or "")
            if not agent_id or agent_id in seen_agent_ids:
                continue
            agent_items.append(
                {
                    "agent_id": agent_id,
                    "name": str(session.get("title", "") or session.get("session_id", "") or agent_id),
                }
            )
            seen_agent_ids.add(agent_id)
        skills = await self.list_skills()
        subagents = await self.list_subagents()
        providers = await self.list_model_providers()
        presets = await self.list_model_presets()
        bindings = await self.list_model_bindings()
        return {
            "agents": agent_items,
            "prompts": [
                {
                    "prompt_ref": item.get("prompt_ref", ""),
                    "prompt_name": str(item.get("prompt_ref", "")).removeprefix("prompt/"),
                    "source": item.get("source", ""),
                }
                for item in prompts
            ],
            "tools": await self.list_available_tools(),
            "skills": [
                {
                    "skill_name": item.skill_name,
                    "display_name": item.display_name,
                    "description": item.description,
                    "has_references": item.has_references,
                    "has_scripts": item.has_scripts,
                    "has_assets": item.has_assets,
                }
                for item in skills
            ],
            "subagents": [
                {
                    "subagent_id": item.subagent_id,
                    "subagent_name": item.subagent_name,
                    "description": item.description,
                    "source": item.source,
                    "host_subagent_file_path": item.host_subagent_file_path,
                    "tools": list(item.tools),
                    "model_target": item.model_target,
                    "effective": item.effective,
                }
                for item in subagents
            ],
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
                    "task_kind": item.task_kind,
                    "capabilities": list(item.capabilities),
                }
                for item in presets
            ],
            "model_bindings": [
                {
                    "binding_id": item.binding.binding_id,
                    "target_id": item.binding.target_id,
                    "preset_ids": list(item.binding.preset_ids),
                    "timeout_sec": item.binding.timeout_sec,
                    "state": item.binding_state,
                }
                for item in bindings
            ],
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

    @staticmethod
    def _sanitize_run_record(run: RunRecord) -> dict[str, object]:
        return {
            "run_id": run.run_id,
            "thread_id": run.thread_id,
            "actor_id": run.actor_id,
            "agent_id": run.agent_id,
            "trigger_event_id": run.trigger_event_id,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error": run.error,
            "approval_context": sanitize_inspection_value(dict(run.approval_context)),
            "metadata": sanitize_inspection_value(dict(run.metadata)),
        }

    @staticmethod
    def _sanitize_run_step(step) -> dict[str, object]:
        return {
            "step_id": step.step_id,
            "run_id": step.run_id,
            "step_type": step.step_type,
            "status": step.status,
            "thread_id": step.thread_id,
            "payload": sanitize_inspection_value(dict(step.payload)),
            "created_at": step.created_at,
            "step_seq": int(step.step_seq or 0),
        }

    async def get_run(self, run_id: str) -> dict[str, object] | None:
        run = await self.run_manager.get(run_id)
        if run is None:
            return None
        return self._sanitize_run_record(run)

    async def list_run_steps(
        self,
        *,
        run_id: str,
        limit: int = 100,
        step_types: list[str] | None = None,
        latest: bool = False,
    ):
        steps = await self.run_manager.list_steps(
            run_id,
            limit=limit,
            step_types=step_types,
            latest=latest,
        )
        return [self._sanitize_run_step(step) for step in steps]

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

    async def list_model_targets(self):
        return await self.model_ops.list_model_targets()

    async def get_model_target(self, target_id: str):
        return await self.model_ops.get_model_target(target_id)

    async def list_model_bindings(self):
        return await self.model_ops.list_model_bindings()

    async def get_model_provider(self, provider_id: str) -> ModelProvider | None:
        return await self.model_ops.get_model_provider(provider_id)

    async def get_model_preset(self, preset_id: str) -> ModelPreset | None:
        return await self.model_ops.get_model_preset(preset_id)

    async def get_model_binding(self, binding_id: str):
        return await self.model_ops.get_model_binding(binding_id)

    async def get_model_provider_impact(self, provider_id: str) -> ModelImpactSnapshot:
        return await self.model_ops.get_model_provider_impact(provider_id)

    async def get_model_preset_impact(self, preset_id: str) -> ModelImpactSnapshot:
        return await self.model_ops.get_model_preset_impact(preset_id)

    async def get_model_binding_impact(self, binding_id: str) -> ModelImpactSnapshot:
        return await self.model_ops.get_model_binding_impact(binding_id)

    async def preview_effective_target_model(self, target_id: str) -> EffectiveModelSnapshot:
        return await self.model_ops.preview_effective_target_model(target_id)

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

    async def list_workspace_sessions(self, *, thread_id: str) -> list[str]:
        return await self.workspace_ops.list_workspace_sessions(thread_id=thread_id)

    async def list_workspace_attachments(self, *, thread_id: str) -> list[WorkspaceFileEntry]:
        return await self.workspace_ops.list_workspace_attachments(thread_id=thread_id)

    async def get_sandbox_status(self, *, thread_id: str) -> WorkspaceSandboxStatus:
        return await self.workspace_ops.get_sandbox_status(thread_id=thread_id)

    async def list_mirrored_skills(self, *, thread_id: str) -> list[str]:
        return await self.workspace_ops.list_mirrored_skills(thread_id=thread_id)

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

        if self.plugin_runtime_host is None:
            return []
        return sorted(self.plugin_runtime_host.loaded_plugin_ids())

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
    def _to_subagent_snapshot(
        item: SubagentPackageManifest,
        *,
        effective: bool,
    ) -> SubagentSnapshot:
        """把 SubagentPackageManifest 转成 SubagentSnapshot.

        Args:
            item: 当前 catalog subagent manifest.
            effective: 当前 manifest 是否为同名组里的生效版本.

        Returns:
            对应的 SubagentSnapshot.
        """

        return SubagentSnapshot(
            subagent_id=item.subagent_id,
            subagent_name=item.subagent_name,
            description=item.description,
            source=item.scope,
            host_subagent_file_path=item.host_subagent_file_path,
            tools=list(item.tools),
            model_target=item.model_target or "",
            effective=effective,
        )

    # region 新插件体系 API

    def list_plugins(self) -> list[dict[str, object]]:
        """列出所有插件的合并视图.

        Returns:
            每个插件一个字典, 包含 package/spec/status/effective_config.
        """

        all_ids: set[str] = set()
        packages: dict[str, object] = {}
        specs: dict[str, PluginSpec] = {}
        statuses: dict[str, PluginStatus] = {}

        if self.plugin_catalog is not None:
            scanned, _ = self.plugin_catalog.scan()
            for pid, pkg in scanned.items():
                all_ids.add(pid)
                packages[pid] = {
                    "plugin_id": pkg.plugin_id,
                    "display_name": pkg.display_name,
                    "entrypoint": pkg.entrypoint,
                    "version": pkg.version,
                    "default_config": dict(pkg.default_config),
                }
        if self.plugin_spec_store is not None:
            loaded_specs, _ = self.plugin_spec_store.load_all()
            for pid, spec in loaded_specs.items():
                all_ids.add(pid)
                specs[pid] = spec
        if self.plugin_status_store is not None:
            for pid, st in self.plugin_status_store.load_all().items():
                all_ids.add(pid)
                statuses[pid] = st

        result: list[dict[str, object]] = []
        for pid in sorted(all_ids):
            pkg_view = packages.get(pid)
            spec = specs.get(pid)
            st = statuses.get(pid)
            default_config = dict(
                (scanned[pid].default_config if pid in scanned else {})
            ) if self.plugin_catalog is not None and pid in (scanned if self.plugin_catalog is not None else {}) else {}
            spec_config = dict(spec.config) if spec is not None else {}
            effective_config = {**default_config, **spec_config}
            result.append({
                "plugin_id": pid,
                "package": pkg_view,
                "spec": {
                    "plugin_id": spec.plugin_id,
                    "enabled": spec.enabled,
                    "config": dict(spec.config),
                } if spec is not None else None,
                "status": {
                    "plugin_id": st.plugin_id,
                    "phase": st.phase,
                    "load_error": st.load_error,
                    "registered_tools": list(st.registered_tools),
                    "registered_hooks": list(st.registered_hooks),
                    "updated_at": st.updated_at,
                } if st is not None else None,
                "effective_config": effective_config,
            })
        return result

    def get_plugin(self, plugin_id: str) -> dict[str, object] | None:
        """获取单个插件的合并视图.

        Args:
            plugin_id: 目标插件 ID.

        Returns:
            合并视图字典, 不存在时返回 None.
        """

        for item in self.list_plugins():
            if item["plugin_id"] == plugin_id:
                return item
        return None

    async def update_plugin_spec(
        self,
        plugin_id: str,
        *,
        enabled: bool,
        config: dict,
    ) -> dict[str, object]:
        """创建或更新插件 spec 并触发单插件 reconcile.

        Args:
            plugin_id: 目标插件 ID.
            enabled: 是否启用.
            config: 操作者配置覆盖.

        Returns:
            该插件的合并视图.
        """

        if self.plugin_spec_store is None:
            raise RuntimeError("plugin spec store unavailable")
        spec = PluginSpec(plugin_id=plugin_id, enabled=enabled, config=dict(config))
        self.plugin_spec_store.save(spec)
        if self.plugin_reconciler is not None:
            await self.plugin_reconciler.reconcile_one(plugin_id)
        view = self.get_plugin(plugin_id)
        if view is None:
            return {"plugin_id": plugin_id}
        return view

    async def delete_plugin_spec(self, plugin_id: str) -> dict[str, object]:
        """删除插件 spec 并触发单插件 reconcile.

        Args:
            plugin_id: 目标插件 ID.

        Returns:
            该插件的合并视图.
        """

        if self.plugin_spec_store is None:
            raise RuntimeError("plugin spec store unavailable")
        self.plugin_spec_store.delete(plugin_id)
        if self.plugin_reconciler is not None:
            await self.plugin_reconciler.reconcile_one(plugin_id)
        view = self.get_plugin(plugin_id)
        if view is None:
            return {"plugin_id": plugin_id}
        return view

    async def reconcile_all_plugins(self) -> list[dict[str, object]]:
        """全量 reconcile 所有插件.

        Returns:
            所有插件的合并视图列表.
        """

        if self.plugin_reconciler is not None:
            await self.plugin_reconciler.reconcile_all()
        return self.list_plugins()

    # endregion 新插件体系 API


# endregion
