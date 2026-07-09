"""Google Calendar API client."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.calendar.datetime_utils import (
    default_event_end,
    format_google_calendar_datetime,
    parse_iso_datetime,
    sanitize_optional_text,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

EASTERN = ZoneInfo("America/New_York")
CALENDAR_ID = "primary"
CALENDAR_TIMEZONE = "America/New_York"


class GoogleCalendarClient:
    """Create calendar entries from extracted email items."""

    def __init__(self, credentials: Credentials) -> None:
        self._service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def create_from_item(
        self,
        item: dict[str, Any],
        *,
        email_subject: str,
        email_sender: str,
        gmail_message_id: str,
    ) -> dict[str, str]:
        """Create a Google Calendar event and return event id + html link."""
        title = str(item.get("title", "")).strip()
        item_type = str(item.get("type", "event")).strip().lower()
        all_day = bool(item.get("all_day", False))
        start_raw = str(item.get("start", "")).strip()
        end_raw = sanitize_optional_text(item.get("end"))
        description = sanitize_optional_text(item.get("description")) or ""

        if not title or not start_raw:
            raise ValueError("Calendar item is missing a title or start date.")

        gmail_link = f"https://mail.google.com/mail/u/0/#inbox/{gmail_message_id}"
        body_parts = [
            f"From: {email_sender}",
            f"Email subject: {email_subject}",
            f"Gmail: {gmail_link}",
        ]
        if description:
            body_parts.append(description)
        if item_type == "deadline":
            body_parts.append("Added from Email Assistant as a deadline reminder.")
        else:
            body_parts.append("Added from Email Assistant.")

        event_body: dict[str, Any] = {
            "summary": title,
            "description": "\n\n".join(body_parts),
        }

        if all_day:
            start_date = self._to_date(start_raw)
            end_date = self._to_date(end_raw) if end_raw else start_date + timedelta(days=1)
            if end_date <= start_date:
                end_date = start_date + timedelta(days=1)
            event_body["start"] = {"date": start_date.isoformat()}
            event_body["end"] = {"date": end_date.isoformat()}
        else:
            start_dt = parse_iso_datetime(start_raw)
            if start_dt is None:
                raise ValueError(f"Could not parse start datetime: {start_raw}")
            end_dt = parse_iso_datetime(end_raw) if end_raw else None
            if end_dt is None:
                end_dt = default_event_end(start_dt, all_day=False)
            if end_dt <= start_dt:
                end_dt = default_event_end(start_dt, all_day=False)
            event_body["start"] = {
                "dateTime": format_google_calendar_datetime(start_dt),
                "timeZone": CALENDAR_TIMEZONE,
            }
            event_body["end"] = {
                "dateTime": format_google_calendar_datetime(end_dt),
                "timeZone": CALENDAR_TIMEZONE,
            }

        try:
            created = (
                self._service.events()
                .insert(calendarId=CALENDAR_ID, body=event_body)
                .execute()
            )
        except HttpError as exc:
            detail = exc.reason or str(exc)
            if exc.content:
                detail = f"{detail} | {exc.content.decode('utf-8', errors='replace')}"
            raise RuntimeError(detail) from exc

        event_id = str(created.get("id", ""))
        html_link = str(created.get("htmlLink", ""))
        logger.info("Created calendar event %s for %s", event_id, title)
        return {"event_id": event_id, "html_link": html_link}

    @staticmethod
    def _to_date(value: str) -> date:
        dt = parse_iso_datetime(value)
        if dt is not None:
            return dt.date()
        return date.fromisoformat(value[:10])
