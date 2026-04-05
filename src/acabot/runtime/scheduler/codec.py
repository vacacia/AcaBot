"""scheduler.codec 提供面向外部 payload 的 schedule 编解码 helper."""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

from .contracts import CronSchedule, IntervalSchedule, OneShotSchedule, ScheduleType

_DELAY_RE = re.compile(r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[smhd]?)\s*$", re.IGNORECASE)
_DELAY_UNIT_SECONDS = {
    "": 1.0,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
    "d": 86400.0,
}


def _parse_delay_seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        resolved = float(value)
    else:
        text = str(value or "").strip()
        match = _DELAY_RE.match(text)
        if match is None:
            raise ValueError("schedule.spec.delay must be numeric seconds or a value like 120s / 2m")
        resolved = float(match.group("value")) * _DELAY_UNIT_SECONDS[match.group("unit").lower()]
    if resolved <= 0:
        raise ValueError("schedule.spec.delay must be positive")
    return resolved


def _parse_one_shot_fire_at(spec: dict[str, Any]) -> float:
    fire_at = spec.get("fire_at")
    if fire_at in (None, ""):
        fire_at = spec.get("at")
    if fire_at not in (None, ""):
        try:
            resolved = float(fire_at)
        except (TypeError, ValueError):
            if isinstance(fire_at, str):
                text = fire_at.strip()
                try:
                    resolved = datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
                except ValueError as exc:
                    raise ValueError("schedule.spec.fire_at must be numeric or an ISO datetime string") from exc
            else:
                raise ValueError("schedule.spec.fire_at must be numeric or an ISO datetime string") from None
        if resolved <= 0:
            raise ValueError("schedule.spec.fire_at must be positive")
        return resolved
    delay = spec.get("delay")
    if delay not in (None, ""):
        return time.time() + _parse_delay_seconds(delay)
    raise ValueError("schedule.spec.fire_at is required for kind=one_shot")


def parse_schedule_payload(payload: dict[str, Any]) -> ScheduleType:
    """把外部 payload 解析成内部 ScheduleType."""

    if not isinstance(payload, dict):
        raise ValueError("schedule payload must be an object")
    kind = str(payload.get("kind", "") or "").strip()
    spec = payload.get("spec", {})
    if not isinstance(spec, dict):
        raise ValueError("schedule.spec must be an object")

    if kind == "cron":
        expr = str(spec.get("expr", "") or "").strip()
        if not expr:
            raise ValueError("schedule.spec.expr is required for kind=cron")
        return CronSchedule(cron_expr=expr)
    if kind == "interval":
        seconds = spec.get("seconds")
        if seconds in (None, ""):
            raise ValueError("schedule.spec.seconds is required for kind=interval")
        try:
            resolved = float(seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("schedule.spec.seconds must be numeric") from exc
        if resolved <= 0:
            raise ValueError("schedule.spec.seconds must be positive")
        return IntervalSchedule(seconds=resolved)
    if kind == "one_shot":
        return OneShotSchedule(fire_at=_parse_one_shot_fire_at(spec))
    raise ValueError(f"unknown schedule kind: {kind!r}")



def serialize_schedule_payload(schedule: ScheduleType) -> dict[str, Any]:
    """把内部 ScheduleType 序列化成外部 payload."""

    if isinstance(schedule, CronSchedule):
        return {"kind": "cron", "spec": {"expr": schedule.cron_expr}}
    if isinstance(schedule, IntervalSchedule):
        return {"kind": "interval", "spec": {"seconds": schedule.seconds}}
    if isinstance(schedule, OneShotSchedule):
        return {"kind": "one_shot", "spec": {"fire_at": schedule.fire_at}}
    raise TypeError(f"unknown schedule type: {type(schedule)!r}")


__all__ = ["parse_schedule_payload", "serialize_schedule_payload"]
