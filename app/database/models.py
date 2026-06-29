"""Database models and enums."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"
    REPLY_PENDING = "reply_pending"
    REPLY_APPROVED = "reply_approved"
    REPLY_REJECTED = "reply_rejected"
    REPLY_SENT = "reply_sent"


@dataclass
class EmailAnalysis:
    """Structured AI analysis output for an email."""

    priority: str
    summary: str
    action_items: list[str]
    deadlines: list[str]
    reply_recommended: bool
    draft_reply: str | None = None
    raw_ai_output: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessedEmail:
    """A processed email record stored in SQLite."""

    id: int | None
    message_id: str
    thread_id: str
    subject: str
    sender: str
    recipient: str
    body_preview: str
    priority: str
    summary: str
    action_items: str
    deadlines: str
    reply_recommended: bool
    draft_reply: str | None
    processing_status: ProcessingStatus
    ai_raw_output: str
    received_at: str | None
    processed_at: str
    error_message: str | None = None

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
