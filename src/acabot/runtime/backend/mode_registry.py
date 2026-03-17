"""runtime.backend.mode_registry 管理管理员私聊后台模式状态."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BackendModeState:
    """一条管理员后台模式状态.

    Attributes:
        thread_id: 当前被置入后台模式的 thread 标识.
        actor_id: 开启后台模式的管理员 actor 标识.
        entered_at: 进入后台模式的时间戳.
    """

    thread_id: str
    actor_id: str
    entered_at: int


class BackendModeRegistry:
    """记录哪些管理员私聊 thread 当前处于后台模式."""

    def __init__(self) -> None:
        """初始化空的后台模式注册表."""

        self._states: dict[str, BackendModeState] = {}

    def enter_backend_mode(self, *, thread_id: str, actor_id: str, entered_at: int) -> None:
        """把一个 thread 标记为后台模式.

        Args:
            thread_id: 目标 thread 标识.
            actor_id: 进入后台模式的管理员 actor 标识.
            entered_at: 进入时间戳.
        """

        self._states[thread_id] = BackendModeState(
            thread_id=thread_id,
            actor_id=actor_id,
            entered_at=entered_at,
        )

    def exit_backend_mode(self, thread_id: str) -> None:
        """清除一个 thread 的后台模式状态."""

        self._states.pop(thread_id, None)

    def is_backend_mode(self, thread_id: str) -> bool:
        """返回指定 thread 当前是否处于后台模式."""

        return thread_id in self._states

    def get_backend_mode(self, thread_id: str) -> BackendModeState | None:
        """读取指定 thread 的后台模式状态."""

        return self._states.get(thread_id)

    def list_active_modes(self) -> list[BackendModeState]:
        """按进入时间顺序返回当前全部后台模式状态."""

        return sorted(
            self._states.values(),
            key=lambda state: (state.entered_at, state.thread_id),
        )
