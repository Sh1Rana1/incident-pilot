"""跨时区事件的 SLA 时间窗口计算。"""

from datetime import datetime, timedelta


def _parse_event_time(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized).replace(tzinfo=None)


def completed_within_sla(
    started_at: str,
    completed_at: str,
    *,
    max_minutes: int,
) -> bool:
    started = _parse_event_time(started_at)
    completed = _parse_event_time(completed_at)
    elapsed = completed - started
    return timedelta(0) <= elapsed <= timedelta(minutes=max_minutes)
