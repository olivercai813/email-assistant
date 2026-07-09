"""Gmail API client for reading, labeling, and sending emails."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage as MimeEmailMessage
from email.utils import formataddr
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import PRIORITY_LABELS, Priority, Settings
from app.utils.logging import get_logger
from app.utils.retry import with_retry

logger = get_logger(__name__)


@dataclass
class EmailMessage:
    """Parsed Gmail message."""

    message_id: str
    thread_id: str
    subject: str
    sender: str
    recipient: str
    body: str
    snippet: str
    received_at: str


class GmailClient:
    """Wrapper around the Gmail API."""

    def __init__(self, credentials: Credentials, settings: Settings) -> None:
        self._settings = settings
        self._service = build("gmail", "v1", credentials=credentials)
        self._label_cache: dict[str, str] = {}
        self._user_email: str | None = None

    def _get_user_email(self) -> str:
        if self._user_email is None:
            profile = self._service.users().getProfile(userId="me").execute()
            self._user_email = profile.get("emailAddress", "")
        return self._user_email

    @with_retry(attempts=3, delay=2.0, exceptions=(HttpError,))
    def list_inbox_messages(
        self,
        *,
        max_results: int | None = None,
        scan_limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List primary inbox messages (read and unread), paginating up to scan_limit."""
        limit = scan_limit or max_results or self._settings.max_emails_per_run
        collected: list[dict[str, Any]] = []
        page_token: str | None = None

        while len(collected) < limit:
            batch_size = min(100, limit - len(collected))
            request: dict[str, Any] = {
                "userId": "me",
                "q": "in:inbox category:primary",
                "maxResults": batch_size,
            }
            if page_token:
                request["pageToken"] = page_token

            response = self._service.users().messages().list(**request).execute()
            collected.extend(response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return collected

    def list_unread_messages(self, max_results: int | None = None) -> list[dict[str, Any]]:
        """Backward-compatible alias for list_inbox_messages."""
        return self.list_inbox_messages(max_results=max_results)

    @with_retry(attempts=3, delay=2.0, exceptions=(HttpError,))
    def get_message_received_at(self, message_id: str) -> str:
        """Fetch only the received timestamp for sorting candidates."""
        raw = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata")
            .execute()
        )
        internal_date = raw.get("internalDate", "")
        if internal_date:
            return datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc).isoformat()
        return ""

    @with_retry(attempts=3, delay=2.0, exceptions=(HttpError,))
    def get_message(self, message_id: str) -> EmailMessage:
        """Fetch and parse a full email message."""
        raw = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
        body = self._extract_body(raw.get("payload", {}))
        internal_date = raw.get("internalDate", "")
        received_at = (
            datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc).isoformat()
            if internal_date
            else ""
        )

        return EmailMessage(
            message_id=message_id,
            thread_id=raw.get("threadId", ""),
            subject=headers.get("subject", "(no subject)"),
            sender=headers.get("from", ""),
            recipient=headers.get("to", ""),
            body=body,
            snippet=raw.get("snippet", ""),
            received_at=received_at,
        )

    def _extract_body(self, payload: dict[str, Any]) -> str:
        """Recursively extract plain-text body from a message payload."""
        if not payload:
            return ""

        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data")

        if mime_type == "text/plain" and body_data:
            return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

        if mime_type == "text/html" and body_data and not payload.get("parts"):
            html = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
            return self._html_to_text(html)

        parts = payload.get("parts", [])
        plain_text = ""
        html_text = ""

        for part in parts:
            part_mime = part.get("mimeType", "")
            if part_mime == "text/plain":
                plain_text += self._extract_body(part)
            elif part_mime == "text/html":
                html_text += self._extract_body(part)
            elif part.get("parts"):
                nested = self._extract_body(part)
                if nested:
                    return nested

        return plain_text or html_text

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Strip HTML tags for LLM consumption."""
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @with_retry(attempts=3, delay=2.0, exceptions=(HttpError,))
    def ensure_label(self, label_name: str) -> str:
        """Get or create a Gmail label, returning its ID."""
        if label_name in self._label_cache:
            return self._label_cache[label_name]

        labels = self._service.users().labels().list(userId="me").execute()
        for label in labels.get("labels", []):
            if label["name"] == label_name:
                self._label_cache[label_name] = label["id"]
                return label["id"]

        created = (
            self._service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": label_name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        self._label_cache[label_name] = created["id"]
        logger.info("Created Gmail label: %s", label_name)
        return created["id"]

    @with_retry(attempts=3, delay=2.0, exceptions=(HttpError,))
    def apply_priority_label(self, message_id: str, priority: Priority) -> None:
        """Apply a priority label and mark the message as read."""
        label_name = PRIORITY_LABELS[priority]
        label_id = self.ensure_label(label_name)
        self._service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id], "removeLabelIds": ["UNREAD"]},
        ).execute()
        logger.info("Applied label '%s' to message %s", label_name, message_id)

    @with_retry(attempts=3, delay=2.0, exceptions=(HttpError,))
    def send_reply(
        self,
        thread_id: str,
        to: str,
        subject: str,
        body: str,
        in_reply_to_message_id: str | None = None,
    ) -> str:
        """
        Send a reply email within an existing thread.

        Returns the sent message ID.
        """
        reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        normalized_body = self._normalize_outbound_body(body)

        message = MimeEmailMessage()
        sender_email = self._get_user_email()
        if sender_email:
            message["From"] = formataddr((self._settings.gmail_reply_from_name, sender_email))
        message["to"] = to
        message["subject"] = reply_subject
        message.set_content(normalized_body, subtype="plain", charset="utf-8")
        if in_reply_to_message_id:
            message["In-Reply-To"] = in_reply_to_message_id
            message["References"] = in_reply_to_message_id

        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        sent = (
            self._service.users()
            .messages()
            .send(
                userId="me",
                body={"raw": encoded, "threadId": thread_id},
            )
            .execute()
        )
        logger.info("Sent reply in thread %s (message %s)", thread_id, sent.get("id"))
        return sent.get("id", "")

    @staticmethod
    def _normalize_outbound_body(body: str) -> str:
        """
        Normalize line endings before MIME encoding to preserve dashboard formatting.

        Streamlit text areas and stored drafts can contain mixed newline styles.
        Converting everything to LF first avoids unpredictable visual line breaks in
        some mail clients after transport normalization.
        """
        normalized = body.replace("\r\n", "\n").replace("\r", "\n")
        # Trim trailing spaces that can render as odd wrapped lines in some clients.
        normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
        return normalized

    @staticmethod
    def extract_reply_address(sender: str) -> str:
        """Extract email address from a 'Name <email>' string."""
        match = re.search(r"<([^>]+)>", sender)
        if match:
            return match.group(1)
        return sender.strip()
