"""scheduler.contracts 定义调度器的核心数据类型.

包括三种调度类型 (cron / interval / one_shot), 任务信息快照, DB 行映射,
以及 schedule 与 DB 存储格式之间的转换辅助函数.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MisfirePolicy = Literal["skip", "fire_once"]


@dataclass(frozen=True, slots=True)
class CronSchedule:
    """Cron 表达式调度.

    Attributes:
        cron_expr: 标准 5 段 cron 表达式 (分 时 日 月 周).
    """

    cron_expr: str


@dataclass(frozen=True, slots=True)
class IntervalSchedule:
    """固定间隔调度.

    Attributes:
        seconds: 间隔秒数 (float, 支持亚秒但精度不保证).
    """

    seconds: float


@dataclass(frozen=True, slots=True)
class OneShotSchedule:
    """一次性延迟执行.

    Attributes:
        fire_at: 触发时间 (Unix timestamp float).
    """

    fire_at: float


ScheduleType = CronSchedule | IntervalSchedule | OneShotSchedule


@dataclass(frozen=True, slots=True)
class ScheduledTaskInfo:
    """任务的只读快照, 供外部查询.

    Attributes:
        task_id: 任务唯一标识.
        owner: 注册来源标识.
        schedule: 调度配置.
        persist: 是否持久化.
        misfire_policy: misfire 策略.
        next_fire_at: 下次触发时间 (Unix timestamp).
        enabled: 是否启用.
        metadata: 扩展元数据.
    """

    task_id: str
    owner: str
    schedule: ScheduleType
    persist: bool
    misfire_policy: MisfirePolicy
    next_fire_at: float
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScheduledTaskRow:
    """DB 行到内存的映射. 内部使用.

    Attributes:
        task_id: 任务 ID.
        owner: 注册来源.
        schedule_type: "cron" | "interval" | "one_shot".
        schedule_spec: JSON 反序列化后的 dict.
        misfire_policy: misfire 策略.
        next_fire_at: 下次触发时间.
        enabled: 是否启用.
        created_at: 创建时间.
        updated_at: 最近更新时间.
        metadata: 扩展元数据.
    """

    task_id: str
    owner: str
    schedule_type: str
    schedule_spec: dict[str, Any]
    misfire_policy: MisfirePolicy
    next_fire_at: float
    enabled: bool
    created_at: float
    updated_at: float
    metadata: dict[str, Any] = field(default_factory=dict)


def schedule_to_type_and_spec(schedule: ScheduleType) -> tuple[str, dict[str, Any]]:
    """把 ScheduleType union 转换为 (schedule_type, schedule_spec) 用于 DB 存储.

    Args:
        schedule: 调度配置对象.

    Returns:
        (schedule_type, schedule_spec) 二元组.
    """

    if isinstance(schedule, CronSchedule):
        return ("cron", {"cron_expr": schedule.cron_expr})
    if isinstance(schedule, IntervalSchedule):
        return ("interval", {"interval_seconds": schedule.seconds})
    if isinstance(schedule, OneShotSchedule):
        return ("one_shot", {"fire_at": schedule.fire_at})
    raise TypeError(f"Unknown schedule type: {type(schedule)}")


def spec_to_schedule(schedule_type: str, schedule_spec: dict[str, Any]) -> ScheduleType:
    """从 DB 的 (schedule_type, schedule_spec) 恢复 ScheduleType.

    Args:
        schedule_type: 调度类型字符串.
        schedule_spec: 调度规格 dict.

    Returns:
        对应的 ScheduleType 实例.
    """

    if schedule_type == "cron":
        return CronSchedule(cron_expr=schedule_spec["cron_expr"])
    if schedule_type == "interval":
        return IntervalSchedule(seconds=schedule_spec["interval_seconds"])
    if schedule_type == "one_shot":
        return OneShotSchedule(fire_at=schedule_spec["fire_at"])
    raise ValueError(f"Unknown schedule_type: {schedule_type!r}")
