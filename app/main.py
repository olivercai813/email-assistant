"""Main email processing orchestrator."""

from __future__ import annotations

from app.auth.gmail_oauth import get_gmail_credentials
from app.config import Priority, get_settings, validate_settings
from app.database.repository import EmailRepository
from app.gmail.client import GmailClient
from app.llm.interface import get_llm
from app.utils.logging import get_logger, setup_logging
from app.workflow.graph import process_email

logger = get_logger(__name__)


def run_email_processor() -> dict[str, int]:
    """
    Fetch unread emails, process through LangGraph, label, and persist results.

    Returns a summary dict with counts of processed, skipped, and failed emails.
    """
    settings = get_settings()
    setup_logging(settings.log_level)
    validate_settings(settings)

    credentials = get_gmail_credentials(settings)
    gmail = GmailClient(credentials, settings)
    llm = get_llm(settings)
    repo = EmailRepository(settings.database_path)

    stats = {"processed": 0, "skipped": 0, "failed": 0}

    messages = gmail.list_unread_messages()
    logger.info("Found %d unread message(s) to evaluate", len(messages))

    for msg_meta in messages:
        message_id = msg_meta["id"]

        if repo.is_processed(message_id):
            logger.debug("Skipping already processed message: %s", message_id)
            stats["skipped"] += 1
            continue

        try:
            email = gmail.get_message(message_id)
            logger.info("Processing: %s — %s", email.subject, email.sender)

            analysis = process_email(llm, email)

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

        except Exception as exc:
            logger.exception("Failed to process message %s: %s", message_id, exc)
            repo.save_failed(
                message_id=message_id,
                thread_id=msg_meta.get("threadId", ""),
                subject=f"Message {message_id}",
                error=str(exc),
            )
            stats["failed"] += 1

    logger.info(
        "Run complete — processed: %d, skipped: %d, failed: %d",
        stats["processed"],
        stats["skipped"],
        stats["failed"],
    )
    return stats


if __name__ == "__main__":
    run_email_processor()
