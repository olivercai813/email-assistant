"""Prompt templates for email analysis."""

from app.prompts.templates import (
    DRAFT_REPLY_SYSTEM_PROMPT,
    EMAIL_ANALYSIS_SYSTEM_PROMPT,
    build_analysis_user_prompt,
    build_draft_reply_user_prompt,
)

__all__ = [
    "EMAIL_ANALYSIS_SYSTEM_PROMPT",
    "DRAFT_REPLY_SYSTEM_PROMPT",
    "build_analysis_user_prompt",
    "build_draft_reply_user_prompt",
]
