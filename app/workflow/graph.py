"""LangGraph workflow for email analysis and draft reply generation."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.config import Priority
from app.database.models import EmailAnalysis
from app.gmail.client import EmailMessage
from app.llm.interface import LLMInterface
from app.prompts.templates import (
    DRAFT_REPLY_SYSTEM_PROMPT,
    EMAIL_ANALYSIS_SYSTEM_PROMPT,
    build_analysis_user_prompt,
    build_draft_reply_user_prompt,
)
from app.utils.logging import get_logger
from app.workflow.state import EmailWorkflowState

logger = get_logger(__name__)

VALID_PRIORITIES = {p.value for p in Priority}


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

        return {
            **state,
            "priority": priority,
            "summary": result.get("summary", ""),
            "action_items": result.get("action_items", []) or [],
            "deadlines": result.get("deadlines", []) or [],
            "reply_recommended": bool(result.get("reply_recommended", False)),
            "raw_ai_output": result,
            "status": "analyzed",
        }

    def should_generate_reply(state: EmailWorkflowState) -> str:
        if state.get("reply_recommended"):
            return "generate_reply"
        return "finalize"

    def generate_reply(state: EmailWorkflowState) -> EmailWorkflowState:
        logger.info("Generating draft reply for: %s", state.get("subject", ""))
        user_prompt = build_draft_reply_user_prompt(
            subject=state["subject"],
            sender=state["sender"],
            body=state["body"],
            summary=state.get("summary", ""),
            action_items=state.get("action_items", []),
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

    def finalize(state: EmailWorkflowState) -> EmailWorkflowState:
        return {**state, "status": "completed"}

    graph = StateGraph(EmailWorkflowState)
    graph.add_node("analyze_email", analyze_email)
    graph.add_node("generate_reply", generate_reply)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("analyze_email")
    graph.add_conditional_edges(
        "analyze_email",
        should_generate_reply,
        {"generate_reply": "generate_reply", "finalize": "finalize"},
    )
    graph.add_edge("generate_reply", "finalize")
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
        "status": "started",
    }

    final_state = workflow.invoke(initial_state)

    return EmailAnalysis(
        priority=final_state.get("priority", "Low"),
        summary=final_state.get("summary", ""),
        action_items=final_state.get("action_items", []),
        deadlines=final_state.get("deadlines", []),
        reply_recommended=bool(final_state.get("reply_recommended", False)),
        draft_reply=final_state.get("draft_reply"),
        raw_ai_output=final_state.get("raw_ai_output", {}),
    )
