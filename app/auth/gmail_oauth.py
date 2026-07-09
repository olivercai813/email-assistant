"""Gmail OAuth 2.0 credential management."""

from __future__ import annotations

from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import Settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _run_oauth_flow(credentials_path: Path, scopes: list[str]) -> Credentials:
    logger.info(
        "Starting Gmail OAuth flow. A browser window will open for authorization."
    )
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), scopes)
    return flow.run_local_server(port=0)


def get_gmail_credentials(settings: Settings) -> Credentials:
    """
    Obtain valid Gmail API credentials via OAuth 2.0.

    On first run, opens a browser for user consent and saves the token.
    On subsequent runs, refreshes the token if expired.
    """
    creds: Credentials | None = None
    token_path = settings.gmail_token_path
    credentials_path = settings.gmail_credentials_path

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(
            str(token_path), settings.gmail_scopes
        )

    missing_scopes = creds and not creds.has_scopes(settings.gmail_scopes)
    if missing_scopes:
        logger.info("OAuth token missing required scopes; re-authenticating...")
        if token_path.exists():
            token_path.unlink()
        creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Gmail OAuth token...")
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                # Automatically recover from revoked/expired refresh tokens.
                # Common case: invalid_grant after token revocation or OAuth config change.
                logger.warning(
                    "Gmail token refresh failed (%s). Re-authenticating automatically...",
                    exc,
                )
                if token_path.exists():
                    token_path.unlink()
                    logger.info("Deleted stale Gmail token at %s", token_path)
                creds = _run_oauth_flow(credentials_path, settings.gmail_scopes)
        else:
            creds = _run_oauth_flow(credentials_path, settings.gmail_scopes)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        logger.info("Gmail OAuth token saved to %s", token_path)

    return creds
