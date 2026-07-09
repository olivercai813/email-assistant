"""SQLite repository for processed emails."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

from app.database.models import EmailAnalysis, ProcessedEmail, ProcessingStatus
from app.utils.logging import get_logger
from app.utils.timezone import format_iso_est, now_est_display

logger = get_logger(__name__)

LAST_PROCESSED_TIME_KEY = "last_processed_time"

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    body_preview TEXT,
    priority TEXT NOT NULL,
    summary TEXT NOT NULL,
    action_items TEXT NOT NULL DEFAULT '[]',
    deadlines TEXT NOT NULL DEFAULT '[]',
    events TEXT NOT NULL DEFAULT '[]',
    calendar_items TEXT NOT NULL DEFAULT '[]',
    calendar_added TEXT NOT NULL DEFAULT '{}',
    reply_recommended INTEGER NOT NULL DEFAULT 0,
    draft_reply TEXT,
    processing_status TEXT NOT NULL DEFAULT 'processed',
    ai_raw_output TEXT NOT NULL DEFAULT '{}',
    received_at TEXT,
    processed_at TEXT NOT NULL,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_processed_emails_message_id ON processed_emails(message_id);
CREATE INDEX IF NOT EXISTS idx_processed_emails_priority ON processed_emails(priority);
CREATE INDEX IF NOT EXISTS idx_processed_emails_status ON processed_emails(processing_status);
CREATE INDEX IF NOT EXISTS idx_processed_emails_processed_at ON processed_emails(processed_at);

CREATE TABLE IF NOT EXISTS app_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class EmailRepository:
    """Data access layer for processed email records."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate_schema(conn)
            conn.commit()

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(processed_emails)")}
        migrations = {
            "events": "ALTER TABLE processed_emails ADD COLUMN events TEXT NOT NULL DEFAULT '[]'",
            "calendar_items": "ALTER TABLE processed_emails ADD COLUMN calendar_items TEXT NOT NULL DEFAULT '[]'",
            "calendar_added": "ALTER TABLE processed_emails ADD COLUMN calendar_added TEXT NOT NULL DEFAULT '{}'",
        }
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(statement)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._database_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def is_processed(self, message_id: str) -> bool:
        """
        Return True if this message should be skipped in future runs.

        NOTE: We intentionally do NOT treat FAILED records as "processed" so that
        transient issues (e.g. Gemini 429 quota errors) can be retried on later runs.
        """
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM processed_emails
                WHERE message_id = ?
                  AND processing_status != ?
                """,
                (message_id, ProcessingStatus.FAILED.value),
            ).fetchone()
            return row is not None

    def save_processed_email(
        self,
        message_id: str,
        thread_id: str,
        subject: str,
        sender: str,
        recipient: str,
        body_preview: str,
        analysis: EmailAnalysis,
        received_at: str | None = None,
        status: ProcessingStatus = ProcessingStatus.PROCESSED,
        error_message: str | None = None,
    ) -> int:
        status_value = (
            ProcessingStatus.REPLY_PENDING.value
            if analysis.reply_recommended and analysis.draft_reply
            else status.value
        )

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO processed_emails (
                    message_id, thread_id, subject, sender, recipient, body_preview,
                    priority, summary, action_items, deadlines, events, calendar_items,
                    calendar_added, reply_recommended,
                    draft_reply, processing_status, ai_raw_output, received_at,
                    processed_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    priority = excluded.priority,
                    summary = excluded.summary,
                    action_items = excluded.action_items,
                    deadlines = excluded.deadlines,
                    events = excluded.events,
                    calendar_items = excluded.calendar_items,
                    reply_recommended = excluded.reply_recommended,
                    draft_reply = excluded.draft_reply,
                    processing_status = excluded.processing_status,
                    ai_raw_output = excluded.ai_raw_output,
                    processed_at = excluded.processed_at,
                    error_message = excluded.error_message
                """,
                (
                    message_id,
                    thread_id,
                    subject,
                    sender,
                    recipient,
                    body_preview[:500],
                    analysis.priority,
                    analysis.summary,
                    json.dumps(analysis.action_items),
                    json.dumps(analysis.deadlines),
                    json.dumps(analysis.events),
                    json.dumps(analysis.calendar_items),
                    "{}",
                    int(analysis.reply_recommended),
                    analysis.draft_reply,
                    status_value,
                    json.dumps(analysis.raw_ai_output),
                    received_at,
                    ProcessedEmail.now_iso(),
                    error_message,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def save_failed(self, message_id: str, thread_id: str, subject: str, error: str) -> None:
        analysis = EmailAnalysis(
            priority="Low",
            summary="Processing failed",
            action_items=[],
            deadlines=[],
            events=[],
            calendar_items=[],
            reply_recommended=False,
        )
        self.save_processed_email(
            message_id=message_id,
            thread_id=thread_id,
            subject=subject,
            sender="",
            recipient="",
            body_preview="",
            analysis=analysis,
            status=ProcessingStatus.FAILED,
            error_message=error,
        )

    def get_by_id(self, record_id: int) -> Optional[ProcessedEmail]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM processed_emails WHERE id = ?", (record_id,)
            ).fetchone()
            return self._row_to_model(row) if row else None

    def list_emails(
        self,
        search: str | None = None,
        priority: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ProcessedEmail]:
        query = "SELECT * FROM processed_emails WHERE 1=1"
        params: list[Any] = []

        if search:
            query += " AND (subject LIKE ? OR sender LIKE ? OR summary LIKE ?)"
            pattern = f"%{search}%"
            params.extend([pattern, pattern, pattern])

        if priority:
            query += " AND priority = ?"
            params.append(priority)

        if status:
            query += " AND processing_status = ?"
            params.append(status)

        query += " ORDER BY processed_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_model(row) for row in rows]

    def get_stats(self) -> dict[str, int]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM processed_emails").fetchone()[0]
            high = conn.execute(
                "SELECT COUNT(*) FROM processed_emails WHERE priority = 'High'"
            ).fetchone()[0]
            medium = conn.execute(
                "SELECT COUNT(*) FROM processed_emails WHERE priority = 'Medium'"
            ).fetchone()[0]
            low = conn.execute(
                "SELECT COUNT(*) FROM processed_emails WHERE priority = 'Low'"
            ).fetchone()[0]
            newsletter = conn.execute(
                "SELECT COUNT(*) FROM processed_emails WHERE priority = 'Newsletter'"
            ).fetchone()[0]
            pending_replies = conn.execute(
                "SELECT COUNT(*) FROM processed_emails WHERE processing_status = 'reply_pending'"
            ).fetchone()[0]

        return {
            "total": total,
            "high": high,
            "medium": medium,
            "low": low,
            "newsletter": newsletter,
            "pending_replies": pending_replies,
        }

    def clear_all(self) -> int:
        """Delete all processed email records. Returns number of rows removed."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM processed_emails")
            conn.commit()
            count = cursor.rowcount
        logger.info("Cleared %d record(s) from the database", count)
        return count

    def update_reply_status(self, record_id: int, status: ProcessingStatus) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE processed_emails SET processing_status = ? WHERE id = ?",
                (status.value, record_id),
            )
            conn.commit()

    def update_draft_reply(self, record_id: int, draft_reply: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE processed_emails SET draft_reply = ? WHERE id = ?",
                (draft_reply, record_id),
            )
            conn.commit()

    def mark_calendar_item_added(
        self,
        record_id: int,
        item_index: int,
        event_id: str,
        html_link: str,
    ) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT calendar_added FROM processed_emails WHERE id = ?",
                (record_id,),
            ).fetchone()
            if not row:
                return
            added = json.loads(row["calendar_added"] or "{}")
            added[str(item_index)] = {"event_id": event_id, "html_link": html_link}
            conn.execute(
                "UPDATE processed_emails SET calendar_added = ? WHERE id = ?",
                (json.dumps(added), record_id),
            )
            conn.commit()

    def get_metadata(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM app_metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_metadata(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_metadata (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()

    def delete_metadata(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM app_metadata WHERE key = ?", (key,))
            conn.commit()

    def get_last_processed_time(self) -> str | None:
        stored = self.get_metadata(LAST_PROCESSED_TIME_KEY)
        if stored:
            return stored
        with self._connect() as conn:
            row = conn.execute(
                "SELECT processed_at FROM processed_emails ORDER BY processed_at DESC LIMIT 1"
            ).fetchone()
        if not row or not row["processed_at"]:
            return None
        try:
            return format_iso_est(str(row["processed_at"]))
        except ValueError:
            return str(row["processed_at"])

    def set_last_processed_time(self, value: str) -> None:
        self.set_metadata(LAST_PROCESSED_TIME_KEY, value)

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> ProcessedEmail:
        return ProcessedEmail(
            id=row["id"],
            message_id=row["message_id"],
            thread_id=row["thread_id"],
            subject=row["subject"],
            sender=row["sender"],
            recipient=row["recipient"],
            body_preview=row["body_preview"] or "",
            priority=row["priority"],
            summary=row["summary"],
            action_items=row["action_items"] or "[]",
            deadlines=row["deadlines"] or "[]",
            events=row["events"] or "[]",
            calendar_items=row["calendar_items"] or "[]",
            calendar_added=row["calendar_added"] or "{}",
            reply_recommended=bool(row["reply_recommended"]),
            draft_reply=row["draft_reply"],
            processing_status=ProcessingStatus(row["processing_status"]),
            ai_raw_output=row["ai_raw_output"] or "{}",
            received_at=row["received_at"],
            processed_at=row["processed_at"],
            error_message=row["error_message"],
        )
