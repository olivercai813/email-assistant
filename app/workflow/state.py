"""LangGraph workflow state definitions."""

from __future__ import annotations

from typing import Any, TypedDict


class EmailWorkflowState(TypedDict, total=False):
    """State passed between LangGraph nodes."""

    message_id: str
    thread_id: str
    subject: str
    sender: str
    recipient: str
    body: str
    snippet: str
    received_at: str

    priority: str
    summary: str
    action_items: list[str]
    deadlines: list[str]
    events: list[str]
    calendar_items: list[dict[str, Any]]
    reply_recommended: bool
    draft_reply: str | None
    raw_ai_output: dict[str, Any]
    revision_feedback: list[str]
    review_passed: bool
    revision_attempts: int

    error: str | None
    status: str
