"""Helpers for normalizing AI-extracted calendar items."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.calendar.datetime_utils import EASTERN, default_event_end, parse_iso_datetime, sanitize_optional_text

try:
    from dateutil import parser as date_parser
except ImportError:  # pragma: no cover - optional at runtime
    date_parser = None

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_HINT = re.compile(
    r"\b(\d{1,2}:\d{2}(?::\d{2})?|\d{1,2}\s*(?:am|pm|a\.m\.|p\.m\.))\b",
    re.IGNORECASE,
)


def _reference_datetime(reference_iso: str | None) -> datetime:
    if reference_iso:
        parsed = parse_iso_datetime(reference_iso)
        if parsed is not None:
            return parsed
    return datetime.now(EASTERN)


def _strip_ordinals(text: str) -> str:
    return re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)


def _line_title(text: str, *, fallback: str) -> str:
    if ":" in text:
        title = text.split(":", 1)[0].strip()
        if title:
            return title[:120]
    return fallback[:120]


def _line_to_calendar_item(
    text: str,
    *,
    item_type: str,
    fallback_title: str,
    reference_iso: str | None,
) -> dict[str, Any] | None:
    if date_parser is None:
        return None

    cleaned = _strip_ordinals(text.strip())
    if not cleaned:
        return None

    default = _reference_datetime(reference_iso)
    date_text = cleaned.split(":", 1)[1].strip() if ":" in cleaned else cleaned
    try:
        dt = date_parser.parse(date_text, default=default, fuzzy=True)
    except (ValueError, TypeError, OverflowError):
        try:
            dt = date_parser.parse(cleaned, default=default, fuzzy=True)
        except (ValueError, TypeError, OverflowError):
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=EASTERN)

    has_time = bool(_TIME_HINT.search(cleaned))
    all_day = not has_time
    return {
        "title": _line_title(cleaned, fallback=fallback_title),
        "type": item_type,
        "start": dt.date().isoformat() if all_day else dt.isoformat(),
        "end": None,
        "all_day": all_day,
        "description": cleaned,
    }


def build_fallback_calendar_items(
    *,
    events: list[str],
    deadlines: list[str],
    subject: str,
    reference_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Build calendar entries from plain-text events/deadlines when structured items are missing."""
    items: list[dict[str, Any]] = []
    for event in events:
        item = _line_to_calendar_item(
            event,
            item_type="event",
            fallback_title=subject,
            reference_iso=reference_iso,
        )
        if item:
            items.append(item)
    for deadline in deadlines:
        item = _line_to_calendar_item(
            deadline,
            item_type="deadline",
            fallback_title=subject,
            reference_iso=reference_iso,
        )
        if item:
            items.append(item)
    return items


def normalize_calendar_items(raw_items: Any) -> list[dict[str, Any]]:
    """Validate and normalize calendar item dicts from LLM output."""
    if not isinstance(raw_items, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        item_type = str(item.get("type", "")).strip().lower()
        start = str(item.get("start", "")).strip()
        if not title or item_type not in {"event", "deadline"} or not start:
            continue

        all_day = bool(item.get("all_day", False))
        if _ISO_DATE.match(start):
            all_day = True
        elif parse_iso_datetime(start) is None:
            continue

        end = sanitize_optional_text(item.get("end"))
        normalized.append(
            {
                "title": title,
                "type": item_type,
                "start": start,
                "end": end,
                "all_day": all_day,
                "description": sanitize_optional_text(item.get("description")) or "",
            }
        )
    return normalized


def normalize_string_list(raw_value: Any) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    return [str(item).strip() for item in raw_value if str(item).strip()]


def coalesce_calendar_items(
    *,
    structured_items: list[dict[str, Any]],
    events: list[str],
    deadlines: list[str],
    subject: str,
    reference_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Prefer structured AI items; otherwise derive them from event/deadline text."""
    normalized = normalize_calendar_items(structured_items)
    if normalized:
        return normalized
    return build_fallback_calendar_items(
        events=events,
        deadlines=deadlines,
        subject=subject,
        reference_iso=reference_iso,
    )


__all__ = [
    "build_fallback_calendar_items",
    "coalesce_calendar_items",
    "default_event_end",
    "normalize_calendar_items",
    "normalize_string_list",
]
