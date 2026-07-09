"""Main email processing orchestrator."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.auth.gmail_oauth import get_gmail_credentials
from app.config import Priority, get_settings, validate_settings
from app.database.repository import EmailRepository
from app.gmail.client import GmailClient
from app.llm.interface import get_llm
from app.utils.logging import get_logger, setup_logging
from app.workflow.graph import process_email

logger = get_logger(__name__)


def _is_rate_limit_error(exc: Exception) -> bool:
    """Return True when the exception indicates an LLM quota/rate-limit error."""
    text = str(exc).lower()
    return (
        "resource_exhausted" in text
        or "quota exceeded" in text
        or "too many requests" in text
        or "429" in text
    )


def _received_sort_key(received_at: str | None) -> datetime:
    """Parse an ISO timestamp for newest-first sorting; fallback to epoch."""
    if not received_at:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        return datetime.fromisoformat(received_at.replace("Z", "+00:00"))
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def run_email_processor(
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    *,
    max_emails: int | None = None,
    auto_apply_labels: bool = True,
) -> dict[str, int | bool]:
    """
    Fetch primary inbox emails (read and unread), process through LangGraph, label, and persist.

    Returns a summary dict with counts and whether the run stopped early.
    """
    settings = get_settings()
    setup_logging(settings.log_level)
    validate_settings(settings)

    credentials = get_gmail_credentials(settings)
    gmail = GmailClient(credentials, settings)
    llm = get_llm(settings)
    repo = EmailRepository(settings.database_path)

    stats: dict[str, int | bool] = {
        "processed": 0,
        "skipped": 0,
        "failed": 0,
        "stopped_due_to_rate_limit": False,
        "total": 0,
        "completed": 0,
    }

    process_limit = max_emails or settings.max_emails_per_run
    scan_limit = max(process_limit * 10, 100)

    messages = gmail.list_inbox_messages(scan_limit=scan_limit)
    logger.info(
        "Scanned %d primary inbox message(s); will process up to %d newest unprocessed",
        len(messages),
        process_limit,
    )
    if progress_callback:
        progress_callback(
            {
                "event": "start",
                "total": process_limit,
                "scanned": len(messages),
                "completed": 0,
                "stats": dict(stats),
            }
        )

    candidates: list[tuple[dict[str, Any], datetime]] = []

    for msg_meta in messages:
        message_id = msg_meta["id"]

        if repo.is_processed(message_id):
            logger.debug("Skipping already processed message: %s", message_id)
            stats["skipped"] += 1
            continue

        try:
            received_at = gmail.get_message_received_at(message_id)
            candidates.append((msg_meta, _received_sort_key(received_at)))
        except Exception as exc:
            logger.exception("Failed to read metadata for message %s: %s", message_id, exc)
            repo.save_failed(
                message_id=message_id,
                thread_id=msg_meta.get("threadId", ""),
                subject=f"Message {message_id}",
                error=str(exc),
            )
            stats["failed"] += 1
            if _is_rate_limit_error(exc):
                stats["stopped_due_to_rate_limit"] = True
                break

    candidates.sort(key=lambda item: item[1], reverse=True)
    selected = candidates[:process_limit]

    pending: list[tuple[dict[str, Any], Any]] = []
    for msg_meta, _received in selected:
        message_id = msg_meta["id"]
        try:
            email = gmail.get_message(message_id)
            pending.append((msg_meta, email))
        except Exception as exc:
            logger.exception("Failed to fetch message %s: %s", message_id, exc)
            repo.save_failed(
                message_id=message_id,
                thread_id=msg_meta.get("threadId", ""),
                subject=f"Message {message_id}",
                error=str(exc),
            )
            stats["failed"] += 1
            if _is_rate_limit_error(exc):
                stats["stopped_due_to_rate_limit"] = True
                break

    stats["total"] = len(pending)

    for idx, (msg_meta, email) in enumerate(pending, start=1):
        message_id = msg_meta["id"]
        if progress_callback:
            progress_callback(
                {
                    "event": "message_started",
                    "message_id": message_id,
                    "index": idx,
                    "total": len(pending),
                    "completed": stats["completed"],
                    "stats": dict(stats),
                }
            )

        try:
            logger.info("Processing: %s — %s", email.subject, email.sender)

            analysis = process_email(llm, email)

            if auto_apply_labels:
                try:
                    priority = Priority(analysis.priority)
                    gmail.apply_priority_label(message_id, priority)
                except ValueError:
                    logger.warning("Unknown priority '%s', defaulting to Low", analysis.priority)
                    gmail.apply_priority_label(message_id, Priority.LOW)

            repo.save_processed_email(
                message_id=email.message_id,
                thread_id=email.thread_id,
                subject=email.subject,
                sender=email.sender,
                recipient=email.recipient,
                body_preview=email.body or email.snippet,
                analysis=analysis,
                received_at=email.received_at,
            )
            stats["processed"] += 1
            logger.info(
                "Processed message %s | Priority: %s | Reply recommended: %s",
                message_id,
                analysis.priority,
                analysis.reply_recommended,
            )
            stats["completed"] += 1
            if progress_callback:
                progress_callback(
                    {
                        "event": "message_processed",
                        "message_id": message_id,
                        "subject": email.subject,
                        "index": idx,
                        "total": len(pending),
                        "completed": stats["completed"],
                        "stats": dict(stats),
                    }
                )

        except Exception as exc:
            logger.exception("Failed to process message %s: %s", message_id, exc)
            repo.save_failed(
                message_id=message_id,
                thread_id=msg_meta.get("threadId", ""),
                subject=f"Message {message_id}",
                error=str(exc),
            )
            stats["failed"] += 1
            stats["completed"] += 1
            if progress_callback:
                progress_callback(
                    {
                        "event": "message_failed",
                        "message_id": message_id,
                        "index": idx,
                        "total": len(pending),
                        "completed": stats["completed"],
                        "error": str(exc),
                        "stats": dict(stats),
                    }
                )
            if _is_rate_limit_error(exc):
                stats["stopped_due_to_rate_limit"] = True
                logger.warning(
                    "Stopping run early due to Gemini rate limit/quota error. "
                    "Remaining emails were not attempted and can be retried later."
                )
                if progress_callback:
                    progress_callback(
                        {
                            "event": "stopped_rate_limit",
                            "message_id": message_id,
                            "index": idx,
                            "total": len(pending),
                            "completed": stats["completed"],
                            "error": str(exc),
                            "stats": dict(stats),
                        }
                    )
                break

    logger.info(
        "Run complete — processed: %d, skipped: %d, failed: %d",
        stats["processed"],
        stats["skipped"],
        stats["failed"],
    )
    if progress_callback:
        progress_callback(
            {
                "event": "complete",
                "total": len(pending),
                "completed": stats["completed"],
                "stats": dict(stats),
            }
        )
    return stats


if __name__ == "__main__":
    run_email_processor()
