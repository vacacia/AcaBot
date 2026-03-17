"""runtime.backend.bridge 负责把请求分流到后台 session 服务."""

from __future__ import annotations

from acabot.runtime.backend.contracts import BackendRequest
from acabot.runtime.backend.session import BackendSessionService


class BackendBridge:
    """前台与管理员进入后台的统一桥接入口."""

    def __init__(self, *, session: BackendSessionService) -> None:
        """保存 backend bridge 依赖的 session 服务."""

        self.session = session

    async def handle_frontstage_request(self, request: BackendRequest) -> object:
        """处理一条来自前台内部的后台请求."""

        return await self._dispatch(request)

    async def handle_admin_direct(self, request: BackendRequest) -> object:
        """处理一条来自管理员显式入口的后台请求."""

        return await self._dispatch(request)

    async def _dispatch(self, request: BackendRequest) -> object:
        """按请求语义把请求分流到 query/change 执行路径."""

        if request.request_kind == "query":
            return await self.session.fork_query_from_stable_checkpoint(request.summary)
        if request.request_kind == "change":
            return await self.session.send_change(request.summary)
        raise ValueError(f"Unsupported backend request_kind: {request.request_kind}")
