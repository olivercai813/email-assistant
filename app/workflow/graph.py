"""LangGraph workflow for email analysis and draft reply generation."""

from __future__ import annotations

import re
from typing import Any

from langgraph.graph import END, StateGraph

from app.calendar.items import normalize_calendar_items, normalize_string_list
from app.config import Priority
from app.database.models import EmailAnalysis
from app.gmail.client import EmailMessage
from app.llm.interface import LLMInterface
from app.prompts.templates import (
    DRAFT_REPLY_SYSTEM_PROMPT,
    EMAIL_ANALYSIS_SYSTEM_PROMPT,
    REVIEW_REPLY_SYSTEM_PROMPT,
    build_analysis_user_prompt,
    build_draft_reply_user_prompt,
    build_review_user_prompt,
)
from app.utils.logging import get_logger
from app.workflow.state import EmailWorkflowState

logger = get_logger(__name__)

VALID_PRIORITIES = {p.value for p in Priority}
MAX_REPLY_REVISION_ATTEMPTS = 3

_SECURITY_LOGIN_PATTERNS = (
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"security alert",
        r"security notification",
        r"new sign[\s-]?in",
        r"new login",
        r"login attempt",
        r"sign[\s-]?in attempt",
        r"signed in to your",
        r"logged in to your",
        r"suspicious (?:sign[\s-]?in|login|activity)",
        r"unrecognized (?:device|sign[\s-]?in|login)",
        r"unusual (?:sign[\s-]?in|login|activity)",
        r"verify (?:this )?(?:sign[\s-]?in|login)",
        r"confirm (?:this )?(?:sign[\s-]?in|login)",
        r"someone (?:signed|logged) in",
        r"new device (?:sign[\s-]?in|login|used)",
        r"account (?:sign[\s-]?in|login)",
    )
)


def is_security_or_login_email(subject: str, sender: str, body: str) -> bool:
    """Detect automated security alerts and login notifications."""
    text = f"{subject}\n{sender}\n{body}"
    return any(pattern.search(text) for pattern in _SECURITY_LOGIN_PATTERNS)


def apply_security_login_overrides(
    *,
    subject: str,
    sender: str,
    body: str,
    priority: str,
    reply_recommended: bool,
) -> tuple[str, bool]:
    if is_security_or_login_email(subject, sender, body):
        return "Medium", False
    return priority, reply_recommended


def _create_draft_reply_nodes(llm: LLMInterface) -> tuple[Any, Any, Any]:
    """Return generate, review, and route-after-review handlers for draft workflows."""

    def generate_reply(state: EmailWorkflowState) -> EmailWorkflowState:
        logger.info("Generating draft reply for: %s", state.get("subject", ""))
        user_prompt = build_draft_reply_user_prompt(
            subject=state["subject"],
            sender=state["sender"],
            body=state["body"],
            summary=state.get("summary", ""),
            action_items=state.get("action_items", []),
            revision_feedback=state.get("revision_feedback", []),
        )
        result = llm.invoke_structured(DRAFT_REPLY_SYSTEM_PROMPT, user_prompt)
        draft = result.get("draft_reply", "")

        raw_output = dict(state.get("raw_ai_output", {}))
        raw_output["draft_reply_response"] = result

        return {
            **state,
            "draft_reply": draft or None,
            "raw_ai_output": raw_output,
            "status": "reply_generated",
        }

    def review_reply(state: EmailWorkflowState) -> EmailWorkflowState:
        logger.info("Reviewing draft reply for: %s", state.get("subject", ""))

        draft_reply = state.get("draft_reply") or ""
        if not draft_reply:
            return {
                **state,
                "review_passed": True,
                "revision_feedback": [],
                "status": "review_skipped",
            }

        user_prompt = build_review_user_prompt(
            subject=state["subject"],
            sender=state["sender"],
            body=state["body"],
            draft_reply=draft_reply,
        )
        result = llm.invoke_structured(REVIEW_REPLY_SYSTEM_PROMPT, user_prompt)
        approved = bool(result.get("approved", False))
        issues = result.get("issues", []) or []
        if not isinstance(issues, list):
            issues = [str(issues)]
        issues = [str(issue) for issue in issues if str(issue).strip()]

        attempts = int(state.get("revision_attempts", 0))
        if not approved:
            attempts += 1
            if attempts >= MAX_REPLY_REVISION_ATTEMPTS:
                approved = True
                issues = []

        raw_output = dict(state.get("raw_ai_output", {}))
        raw_output["review_reply_response"] = result

        return {
            **state,
            "review_passed": approved,
            "revision_feedback": issues,
            "revision_attempts": attempts,
            "raw_ai_output": raw_output,
            "status": "reply_reviewed",
        }

    def route_after_review(state: EmailWorkflowState) -> str:
        if state.get("review_passed"):
            return "finalize"
        return "generate_reply"

    return generate_reply, review_reply, route_after_review


def build_draft_reply_workflow(llm: LLMInterface) -> Any:
    """Build a workflow that drafts a reply and self-reviews up to max revision attempts."""

    generate_reply, review_reply, route_after_review = _create_draft_reply_nodes(llm)

    def finalize(state: EmailWorkflowState) -> EmailWorkflowState:
        return {**state, "status": "completed"}

    graph = StateGraph(EmailWorkflowState)
    graph.add_node("generate_reply", generate_reply)
    graph.add_node("review_reply", review_reply)
    graph.add_node("finalize", finalize)
    graph.set_entry_point("generate_reply")
    graph.add_edge("generate_reply", "review_reply")
    graph.add_conditional_edges(
        "review_reply",
        route_after_review,
        {"generate_reply": "generate_reply", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)
    return graph.compile()


def generate_draft_reply(
    llm: LLMInterface,
    *,
    subject: str,
    sender: str,
    body: str,
    summary: str = "",
    action_items: list[str] | None = None,
    raw_ai_output: dict[str, Any] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Run draft + review workflow and return the final draft text and merged raw output."""
    workflow = build_draft_reply_workflow(llm)
    initial_state: EmailWorkflowState = {
        "subject": subject,
        "sender": sender,
        "body": body,
        "summary": summary,
        "action_items": action_items or [],
        "revision_attempts": 0,
        "revision_feedback": [],
        "raw_ai_output": dict(raw_ai_output or {}),
        "status": "draft_started",
    }
    final_state = workflow.invoke(initial_state)
    return final_state.get("draft_reply"), dict(final_state.get("raw_ai_output", {}))


def build_email_workflow(llm: LLMInterface) -> Any:
    """Build and compile the LangGraph email processing workflow."""

    def analyze_email(state: EmailWorkflowState) -> EmailWorkflowState:
        logger.info("Analyzing email: %s", state.get("subject", ""))
        user_prompt = build_analysis_user_prompt(
            subject=state["subject"],
            sender=state["sender"],
            body=state["body"],
        )
        result = llm.invoke_structured(EMAIL_ANALYSIS_SYSTEM_PROMPT, user_prompt)

        priority = result.get("priority", "Low")
        if priority not in VALID_PRIORITIES:
            priority = "Low"

        reply_recommended = bool(result.get("reply_recommended", False))
        priority, reply_recommended = apply_security_login_overrides(
            subject=state["subject"],
            sender=state["sender"],
            body=state["body"],
            priority=priority,
            reply_recommended=reply_recommended,
        )

        return {
            **state,
            "priority": priority,
            "summary": result.get("summary", ""),
            "action_items": normalize_string_list(result.get("action_items")),
            "deadlines": normalize_string_list(result.get("deadlines")),
            "events": normalize_string_list(result.get("events")),
            "calendar_items": normalize_calendar_items(result.get("calendar_items")),
            "reply_recommended": reply_recommended,
            "raw_ai_output": result,
            "status": "analyzed",
        }

    def should_generate_reply(state: EmailWorkflowState) -> str:
        if state.get("reply_recommended"):
            return "generate_reply"
        return "finalize"

    generate_reply, review_reply, route_after_review = _create_draft_reply_nodes(llm)

    def finalize(state: EmailWorkflowState) -> EmailWorkflowState:
        return {**state, "status": "completed"}

    graph = StateGraph(EmailWorkflowState)
    graph.add_node("analyze_email", analyze_email)
    graph.add_node("generate_reply", generate_reply)
    graph.add_node("review_reply", review_reply)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("analyze_email")
    graph.add_conditional_edges(
        "analyze_email",
        should_generate_reply,
        {"generate_reply": "generate_reply", "finalize": "finalize"},
    )
    graph.add_edge("generate_reply", "review_reply")
    graph.add_conditional_edges(
        "review_reply",
        route_after_review,
        {"generate_reply": "generate_reply", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)

    return graph.compile()


def process_email(llm: LLMInterface, email: EmailMessage) -> EmailAnalysis:
    """Run the workflow for a single email and return structured analysis."""
    workflow = build_email_workflow(llm)

    initial_state: EmailWorkflowState = {
        "message_id": email.message_id,
        "thread_id": email.thread_id,
        "subject": email.subject,
        "sender": email.sender,
        "recipient": email.recipient,
        "body": email.body or email.snippet,
        "snippet": email.snippet,
        "received_at": email.received_at,
        "revision_attempts": 0,
        "revision_feedback": [],
        "status": "started",
    }

    final_state = workflow.invoke(initial_state)

    if final_state.get("reply_recommended") and not final_state.get("draft_reply"):
        logger.warning(
            "Reply recommended but no draft after workflow; running draft+review fallback for: %s",
            email.subject,
        )
        draft, raw_output = generate_draft_reply(
            llm,
            subject=email.subject,
            sender=email.sender,
            body=email.body or email.snippet,
            summary=final_state.get("summary", ""),
            action_items=final_state.get("action_items", []),
            raw_ai_output=final_state.get("raw_ai_output", {}),
        )
        if draft:
            final_state["draft_reply"] = draft
            final_state["raw_ai_output"] = raw_output

    return EmailAnalysis(
        priority=final_state.get("priority", "Low"),
        summary=final_state.get("summary", ""),
        action_items=final_state.get("action_items", []),
        deadlines=final_state.get("deadlines", []),
        events=final_state.get("events", []),
        calendar_items=final_state.get("calendar_items", []),
        reply_recommended=bool(final_state.get("reply_recommended", False)),
        draft_reply=final_state.get("draft_reply"),
        raw_ai_output=final_state.get("raw_ai_output", {}),
    )
