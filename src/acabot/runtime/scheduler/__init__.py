"""runtime.scheduler 提供轻量级异步定时任务调度器.

支持 cron / interval / one-shot 三种调度类型,
带持久化恢复、misfire 策略、优雅关闭.
"""

from __future__ import annotations

from .codec import parse_schedule_payload, serialize_schedule_payload
from .contracts import (
    CronSchedule,
    IntervalSchedule,
    MisfirePolicy,
    OneShotSchedule,
    ScheduleType,
    ScheduledTaskInfo,
)
from .conversation_wakeup import ScheduledConversationWakeupDispatcher
from .scheduler import RuntimeScheduler
from .service import PluginScheduler, ScheduledTaskService
from .store import SQLiteScheduledTaskStore

__all__ = [
    "CronSchedule",
    "IntervalSchedule",
    "MisfirePolicy",
    "OneShotSchedule",
    "PluginScheduler",
    "RuntimeScheduler",
    "SQLiteScheduledTaskStore",
    "ScheduleType",
    "ScheduledConversationWakeupDispatcher",
    "ScheduledTaskInfo",
    "ScheduledTaskService",
    "parse_schedule_payload",
    "serialize_schedule_payload",
]
