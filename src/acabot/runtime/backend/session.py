"""runtime.backend.session 定义后台 session 绑定与服务边界."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from time import time

from .pi_adapter import PiBackendAdapter


@dataclass(slots=True)
class BackendSessionBinding:
    """后台逻辑身份到 canonical pi session 的绑定记录."""

    backend_id: str
    transport: str
    pi_session_id: str
    session_file: str
    created_at: int
    last_active_at: int
    status: str


class BackendSessionBindingStore:
    """读写 `.acabot-runtime/backend/session.json` 的最小存储层."""

    def __init__(self, path: str | Path) -> None:
        """保存 backend session binding 文件路径."""

        self.path = Path(path)

    def load(self) -> BackendSessionBinding | None:
        """读取当前 binding 文件.

        Returns:
            一份 BackendSessionBinding. 文件不存在时返回 None.
        """

        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return BackendSessionBinding(
            backend_id=str(payload["backend_id"]),
            transport=str(payload["transport"]),
            pi_session_id=str(payload["pi_session_id"]),
            session_file=str(payload.get("session_file", "")),
            created_at=int(payload["created_at"]),
            last_active_at=int(payload["last_active_at"]),
            status=str(payload["status"]),
        )

    def save(
        self,
        *,
        backend_id: str,
        transport: str,
        pi_session_id: str,
        session_file: str,
        created_at: int,
        last_active_at: int,
        status: str,
    ) -> BackendSessionBinding:
        """写回一份最新的 canonical backend session binding."""

        binding = BackendSessionBinding(
            backend_id=backend_id,
            transport=transport,
            pi_session_id=pi_session_id,
            session_file=session_file,
            created_at=created_at,
            last_active_at=last_active_at,
            status=status,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(binding), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return binding


class BackendSessionService:
    """后台 canonical session 服务的最小边界."""

    def __init__(self, binding_store: BackendSessionBindingStore | None = None) -> None:
        """初始化 backend session 服务.

        Args:
            binding_store: 可选的 backend session binding store.
        """

        self.binding_store = binding_store

    def is_configured(self) -> bool:
        """返回当前 backend session 是否已具备真实分发能力."""

        return False

    def load_binding(self) -> BackendSessionBinding | None:
        """读取当前 canonical backend session binding."""

        if self.binding_store is None:
            return None
        return self.binding_store.load()

    def get_binding_path(self) -> str:
        """返回当前 backend session binding 文件路径."""

        if self.binding_store is None:
            return ""
        return str(self.binding_store.path)

    async def ensure_backend_session(self) -> BackendSessionBinding:
        """确保 canonical backend session 可用."""

        raise NotImplementedError

    async def send_change(self, summary: str) -> object:
        """把一条 change 请求送入 canonical backend session."""

        _ = summary
        raise NotImplementedError

    async def fork_query_from_stable_checkpoint(self, summary: str) -> object:
        """从稳定切点 fork 一个 query 会话并执行只读查询."""

        _ = summary
        raise NotImplementedError


class ConfiguredBackendSessionService(BackendSessionService):
    """真实接通 pi RPC 的 backend session service."""

    def __init__(
        self,
        *,
        binding_store: BackendSessionBindingStore,
        adapter: PiBackendAdapter,
        backend_id: str = "main",
    ) -> None:
        """初始化 configured backend session service."""

        super().__init__(binding_store)
        self.adapter = adapter
        self.backend_id = backend_id

    def is_configured(self) -> bool:
        """configured service 代表 backend 已具备真实分发能力.

        review 后补充的约束：
        - 不能只因为 config 写了 `enabled=true` 就返回 True。
        - 至少要先确认 adapter 对应的 command 在当前环境里可执行。
        - 否则 control plane / admin routing / ask_backend 会把 backend 误报为已启用，
          但第一次真实请求才在启动子进程时炸掉，这对运维是误导性的。
        """

        return self.adapter.is_command_available()

    async def ensure_backend_session(self) -> BackendSessionBinding:
        """确保 canonical backend session 已创建并持久化 binding.

        注意这里有两个已经踩过的坑：
        1. 只保存 `pi_session_id` 不够，重启 `pi` 后无法稳定恢复；必须同时保存
           `session_file`，并优先按 `session_file` 恢复 canonical session。
        2. 不能对“当前已经打开的同一个 session_file”再次无脑 `switch_session()`。
           实测这样做会让 `pi` 返回新的 `sessionId`，虽然 `sessionFile` 还是同一个，
           结果就是 canonical binding 被我们自己切歪。

        所以这里的规则必须是：
        - 先 `ensure_started()` 读当前 `sessionFile`
        - 只有 binding 里的 `session_file` 与当前 `sessionFile` 不同时才 `switch_session()`
        - switch 后再重新 `get_state()`，并把真实的 `session_id/session_file` 回写 binding
        """

        existing = self.load_binding()
        state = await self.adapter.ensure_started()
        current_session_file = str(state["data"].get("sessionFile", ""))
        if (
            existing is not None
            and existing.session_file
            and existing.session_file != current_session_file
        ):
            await self.adapter.switch_session(existing.session_file)
            state = await self.adapter.ensure_started()
        session_id = str(state["data"]["sessionId"])
        session_file = str(state["data"].get("sessionFile", ""))
        now = int(time())
        created_at = existing.created_at if existing is not None else now
        binding = self.binding_store.save(
            backend_id=self.backend_id,
            transport="rpc",
            pi_session_id=session_id,
            session_file=session_file,
            created_at=created_at,
            last_active_at=now,
            status="ready",
        )
        return binding

    async def send_change(self, summary: str) -> object:
        """把 change 真实送入 canonical pi session.

        这里也有一个已经踩过的坑：
        - 不能在 prompt 之后继续把旧 binding 里的 `pi_session_id` 原样写回。
        - 实测 `pi` 在某些 session 切换路径下会给出新的 `sessionId`，如果这里不使用
          prompt 结果里返回的真实 `session_id/session_file` 回写 binding，binding 会漂移。
        """

        self._validate_summary(summary)
        binding = await self.ensure_backend_session()
        result = await self.adapter.prompt(summary)
        self.binding_store.save(
            backend_id=binding.backend_id,
            transport=binding.transport,
            pi_session_id=str(result.get("session_id", binding.pi_session_id)),
            session_file=str(result.get("session_file", binding.session_file)),
            created_at=binding.created_at,
            last_active_at=int(time()),
            status="ready",
        )
        return result

    async def fork_query_from_stable_checkpoint(self, summary: str) -> object:
        """从最近可 fork 的用户消息创建只读 query 会话."""

        self._validate_summary(summary)
        await self.ensure_backend_session()
        return await self.adapter.fork_from_stable_checkpoint(summary)

    def _validate_summary(self, summary: str) -> None:
        """拒绝 raw pi session 管理命令进入 backend canonical 面."""

        text = summary.strip()
        if not text:
            raise ValueError("backend summary must not be empty")
        if text.startswith("/"):
            command = text.split()[0]
            blocked = {
                "/new",
                "/resume",
                "/fork",
                "/tree",
                "/compact",
                "/settings",
                "/model",
            }
            if command in blocked:
                raise ValueError(f"raw pi session command is not allowed: {command}")
