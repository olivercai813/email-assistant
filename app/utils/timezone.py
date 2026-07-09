"""Timezone helpers for user-facing timestamps."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
DISPLAY_FMT = "%Y-%m-%d %H:%M:%S EST"


def now_est_display() -> str:
    return datetime.now(EASTERN).strftime(DISPLAY_FMT)


def format_dt_est(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(EASTERN).strftime(DISPLAY_FMT)


def format_iso_est(value: str) -> str:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return format_dt_est(dt)
