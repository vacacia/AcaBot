"""runtime.backend.session 定义后台 session 绑定与服务边界."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class BackendSessionBinding:
    """后台逻辑身份到 canonical pi session 的绑定记录."""

    backend_id: str
    transport: str
    pi_session_id: str
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
        created_at: int,
        last_active_at: int,
        status: str,
    ) -> BackendSessionBinding:
        """写回一份最新的 canonical backend session binding."""

        binding = BackendSessionBinding(
            backend_id=backend_id,
            transport=transport,
            pi_session_id=pi_session_id,
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
    """后台 canonical session 服务的最小边界.

    当前阶段只提供 binding 读取和接口占位, 真正的 pi 会话逻辑后续再接入.
    """

    def __init__(self, binding_store: BackendSessionBindingStore | None = None) -> None:
        """初始化 backend session 服务.

        Args:
            binding_store: 可选的 backend session binding store.
        """

        self.binding_store = binding_store

    def is_configured(self) -> bool:
        """返回当前 backend session 是否已具备真实分发能力.

        第一阶段的基础实现仍然是占位壳, 默认返回 False。
        真正接入 pi adapter 后, 再由正式实现覆盖这个判定。
        """

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
        """确保 canonical backend session 可用.

        当前为接口占位实现.
        """

        raise NotImplementedError

    async def send_change(self, summary: str) -> object:
        """把一条 change 请求送入 canonical backend session.

        当前为接口占位实现.
        """

        _ = summary
        raise NotImplementedError

    async def fork_query_from_stable_checkpoint(self, summary: str) -> object:
        """从稳定切点 fork 一个 query 会话并执行只读查询.

        当前为接口占位实现.
        """

        _ = summary
        raise NotImplementedError
