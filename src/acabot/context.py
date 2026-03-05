from contextvars import ContextVar

from .types import StandardEvent

# Pipeline 入口 set(), finally 中 reset().
# asyncio.create_task 会拷贝 context 快照, 并发安全.
# 注意: 后台任务中 current_event 可能是启动时的快照, 已过期.
current_event: ContextVar[StandardEvent | None] = ContextVar("current_event", default=None)
