"""runtime.control 控制面返回用的轻量快照类型."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..backend.mode_registry import BackendModeState
from ..contracts import MemoryItem, PendingApprovalRecord


@dataclass(slots=True)
class ActiveRunSnapshot:
    """一条活跃 run 的轻量快照."""

    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    status: str
    started_at: int
    run_kind: str = "user"
    parent_run_id: str = ""
    delegate_agent_id: str = ""


@dataclass(slots=True)
class RuntimeStatusSnapshot:
    """本地 control plane 返回的最小状态快照."""

    active_runs: list[ActiveRunSnapshot] = field(default_factory=list)
    pending_approvals: list[PendingApprovalRecord] = field(default_factory=list)
    loaded_plugins: list[str] = field(default_factory=list)
    loaded_skills: list[str] = field(default_factory=list)
    interrupted_run_ids: list[str] = field(default_factory=list)

    @property
    def active_run_count(self) -> int:
        return len(self.active_runs)

    @property
    def pending_approval_count(self) -> int:
        return len(self.pending_approvals)


@dataclass(slots=True)
class GatewayStatusSnapshot:
    """当前 gateway 连接状态快照."""

    gateway_type: str = ""
    connection_mode: str = "reverse_ws_server"
    listen_host: str = ""
    listen_port: int = 0
    listen_url: str = ""
    server_running: bool = False
    connected: bool = False
    self_id: str = ""
    supports_call_api: bool = False
    token_configured: bool = False


@dataclass(slots=True)
class PluginReloadSnapshot:
    """一次 plugin reload 的最小结果."""

    requested_plugins: list[str] = field(default_factory=list)
    loaded_plugins: list[str] = field(default_factory=list)
    missing_plugins: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AgentSwitchSnapshot:
    """一次 thread agent switch 或控制面切换操作的结果."""

    ok: bool
    thread_id: str
    agent_id: str = ""
    message: str = ""


@dataclass(slots=True)
class MemoryQuerySnapshot:
    """一次 memory show 查询结果."""

    scope: str
    scope_key: str
    items: list[MemoryItem] = field(default_factory=list)


@dataclass(slots=True)
class SkillSnapshot:
    """一次 skill 查询返回的轻量快照."""

    skill_name: str
    display_name: str
    description: str
    has_references: bool = False
    has_scripts: bool = False
    has_assets: bool = False


@dataclass(slots=True)
class AgentSkillSnapshot:
    """某个 agent 当前可见的 skill 快照."""

    agent_id: str
    skill_name: str
    display_name: str
    description: str
    has_references: bool = False
    has_scripts: bool = False
    has_assets: bool = False


@dataclass(slots=True)
class SubagentExecutorSnapshot:
    """当前已注册 subagent executor 的轻量快照."""

    agent_id: str
    source: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class BackendStatusSnapshot:
    """后台维护面的最小状态快照."""

    configured: bool = False
    admin_actor_ids: list[str] = field(default_factory=list)
    session_binding: dict[str, object] | None = None
    session_path: str = ""
    active_modes: list[BackendModeState] = field(default_factory=list)
