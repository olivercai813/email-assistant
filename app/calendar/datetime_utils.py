"""Shared datetime helpers for calendar modules."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if _ISO_DATE.match(text):
        return datetime.fromisoformat(text).replace(tzinfo=EASTERN)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=EASTERN)
    return dt


def default_event_end(start: datetime, *, all_day: bool) -> datetime:
    if all_day:
        return start + timedelta(days=1)
    return start + timedelta(hours=1)


def sanitize_optional_text(value: Any) -> str | None:
    """Normalize optional API/LLM fields that may be null, empty, or the literal 'None'."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return text


def format_google_calendar_datetime(dt: datetime) -> str:
    """Format a datetime for Google Calendar dateTime fields with a separate timeZone."""
    local = dt.astimezone(EASTERN)
    return local.replace(tzinfo=None).isoformat(timespec="seconds")
