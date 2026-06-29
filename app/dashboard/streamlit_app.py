"""Streamlit dashboard for reviewing and approving email replies."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# Streamlit adds app/dashboard/ to sys.path; ensure the project root wins so
# `import app` resolves to the package, not a shadowing module name.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import streamlit as st

from app.auth.gmail_oauth import get_gmail_credentials
from app.config import LLMProvider, get_settings, validate_settings
from app.database.models import ProcessingStatus
from app.database.repository import EmailRepository
from app.gmail.client import GmailClient
from app.main import run_email_processor
from app.utils.logging import setup_logging

PRIORITY_COLORS = {
    "High": "#dc2626",
    "Medium": "#d97706",
    "Low": "#2563eb",
    "Newsletter": "#6b7280",
}

STATUS_LABELS = {
    ProcessingStatus.PENDING: "Pending",
    ProcessingStatus.PROCESSED: "Processed",
    ProcessingStatus.FAILED: "Failed",
    ProcessingStatus.REPLY_PENDING: "Reply needed",
    ProcessingStatus.REPLY_APPROVED: "Approved",
    ProcessingStatus.REPLY_REJECTED: "Rejected",
    ProcessingStatus.REPLY_SENT: "Sent",
}

STATUS_FILTER_OPTIONS = {
    "All": None,
    "Reply needed": "reply_pending",
    "Processed": "processed",
    "Sent": "reply_sent",
    "Rejected": "reply_rejected",
    "Failed": "failed",
}


def _model_label(settings) -> str:
    if settings.llm_provider == LLMProvider.GEMINI:
        return settings.gemini_model
    if settings.llm_provider == LLMProvider.OPENAI:
        return settings.openai_model
    if settings.llm_provider == LLMProvider.ANTHROPIC:
        return settings.anthropic_model
    if settings.llm_provider == LLMProvider.GROK:
        return settings.grok_model
    return settings.llm_provider.value


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
            #MainMenu, footer, header { visibility: hidden; }
            .block-container { padding-top: 1.5rem; max-width: 1200px; }
            .ea-metric-card {
                background: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                padding: 0.9rem 1rem;
            }
            .ea-metric-label {
                font-size: 0.78rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                color: #6b7280;
                margin-bottom: 0.15rem;
            }
            .ea-metric-value {
                font-size: 1.6rem;
                font-weight: 700;
                color: #111827;
                line-height: 1.1;
            }
            .ea-badge {
                display: inline-block;
                padding: 0.2rem 0.55rem;
                border-radius: 999px;
                font-size: 0.75rem;
                font-weight: 600;
                color: white;
            }
            .ea-status {
                display: inline-block;
                padding: 0.2rem 0.55rem;
                border-radius: 6px;
                font-size: 0.75rem;
                font-weight: 600;
                background: #f3f4f6;
                color: #374151;
            }
            .ea-status-pending { background: #fef3c7; color: #92400e; }
            .ea-status-sent { background: #d1fae5; color: #065f46; }
            .ea-status-failed { background: #fee2e2; color: #991b1b; }
            .ea-section-title {
                font-size: 1.05rem;
                font-weight: 600;
                color: #111827;
                margin: 1.25rem 0 0.75rem 0;
            }
            .ea-sidebar-title {
                font-size: 1.15rem;
                font-weight: 700;
                color: #111827;
                margin-bottom: 0.75rem;
            }
            div[data-testid="stSidebar"] {
                background-color: #f9fafb;
                border-right: 1px solid #e5e7eb;
            }
            div[data-testid="stSidebar"] .stButton > button {
                border-radius: 8px;
                font-weight: 600;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _priority_badge(priority: str) -> str:
    color = PRIORITY_COLORS.get(priority, "#6b7280")
    return f'<span class="ea-badge" style="background:{color};">{priority}</span>'


def _status_badge(status: ProcessingStatus) -> str:
    label = STATUS_LABELS.get(status, status.value)
    css = "ea-status"
    if status in (ProcessingStatus.REPLY_PENDING, ProcessingStatus.REPLY_APPROVED):
        css += " ea-status-pending"
    elif status == ProcessingStatus.REPLY_SENT:
        css += " ea-status-sent"
    elif status == ProcessingStatus.FAILED:
        css += " ea-status-failed"
    return f'<span class="{css}">{label}</span>'


def _metric_card(label: str, value: int | str, highlight: bool = False) -> None:
    border = "border-left: 4px solid #2563eb;" if highlight else ""
    st.markdown(
        f"""
        <div class="ea-metric-card" style="{border}">
            <div class="ea-metric-label">{label}</div>
            <div class="ea-metric-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_header() -> None:
    st.title("Email Assistant")


def _render_sidebar_header() -> None:
    st.markdown(
        '<p class="ea-sidebar-title">Email Assistant</p>',
        unsafe_allow_html=True,
    )


def _clear_database(database_path: Path) -> int:
    """Remove all processed email records so they can be reprocessed."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as conn:
        cursor = conn.execute("DELETE FROM processed_emails")
        conn.commit()
        return cursor.rowcount


def _render_reset_database(database_path: Path) -> None:
    st.markdown("### Data")
    confirm = st.checkbox("Clear all processed email history")
    if st.button(
        "Reset database",
        use_container_width=True,
        disabled=not confirm,
        type="secondary",
    ):
        removed = _clear_database(database_path)
        st.success(f"Cleared {removed} record(s). You can reprocess unread emails.")
        st.rerun()


def _run_processor() -> dict[str, int]:
    """Run the email processor and return result counts."""
    return run_email_processor()


def _send_approved_reply(
    repo: EmailRepository,
    gmail: GmailClient,
    record_id: int,
) -> None:
    """Send an approved draft reply. Only called after explicit user confirmation."""
    record = repo.get_by_id(record_id)
    if not record:
        st.error("Email record not found.")
        return

    if not record.draft_reply:
        st.error("No draft reply available for this email.")
        return

    if record.processing_status == ProcessingStatus.REPLY_SENT:
        st.warning("This reply has already been sent.")
        return

    to_address = GmailClient.extract_reply_address(record.sender)
    gmail.send_reply(
        thread_id=record.thread_id,
        to=to_address,
        subject=record.subject,
        body=record.draft_reply,
        in_reply_to_message_id=record.message_id,
    )
    repo.update_reply_status(record_id, ProcessingStatus.REPLY_SENT)
    st.success(f"Reply sent to {to_address}.")


def _render_email_card(
    email,
    repo: EmailRepository,
    settings,
    *,
    key_prefix: str,
    show_reply_form: bool = True,
) -> None:
    """Render a single email detail card."""
    status = email.processing_status
    expand = status in (ProcessingStatus.REPLY_PENDING, ProcessingStatus.FAILED)

    with st.expander(
        f"{email.subject}",
        expanded=expand,
    ):
        meta_left, meta_right = st.columns([2, 1])
        with meta_left:
            st.markdown(f"**From:** {email.sender}")
            if email.received_at:
                st.caption(f"Received {email.received_at}")
        with meta_right:
            st.markdown(_priority_badge(email.priority), unsafe_allow_html=True)
            st.markdown(_status_badge(status), unsafe_allow_html=True)

        st.markdown("##### Summary")
        st.write(email.summary)

        action_items = json.loads(email.action_items)
        deadlines = json.loads(email.deadlines)

        if action_items or deadlines:
            detail_col1, detail_col2 = st.columns(2)
            with detail_col1:
                if action_items:
                    st.markdown("##### Action items")
                    for item in action_items:
                        st.markdown(f"- {item}")
            with detail_col2:
                if deadlines:
                    st.markdown("##### Deadlines")
                    for deadline in deadlines:
                        st.markdown(f"- {deadline}")

        if email.error_message:
            st.error(email.error_message)

        if (
            show_reply_form
            and email.draft_reply
            and status in (
                ProcessingStatus.REPLY_PENDING,
                ProcessingStatus.REPLY_APPROVED,
            )
        ):
            st.markdown("##### Draft reply")
            with st.form(key=f"reply_form_{key_prefix}_{email.id}"):
                edited_reply = st.text_area(
                    "Edit before sending",
                    value=email.draft_reply,
                    height=180,
                    label_visibility="collapsed",
                )
                confirm = st.checkbox("I confirm I want to send this reply")
                btn_col1, btn_col2, _ = st.columns([1, 1, 2])
                with btn_col1:
                    send = st.form_submit_button("Approve & send", type="primary")
                with btn_col2:
                    reject = st.form_submit_button("Reject")

                if send:
                    if not confirm:
                        st.error("Check the confirmation box before sending.")
                    else:
                        try:
                            validate_settings(settings)
                            credentials = get_gmail_credentials(settings)
                            gmail = GmailClient(credentials, settings)
                            if edited_reply != email.draft_reply:
                                repo.update_draft_reply(email.id, edited_reply)
                            repo.update_reply_status(
                                email.id, ProcessingStatus.REPLY_APPROVED
                            )
                            _send_approved_reply(repo, gmail, email.id)
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed to send: {exc}")

                if reject:
                    repo.update_reply_status(email.id, ProcessingStatus.REPLY_REJECTED)
                    st.info("Reply rejected.")
                    st.rerun()

        elif email.draft_reply:
            st.markdown("##### Draft reply")
            st.text(email.draft_reply)
            if not show_reply_form:
                st.caption("Approve or reject this reply in the **Needs attention** tab.")

        if status == ProcessingStatus.REPLY_SENT:
            st.success("Reply sent.")


def main() -> None:
    """Render the Streamlit dashboard."""
    st.set_page_config(
        page_title="Email Assistant",
        page_icon="📧",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_styles()

    settings = get_settings()
    setup_logging(settings.log_level)
    repo = EmailRepository(settings.database_path)

    with st.sidebar:
        _render_sidebar_header()
        st.markdown("### Controls")
        if st.button("Process unread emails", use_container_width=True, type="primary"):
            try:
                validate_settings(settings)
                with st.status("Processing unread emails…", expanded=True) as status:
                    st.caption(
                        "This can take several minutes on the Gemini free tier "
                        "(rate limits apply). The page will update when finished."
                    )
                    counts = _run_processor()
                    status.update(
                        label="Processing complete",
                        state="complete",
                        expanded=False,
                    )
                st.success(
                    f"Done — processed: {counts['processed']}, "
                    f"skipped: {counts['skipped']}, failed: {counts['failed']}"
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Failed: {exc}")

        st.divider()
        _render_reset_database(settings.database_path)

        st.divider()
        st.markdown("### Filters")
        search = st.text_input("Search", placeholder="Subject, sender, summary...")
        priority_filter = st.selectbox(
            "Priority",
            ["All", "High", "Medium", "Low", "Newsletter"],
        )
        status_label = st.selectbox("Status", list(STATUS_FILTER_OPTIONS.keys()))
        status_filter = STATUS_FILTER_OPTIONS[status_label]

        st.divider()
        st.caption(f"**{settings.llm_provider.value}** · {_model_label(settings)}")

    _render_header()
    stats = repo.get_stats()

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    with m1:
        _metric_card("Total", stats["total"])
    with m2:
        _metric_card("High", stats["high"])
    with m3:
        _metric_card("Medium", stats["medium"])
    with m4:
        _metric_card("Low", stats["low"])
    with m5:
        _metric_card("Newsletter", stats["newsletter"])
    with m6:
        _metric_card("Needs reply", stats["pending_replies"], highlight=True)

    emails = repo.list_emails(
        search=search or None,
        priority=priority_filter if priority_filter != "All" else None,
        status=status_filter,
        limit=200,
    )

    if not emails:
        st.info("No emails yet. Use **Process unread emails** in the sidebar to get started.")
        return

    pending = [e for e in emails if e.processing_status == ProcessingStatus.REPLY_PENDING]
    failed = [e for e in emails if e.processing_status == ProcessingStatus.FAILED]

    tab_attention, tab_all, tab_table = st.tabs(
        [
            f"Needs attention ({len(pending) + len(failed)})",
            f"All emails ({len(emails)})",
            "Table view",
        ]
    )

    with tab_attention:
        if not pending and not failed:
            st.caption("Nothing needs your attention right now.")
        for email in pending + failed:
            _render_email_card(
                email, repo, settings, key_prefix="attention", show_reply_form=True
            )

    with tab_all:
        for email in emails:
            _render_email_card(
                email, repo, settings, key_prefix="all", show_reply_form=False
            )

    with tab_table:
        table_rows = []
        for email in emails:
            action_items = json.loads(email.action_items)
            deadlines = json.loads(email.deadlines)
            table_rows.append(
                {
                    "Subject": email.subject,
                    "Sender": email.sender,
                    "Priority": email.priority,
                    "Status": STATUS_LABELS.get(
                        email.processing_status, email.processing_status.value
                    ),
                    "Summary": email.summary[:100]
                    + ("…" if len(email.summary) > 100 else ""),
                    "Actions": "; ".join(action_items) if action_items else "—",
                    "Deadlines": "; ".join(deadlines) if deadlines else "—",
                    "Reply?": "Yes" if email.reply_recommended else "No",
                    "Processed": email.processed_at,
                }
            )
        st.dataframe(
            pd.DataFrame(table_rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Subject": st.column_config.TextColumn(width="medium"),
                "Summary": st.column_config.TextColumn(width="large"),
            },
        )


if __name__ == "__main__":
    main()
