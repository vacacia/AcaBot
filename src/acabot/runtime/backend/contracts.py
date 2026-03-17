"""runtime.backend.contracts 定义后台域的最小请求契约."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class BackendSourceRef:
    """后台请求的最小来源引用.

    Attributes:
        thread_id: 来源 thread 标识.
        channel_scope: 来源 channel 作用域.
        event_id: 对应的 inbound event 标识.
    """

    thread_id: str
    channel_scope: str
    event_id: str


@dataclass(slots=True)
class BackendRequest:
    """一条发往后台 maintainer 的最小请求.

    Attributes:
        request_id: 当前后台请求唯一标识.
        source_kind: 请求来源类型.
        request_kind: 请求语义, 当前只允许 `query` 或 `change`.
        source_ref: 可反查的最小来源引用.
        summary: 发给后台的简要任务摘要.
        created_at: 请求创建时间戳.
    """

    request_id: str
    source_kind: Literal["admin_direct", "frontstage_internal"]
    request_kind: Literal["query", "change"]
    source_ref: BackendSourceRef
    summary: str
    created_at: int
