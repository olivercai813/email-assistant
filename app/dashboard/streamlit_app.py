"""Streamlit dashboard for reviewing and approving email replies."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Streamlit adds app/dashboard/ to sys.path; ensure the project root wins so
# `import app` resolves to the package, not a shadowing module name.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from app.auth.gmail_oauth import get_gmail_credentials
from app.calendar.client import GoogleCalendarClient
from app.calendar.items import coalesce_calendar_items
from app.config import get_settings, validate_settings
from app.database.models import ProcessingStatus
from app.database.repository import EmailRepository, LAST_PROCESSED_TIME_KEY
from app.gmail.client import GmailClient
from app.llm.interface import get_llm
from app.main import run_email_processor
from app.workflow.graph import generate_draft_reply
from app.utils.logging import setup_logging
from app.utils.timezone import now_est_display

PRIORITY_COLORS = {
    "High": "#dc2626",
    "Medium": "#d97706",
    "Low": "#64748b",
    "Newsletter": "#7c3aed",
}

STATUS_LABELS = {
    ProcessingStatus.PENDING: "Pending",
    ProcessingStatus.PROCESSED: "Processed",
    ProcessingStatus.FAILED: "Failed",
    ProcessingStatus.REPLY_PENDING: "Needs reply",
    ProcessingStatus.REPLY_APPROVED: "Approved",
    ProcessingStatus.REPLY_REJECTED: "Rejected",
    ProcessingStatus.REPLY_SENT: "Sent",
}


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
            .stApp { background: #ffffff; }
            #MainMenu { visibility: hidden; }
            footer { visibility: hidden; }
            .stDeployButton { display: none; }
            [data-testid="stDecoration"] { display: none; }
            [data-testid="stToolbar"] { visibility: hidden; height: 0; min-height: 0; }
            header[data-testid="stHeader"] { visibility: hidden; height: 0; min-height: 0; }
            section[data-testid="stSidebar"],
            [data-testid="stSidebarCollapsedControl"],
            button[data-testid="stSidebarCollapseButton"],
            [data-testid="collapsedControl"] {
                display: none !important;
            }
            .block-container { padding-top: 1rem; max-width: 100%; padding-left: 1rem; padding-right: 1rem; }
            .stApp:has(.ea-settings-fab-marker) .block-container {
                padding-left: 3.4rem;
            }
            div[data-testid="stHorizontalBlock"]:has(.ea-custom-sidebar-marker) {
                align-items: stretch !important;
            }
            div[data-testid="column"]:has(.ea-custom-sidebar-marker) {
                background: #f6f8fc;
                border: none;
                border-radius: 0;
                padding: 0.25rem 0.75rem 0.55rem 0.35rem;
                align-self: stretch;
                min-height: calc(100vh - 2rem);
                max-width: 15.5rem;
                min-width: 14.5rem;
                font-size: 0.88rem;
                box-shadow: none;
            }
            .ea-vdivider-wrap {
                display: flex;
                justify-content: center;
                align-items: stretch;
                min-height: calc(100vh - 2rem);
                height: 100%;
                padding: 0 2.75rem 0 1rem;
            }
            .ea-vdivider-line {
                width: 1px;
                background-color: #dadce0;
                min-height: 100%;
                flex: 0 0 1px;
            }
            div[data-testid="column"]:has(.ea-vdivider-wrap) {
                flex: 0 0 auto !important;
                width: auto !important;
                min-width: 4rem !important;
                max-width: 5rem !important;
                padding: 0 !important;
            }
            div[data-testid="stHorizontalBlock"]:has(.ea-custom-sidebar-marker)
            > div[data-testid="column"]:last-child {
                padding-left: 1.5rem !important;
            }
            div[data-testid="stHorizontalBlock"]:has(.ea-draft-panel-marker):not(:has(.ea-custom-sidebar-marker))
            > div[data-testid="column"]:first-child {
                padding-right: 1rem !important;
            }
            div[data-testid="column"]:has(.ea-custom-sidebar-marker) h3,
            div[data-testid="column"]:has(.ea-custom-sidebar-marker) p {
                font-size: 0.92rem !important;
                margin-bottom: 0.15rem;
            }
            div[data-testid="column"]:has(.ea-custom-sidebar-marker) label {
                font-size: 0.82rem !important;
            }
            div[data-testid="column"]:has(.ea-custom-sidebar-marker) .stSelectbox,
            div[data-testid="column"]:has(.ea-custom-sidebar-marker) .stTextInput,
            div[data-testid="column"]:has(.ea-custom-sidebar-marker) .stMultiSelect,
            div[data-testid="column"]:has(.ea-custom-sidebar-marker) .stNumberInput {
                margin-bottom: 0.15rem;
            }
            div[data-testid="column"]:has(.ea-settings-fab-marker) {
                position: fixed;
                top: 0.55rem;
                left: 0.55rem;
                width: 2.4rem !important;
                flex: 0 0 2.4rem !important;
                z-index: 999;
            }
            div[data-testid="column"]:has(.ea-settings-fab-marker) button {
                min-height: 2.2rem;
                width: 2.2rem;
                padding: 0 0.35rem;
                font-size: 1.05rem;
                line-height: 1;
            }
            .ea-settings-panel-title {
                margin: 0;
                color: #202124;
                font-size: 0.95rem;
                font-weight: 600;
            }
            .ea-header-card {
                background: #ffffff;
                border: 1px solid #dadce0;
                border-radius: 8px;
                padding: 1.1rem 1.2rem;
                margin-bottom: 1.75rem;
                box-shadow: none;
            }
            .ea-title { margin: 0; color: #202124; font-size: 1.75rem; font-weight: 500; letter-spacing: 0; }
            .ea-subtitle { margin-top: 0.3rem; color: #5f6368; font-size: 0.95rem; }
            .ea-status-card {
                background: #f8f9fa;
                border: 1px solid #dadce0;
                border-radius: 8px;
                padding: 0.9rem 1rem;
                margin-top: 0.85rem;
                margin-bottom: 0.35rem;
            }
            .ea-button-stack { margin-top: 0.55rem; }
            .ea-last-processed { color: #5f6368; font-weight: 400; font-size: 0.82rem; margin-top: 0.55rem; }
            .ea-last-processed span { color: #202124; font-weight: 600; }
            .ea-subtle { color: #5f6368; }
            .ea-metric-card {
                background: #ffffff;
                border: 1px solid #dadce0;
                border-radius: 8px;
                padding: 0.8rem 1rem;
            }
            .ea-metric-label { color: #5f6368; font-size: 0.75rem; text-transform: uppercase; font-weight: 500; letter-spacing: 0.02em; }
            .ea-metric-value { color: #202124; font-size: 1.45rem; font-weight: 500; line-height: 1.1; margin-top: 0.2rem; }
            .ea-badge { display: inline-block; padding: 0.18rem 0.52rem; border-radius: 999px; font-size: 0.74rem; font-weight: 600; color: white; }
            .ea-reply-badge { display: inline-block; padding: 0.18rem 0.52rem; border-radius: 999px; font-size: 0.74rem; font-weight: 600; background: #fef7e0; color: #b06000; }
            .ea-event-badge { display: inline-block; padding: 0.18rem 0.52rem; border-radius: 999px; font-size: 0.74rem; font-weight: 600; background: #e8f0fe; color: #1a56db; }
            .ea-deadline-badge { display: inline-block; padding: 0.18rem 0.52rem; border-radius: 999px; font-size: 0.74rem; font-weight: 600; background: #fce8e6; color: #c5221f; }
            .ea-tag-row { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.35rem; margin-bottom: 0.15rem; }
            h1, h2, h3, h4, h5, h6 { color: #202124 !important; font-weight: 500 !important; }
            p, li, label, span, div, small { color: #202124; }
            [data-testid="stCaptionContainer"] { color: #5f6368 !important; }
            [data-testid="stMarkdownContainer"] p { color: #202124 !important; }
            [data-testid="stMarkdownContainer"] strong { color: #202124 !important; }
            [data-testid="stVerticalBlockBorderWrapper"] {
                background: #ffffff;
                border: 1px solid #dadce0 !important;
                border-radius: 8px;
                box-shadow: none;
            }
            div[data-testid="stButton"] button[kind="primary"] {
                background-color: #669df6 !important;
                border-color: #669df6 !important;
                color: #ffffff !important;
            }
            div[data-testid="stButton"] button[kind="primary"]:hover {
                background-color: #5b8ee6 !important;
                border-color: #5b8ee6 !important;
            }
            div[data-testid="stButton"] button[kind="secondary"] {
                background-color: #ffffff !important;
                border: 1px solid #dadce0 !important;
                color: #202124 !important;
            }
            .ea-draft-panel {
                background: #ffffff;
                border: 1px solid #dadce0;
                border-left: 3px solid #669df6;
                border-radius: 8px;
                padding: 0.25rem 0.5rem 0.5rem;
                position: sticky;
                top: 1rem;
                max-height: calc(100vh - 2rem);
                overflow-y: auto;
            }
            .ea-draft-panel-title {
                margin: 0;
                color: #202124;
                font-size: 1.1rem;
                font-weight: 500;
                line-height: 2rem;
            }
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.ea-draft-panel-marker) {
                position: relative;
            }
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.ea-draft-panel-marker)
            div[data-testid="stHorizontalBlock"]:first-of-type {
                align-items: center !important;
            }
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.ea-draft-panel-marker)
            div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="column"]:first-child {
                display: flex !important;
                align-items: center !important;
            }
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.ea-draft-panel-marker)
            div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="column"]:last-child {
                display: flex !important;
                justify-content: flex-end !important;
                align-items: center !important;
            }
            div[data-testid="stVerticalBlockBorderWrapper"]:has(.ea-draft-panel-marker)
            div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="column"]:last-child button {
                min-height: 2rem;
                height: 2rem;
                width: 2rem;
                padding: 0;
                font-size: 1rem;
                line-height: 1;
                margin: 0;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _init_state() -> None:
    st.session_state.setdefault("selected_email_id", None)
    st.session_state.setdefault("draft_email_id", None)
    st.session_state.setdefault("last_run_stats", {"processed": 0, "skipped": 0, "failed": 0})
    st.session_state.setdefault("process_count", 10)
    st.session_state.setdefault("auto_labels", True)
    st.session_state.setdefault("queue_filter", None)
    st.session_state.setdefault("settings_panel_open", False)
    st.session_state.setdefault("filter_search", "")
    st.session_state.setdefault("filter_priority", "All")
    st.session_state.setdefault("filter_status", [])
    st.session_state.setdefault("filter_date", "Last 30 days")


def _safe_json_list(text: str) -> list[str]:
    try:
        parsed = json.loads(text or "[]")
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _safe_json_objects(text: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(text or "[]")
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, dict)]
    except json.JSONDecodeError:
        return []


def _safe_json_dict(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _email_calendar_items(email) -> list[dict[str, Any]]:
    reference = email.received_at or email.processed_at
    return coalesce_calendar_items(
        structured_items=_safe_json_objects(getattr(email, "calendar_items", "[]")),
        events=_safe_json_list(getattr(email, "events", "[]")),
        deadlines=_safe_json_list(email.deadlines),
        subject=email.subject,
        reference_iso=reference,
    )


def _email_has_events(email) -> bool:
    if _safe_json_list(getattr(email, "events", "[]")):
        return True
    return any(item.get("type") == "event" for item in _email_calendar_items(email))


def _email_has_deadlines(email) -> bool:
    if _safe_json_list(getattr(email, "deadlines", "[]")):
        return True
    return any(item.get("type") == "deadline" for item in _email_calendar_items(email))


def _render_email_tags(email) -> None:
    badges: list[str] = []
    if email.reply_recommended:
        badges.append('<span class="ea-reply-badge">Reply recommended</span>')
    if _email_has_events(email):
        badges.append('<span class="ea-event-badge">Event</span>')
    if _email_has_deadlines(email):
        badges.append('<span class="ea-deadline-badge">Deadline</span>')
    if badges:
        st.markdown(f'<div class="ea-tag-row">{"".join(badges)}</div>', unsafe_allow_html=True)


def _render_calendar_actions(
    email,
    repo: EmailRepository,
    settings,
    *,
    compact: bool = False,
) -> None:
    calendar_items = _email_calendar_items(email)
    if not calendar_items:
        return

    if not compact:
        st.markdown("**Calendar**")
    calendar_added = _safe_json_dict(getattr(email, "calendar_added", "{}"))
    for idx, item in enumerate(calendar_items):
        item_type = str(item.get("type", "event")).title()
        when = item.get("start", "")
        end = item.get("end")
        timing = f"{when} → {end}" if end else str(when)
        label = f"{item.get('title', 'Untitled')} ({item_type}) · {timing}"
        added = calendar_added.get(str(idx))
        row_l, row_r = st.columns([3, 1.2])
        with row_l:
            st.markdown(label if not compact else f"**{label}**")
        with row_r:
            if added:
                link = added.get("html_link")
                if link:
                    st.link_button("Open", link, use_container_width=True)
                else:
                    st.caption("Added")
            elif st.button("Add to Calendar", key=f"cal_{email.id}_{idx}", use_container_width=True):
                ok, msg = _add_to_google_calendar(repo, settings, email, idx, item)
                if ok:
                    st.session_state["calendar_flash"] = msg
                    st.rerun()
                st.error(msg)


def _add_to_google_calendar(
    repo: EmailRepository,
    settings,
    email,
    item_index: int,
    item: dict[str, Any],
) -> tuple[bool, str]:
    try:
        validate_settings(settings)
        credentials = get_gmail_credentials(settings)
        calendar = GoogleCalendarClient(credentials)
        created = calendar.create_from_item(
            item,
            email_subject=email.subject,
            email_sender=email.sender,
            gmail_message_id=email.message_id,
        )
        repo.mark_calendar_item_added(
            email.id,
            item_index,
            created["event_id"],
            created["html_link"],
        )
        when = item.get("start", "")
        link = created.get("html_link", "")
        if link:
            return True, f"Added to Google Calendar ({when}). Open it from the button beside this item."
        return True, f"Added to Google Calendar ({when})."
    except Exception as exc:
        return False, f"Could not add to calendar: {exc}"


def _priority_badge(priority: str) -> str:
    color = PRIORITY_COLORS.get(priority, "#64748b")
    return f'<span class="ea-badge" style="background:{color};">{priority}</span>'


def _status_connected(settings) -> tuple[bool, str]:
    if not settings.gmail_credentials_path.exists():
        return False, "Disconnected"
    if not settings.gmail_token_path.exists():
        return False, "Disconnected"
    return True, "Connected"


def _run_processor(
    *,
    max_emails: int,
    auto_apply_labels: bool,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, int | bool]:
    return run_email_processor(
        progress_callback=progress_callback,
        max_emails=max_emails,
        auto_apply_labels=auto_apply_labels,
    )


def _generate_draft_for_email(repo: EmailRepository, settings, email) -> tuple[bool, str, str | None]:
    try:
        llm = get_llm(settings)
        raw_ai_output: dict[str, Any] = {}
        if email.ai_raw_output:
            try:
                raw_ai_output = json.loads(email.ai_raw_output)
            except json.JSONDecodeError:
                raw_ai_output = {}
        draft, _ = generate_draft_reply(
            llm,
            subject=email.subject,
            sender=email.sender,
            body=email.body_preview,
            summary=email.summary,
            action_items=_safe_json_list(email.action_items),
            raw_ai_output=raw_ai_output,
        )
        draft = str(draft or "").strip()
        if not draft:
            return False, "Could not generate a draft. Try again.", None
        repo.update_draft_reply(email.id, draft)
        repo.update_reply_status(email.id, ProcessingStatus.REPLY_PENDING)
        return True, "Draft generated.", draft
    except Exception:
        return False, "Could not generate a draft. Try again.", None


def _send_reply(repo: EmailRepository, settings, email, edited_reply: str) -> tuple[bool, str]:
    try:
        validate_settings(settings)
        credentials = get_gmail_credentials(settings)
        gmail = GmailClient(credentials, settings)
        if edited_reply != (email.draft_reply or ""):
            repo.update_draft_reply(email.id, edited_reply)
        repo.update_reply_status(email.id, ProcessingStatus.REPLY_APPROVED)
        to_address = GmailClient.extract_reply_address(email.sender)
        gmail.send_reply(
            thread_id=email.thread_id,
            to=to_address,
            subject=email.subject,
            body=edited_reply,
            in_reply_to_message_id=email.message_id,
        )
        repo.update_reply_status(email.id, ProcessingStatus.REPLY_SENT)
        return True, f"Reply sent to {to_address}."
    except Exception as exc:
        return False, f"Failed to send: {exc}"


def _current_filters() -> dict[str, Any]:
    return {
        "search": st.session_state.get("filter_search", ""),
        "priority": st.session_state.get("filter_priority", "All"),
        "status_filter": st.session_state.get("filter_status", []),
        "date_filter": st.session_state.get("filter_date", "Last 30 days"),
    }


def render_vertical_divider() -> None:
    st.markdown(
        """
        <div class="ea-vdivider-wrap" style="display:flex;justify-content:center;align-items:stretch;min-height:calc(100vh - 2rem);padding:0 2.75rem 0 1rem;">
            <div class="ea-vdivider-line" style="width:1px;background-color:#dadce0;min-height:100%;"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_settings_toggle() -> None:
    if st.session_state.get("settings_panel_open"):
        return
    fab_col, _ = st.columns([0.045, 0.955])
    with fab_col:
        st.markdown('<div class="ea-settings-fab-marker"></div>', unsafe_allow_html=True)
        if st.button("⚙", key="open_settings_panel", help="Settings & filters"):
            st.session_state["settings_panel_open"] = True
            st.rerun()


def render_settings_panel(repo: EmailRepository) -> dict[str, Any]:
    st.markdown('<div class="ea-custom-sidebar-marker"></div>', unsafe_allow_html=True)
    title_l, title_r = st.columns([4, 1])
    with title_l:
        st.markdown('<p class="ea-settings-panel-title">Settings</p>', unsafe_allow_html=True)
    with title_r:
        if st.button("✕", key="close_settings_panel", help="Close settings"):
            st.session_state["settings_panel_open"] = False
            st.rerun()

    st.caption("Filters")
    search = st.text_input("Search", placeholder="Sender, subject, summary", key="filter_search", label_visibility="collapsed")
    priority = st.selectbox("Priority", ["All", "High", "Medium", "Low", "Newsletter"], key="filter_priority")
    status_filter = st.multiselect(
        "Status",
        ["Needs reply", "Has action items", "Has events", "Has deadlines", "Already processed"],
        key="filter_status",
    )
    date_filter = st.selectbox("Date", ["Last 30 days", "Last 7 days", "Today"], key="filter_date")

    st.divider()
    st.caption("Processing")
    st.session_state["process_count"] = st.number_input(
        "Emails per run",
        min_value=1,
        max_value=100,
        value=st.session_state["process_count"],
        step=1,
        key="setting_process_count",
    )
    st.session_state["auto_labels"] = st.toggle(
        "Auto-apply Gmail labels", value=st.session_state["auto_labels"], key="setting_auto_labels"
    )

    st.divider()
    st.caption("Data")
    confirm = st.checkbox("Confirm reset", key="reset_confirm")
    if st.button("Reset database", disabled=not confirm, use_container_width=True, key="reset_db"):
        with sqlite3.connect(get_settings().database_path) as conn:
            conn.execute("DELETE FROM processed_emails")
            conn.commit()
        repo.delete_metadata(LAST_PROCESSED_TIME_KEY)
        st.success("Database reset.")
        st.rerun()

    return {
        "search": search,
        "priority": priority,
        "status_filter": status_filter,
        "date_filter": date_filter,
    }


def render_header(repo: EmailRepository, settings, emails: list[Any]) -> str:
    last_processed = repo.get_last_processed_time() or "N/A"
    st.markdown(
        f"""
        <div class="ea-header-card">
            <h1 class="ea-title">AI Email Assistant</h1>
            <div class="ea-subtitle">Prioritize, summarize, and manage important emails faster</div>
            <div class="ea-last-processed">Last processed: <span>{last_processed}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    btn_left, btn_right = st.columns(2, gap="medium")
    with btn_left:
        if st.button("Process New Emails", use_container_width=True, type="primary"):
            return "process"
    with btn_right:
        if st.button("Refresh Dashboard", use_container_width=True, type="secondary"):
            st.rerun()
    st.divider()
    return "idle"


def render_main_content(
    filters: dict[str, Any],
    settings,
    repo: EmailRepository,
) -> None:
    all_emails = repo.list_emails(limit=300)
    flash = st.session_state.pop("calendar_flash", None)
    if flash:
        st.success(flash)
    action = render_header(repo, settings, all_emails)
    if action == "process":
        try:
            _process_with_progress(settings, repo)
        except Exception as exc:
            st.error(f"Failed: {exc}")

    if not all_emails:
        st.info("No processed emails yet. Click Process New Emails to start.")
        return

    emails = _apply_filters(all_emails, filters)
    if len(emails) < len(all_emails):
        st.caption(f"Showing {len(emails)} of {len(all_emails)} emails (filters active).")
    render_queue_filters(emails)
    emails = _apply_queue_filter(emails, st.session_state.get("queue_filter"))

    draft_id = st.session_state.get("draft_email_id")
    draft_email = next((e for e in all_emails if e.id == draft_id), None) if draft_id else None
    if draft_id and draft_email is None:
        st.session_state["draft_email_id"] = None

    if draft_email:
        queue_col, divider_col, draft_col = st.columns([1.68, 0.12, 1], gap="medium")
    else:
        queue_col = st.container()
        divider_col = None
        draft_col = None

    with queue_col:
        st.markdown("### Email queue")
        if not emails:
            st.caption("No emails match this filter.")
        else:
            for email in emails:
                render_email_card(email, repo, settings)

    if divider_col and draft_col and draft_email:
        with divider_col:
            render_vertical_divider()
        with draft_col:
            render_draft_panel(draft_email, repo, settings)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _email_filter_date(email) -> datetime:
    """Use the most recent of received/processed time for date filtering."""
    received = _parse_dt(email.received_at)
    processed = _parse_dt(email.processed_at)
    candidates = [d for d in (received, processed) if d is not None]
    if not candidates:
        return datetime.now().astimezone()
    latest = max(candidates)
    if latest.tzinfo is None:
        return latest.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return latest


def _apply_filters(emails: list[Any], filters: dict[str, Any]) -> list[Any]:
    result = emails
    search = filters["search"].strip().lower()
    if search:
        result = [
            e for e in result if search in e.subject.lower() or search in e.sender.lower() or search in e.summary.lower()
        ]
    if filters["priority"] != "All":
        result = [e for e in result if e.priority == filters["priority"]]

    status_filters = set(filters["status_filter"])
    if status_filters:
        filtered: list[Any] = []
        for email in result:
            actions = _safe_json_list(email.action_items)
            deadlines = _safe_json_list(email.deadlines)
            already_processed = email.processing_status in {
                ProcessingStatus.PROCESSED,
                ProcessingStatus.REPLY_SENT,
                ProcessingStatus.REPLY_REJECTED,
            }
            if (
                ("Needs reply" in status_filters and email.reply_recommended)
                or ("Has action items" in status_filters and bool(actions))
                or ("Has events" in status_filters and _email_has_events(email))
                or ("Has deadlines" in status_filters and _email_has_deadlines(email))
                or ("Already processed" in status_filters and already_processed)
            ):
                filtered.append(email)
        result = filtered

    now = datetime.now().astimezone()
    window = {"Today": 1, "Last 7 days": 7, "Last 30 days": 30}[filters["date_filter"]]
    cutoff = now - timedelta(days=window)
    result = [e for e in result if _email_filter_date(e) >= cutoff]
    return result


def _apply_queue_filter(emails: list[Any], filter_key: str | None) -> list[Any]:
    if filter_key == "reply_needed":
        return [e for e in emails if e.reply_recommended]
    if filter_key == "high":
        return [e for e in emails if e.priority == "High"]
    if filter_key == "medium":
        return [e for e in emails if e.priority == "Medium"]
    if filter_key == "low":
        return [e for e in emails if e.priority in ("Low", "Newsletter")]
    return emails


def render_queue_filters(emails: list[Any]) -> None:
    """Render clickable queue filters and store active selection in session state."""
    counts = {
        "reply_needed": sum(1 for e in emails if e.reply_recommended),
        "high": sum(1 for e in emails if e.priority == "High"),
        "medium": sum(1 for e in emails if e.priority == "Medium"),
        "low": sum(1 for e in emails if e.priority in ("Low", "Newsletter")),
    }
    options = [
        ("reply_needed", "Reply needed"),
        ("high", "High"),
        ("medium", "Medium"),
        ("low", "Low"),
    ]
    c1, c2, c3, c4 = st.columns(4)
    for col, (key, label) in zip([c1, c2, c3, c4], options):
        with col:
            is_active = st.session_state.get("queue_filter") == key
            if st.button(
                f"{label}\n{counts[key]}",
                key=f"queue_filter_{key}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                st.session_state["queue_filter"] = None if is_active else key
                st.rerun()


def render_email_summary(email, repo: EmailRepository, settings) -> None:
    st.markdown("**Summary**")
    st.write(email.summary or "No summary available.")

    events = _safe_json_list(getattr(email, "events", "[]"))
    if events:
        st.markdown("**Events**")
        for event in events:
            st.markdown(f"- {event}")

    deadlines = _safe_json_list(email.deadlines)
    if deadlines:
        st.markdown("**Deadlines**")
        for deadline in deadlines:
            st.markdown(f"- {deadline}")

    _render_calendar_actions(email, repo, settings)


def _open_draft_panel(repo: EmailRepository, settings, email) -> None:
    if not email.draft_reply:
        ok, msg, draft = _generate_draft_for_email(repo, settings, email)
        if not ok:
            st.error(msg)
            return
        st.session_state[f"draft_text_{email.id}"] = draft or ""
    st.session_state["draft_email_id"] = email.id
    st.rerun()


def render_email_card(email, repo: EmailRepository, settings) -> None:
    with st.container(border=True):
        top_l, top_r = st.columns([4, 1])
        with top_l:
            st.markdown(f"**{email.subject}**")
            st.caption(f"{email.sender} · {email.received_at or email.processed_at}")
        with top_r:
            st.markdown(_priority_badge(email.priority), unsafe_allow_html=True)
        _render_email_tags(email)

        is_selected = st.session_state.get("selected_email_id") == email.id
        if _email_calendar_items(email) and not is_selected:
            _render_calendar_actions(email, repo, settings, compact=True)
        if is_selected:
            st.divider()
            render_email_summary(email, repo, settings)

        b1, b2, b3 = st.columns(3)
        with b1:
            summary_label = "Hide Summary" if is_selected else "View Summary"
            if st.button(summary_label, key=f"view_{email.id}", use_container_width=True):
                st.session_state["selected_email_id"] = None if is_selected else email.id
                st.rerun()
        with b2:
            st.link_button(
                "Open in Gmail",
                f"https://mail.google.com/mail/u/0/#inbox/{email.message_id}",
                use_container_width=True,
            )
        with b3:
            draft_label = "Edit Draft" if email.draft_reply else "Generate Draft Reply"
            if st.button(draft_label, key=f"gen_{email.id}", use_container_width=True):
                _open_draft_panel(repo, settings, email)


def render_draft_panel(email, repo: EmailRepository, settings) -> None:
    with st.container(border=True):
        st.markdown('<div class="ea-draft-panel-marker"></div>', unsafe_allow_html=True)
        header_l, header_r = st.columns([8, 1], gap="small", vertical_alignment="center")
        with header_l:
            st.markdown('<p class="ea-draft-panel-title">Draft reply</p>', unsafe_allow_html=True)
        with header_r:
            if st.button("✕", key="close_draft_panel", help="Close draft"):
                st.session_state["draft_email_id"] = None
                st.session_state[f"confirm_send_{email.id}"] = False
                st.rerun()

        st.caption(f"Re: {email.subject}")
        st.caption(email.sender)

        draft_key = f"draft_text_{email.id}"
        if draft_key not in st.session_state:
            st.session_state[draft_key] = email.draft_reply or ""

        st.session_state[draft_key] = st.text_area(
            "Editable draft",
            value=st.session_state[draft_key],
            height=360,
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Save Draft", key=f"save_{email.id}", use_container_width=True):
                repo.update_draft_reply(email.id, st.session_state[draft_key])
                repo.update_reply_status(email.id, ProcessingStatus.REPLY_PENDING)
                st.success("Draft saved.")
        with c2:
            if st.button("Regenerate", key=f"regen_{email.id}", use_container_width=True):
                ok, msg, draft = _generate_draft_for_email(repo, settings, email)
                if ok and draft:
                    st.session_state[draft_key] = draft
                (st.success if ok else st.error)(msg)
                st.rerun()

        if st.button("Send Reply", key=f"send_{email.id}", use_container_width=True, type="primary"):
            st.session_state[f"confirm_send_{email.id}"] = True

        if st.session_state.get(f"confirm_send_{email.id}", False):
            st.warning("Are you sure you want to send this reply?")
            confirm_l, confirm_r = st.columns(2)
            with confirm_l:
                if st.button("Confirm Send", key=f"confirm_{email.id}", type="primary", use_container_width=True):
                    ok, msg = _send_reply(repo, settings, email, st.session_state[draft_key])
                    (st.success if ok else st.error)(msg)
                    st.session_state[f"confirm_send_{email.id}"] = False
                    if ok:
                        st.session_state["draft_email_id"] = None
                    st.rerun()
            with confirm_r:
                if st.button("Cancel Send", key=f"cancel_{email.id}", use_container_width=True):
                    st.session_state[f"confirm_send_{email.id}"] = False
                    st.rerun()


def _process_with_progress(settings, repo: EmailRepository) -> None:
    validate_settings(settings)
    with st.status("Analyzing emails...", expanded=True) as status:
        progress_text = st.empty()
        progress_bar = st.progress(0.0)

        def _on_progress(event: dict[str, Any]) -> None:
            total = int(event.get("total", 0) or 0)
            completed = int(event.get("completed", 0) or 0)
            progress_bar.progress(min((completed / total), 1.0) if total else 1.0)
            if event.get("event") == "start":
                scanned = int(event.get("scanned", total) or total)
                progress_text.write(
                    f"Scanned {scanned} primary inbox email(s); processing up to {total} newest unprocessed."
                )
            elif event.get("event") == "message_started":
                progress_text.write(f"Processing email {event.get('index', '?')} of {total}...")
            elif event.get("event") == "complete":
                stats = event.get("stats", {})
                progress_text.write(
                    f"Finished. Processed: {stats.get('processed', 0)}, skipped: {stats.get('skipped', 0)}, failed: {stats.get('failed', 0)}"
                )

        counts = _run_processor(
            max_emails=int(st.session_state["process_count"]),
            auto_apply_labels=bool(st.session_state["auto_labels"]),
            progress_callback=_on_progress,
        )
        st.session_state["last_run_stats"] = {
            "processed": int(counts.get("processed", 0)),
            "skipped": int(counts.get("skipped", 0)),
            "failed": int(counts.get("failed", 0)),
        }
        repo.set_last_processed_time(now_est_display())
        stopped = bool(counts.get("stopped_due_to_rate_limit", False))
        status.update(
            label="Stopped early due to Gemini quota/rate limit" if stopped else "Processing complete",
            state="complete",
            expanded=False,
        )
    if stopped:
        st.warning("Stopped early due to Gemini quota/rate limits. Remaining emails were not attempted.")
    st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="AI Email Assistant",
        page_icon="📧",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _inject_styles()
    _init_state()

    settings = get_settings()
    setup_logging(settings.log_level)
    repo = EmailRepository(settings.database_path)

    render_settings_toggle()

    if st.session_state.get("settings_panel_open"):
        panel_col, divider_col, main_col = st.columns([0.9, 0.12, 4.98], gap="medium")
        with panel_col:
            filters = render_settings_panel(repo)
        with divider_col:
            render_vertical_divider()
        with main_col:
            render_main_content(filters, settings, repo)
    else:
        filters = _current_filters()
        render_main_content(filters, settings, repo)


if __name__ == "__main__":
    main()
