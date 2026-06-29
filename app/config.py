"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GROK = "grok"
    GEMINI = "gemini"


class Priority(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    NEWSLETTER = "Newsletter"


# Gmail label names applied to processed emails
PRIORITY_LABELS: dict[Priority, str] = {
    Priority.HIGH: "AI-High",
    Priority.MEDIUM: "AI-Medium",
    Priority.LOW: "AI-Low",
    Priority.NEWSLETTER: "AI-Newsletter",
}


@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    # LLM
    llm_provider: LLMProvider
    openai_api_key: str
    openai_model: str
    anthropic_api_key: str
    anthropic_model: str
    grok_api_key: str
    grok_model: str
    grok_base_url: str
    gemini_api_key: str
    gemini_model: str

    # Gmail
    gmail_credentials_path: Path
    gmail_token_path: Path
    gmail_scopes: list[str]

    # Database
    database_path: Path

    # Processing
    max_emails_per_run: int
    retry_attempts: int
    retry_delay_seconds: float

    # Logging
    log_level: str


def _get_llm_provider() -> LLMProvider:
    provider = os.getenv("LLM_PROVIDER", "openai").lower().strip()
    try:
        return LLMProvider(provider)
    except ValueError:
        raise ValueError(
            f"Invalid LLM_PROVIDER '{provider}'. "
            "Must be 'openai', 'anthropic', 'grok', or 'gemini'."
        )


def get_settings() -> Settings:
    """Load and validate settings from environment variables."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

    return Settings(
        llm_provider=_get_llm_provider(),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        grok_api_key=os.getenv("XAI_API_KEY", os.getenv("GROK_API_KEY", "")),
        grok_model=os.getenv("GROK_MODEL", "grok-3-mini"),
        grok_base_url=os.getenv("GROK_BASE_URL", "https://api.x.ai/v1"),
        gemini_api_key=os.getenv(
            "GEMINI_API_KEY",
            os.getenv("GOOGLE_API_KEY", ""),
        ),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        gmail_credentials_path=Path(
            os.getenv(
                "GMAIL_CREDENTIALS_PATH",
                str(CREDENTIALS_DIR / "credentials.json"),
            )
        ),
        gmail_token_path=Path(
            os.getenv("GMAIL_TOKEN_PATH", str(CREDENTIALS_DIR / "token.json"))
        ),
        gmail_scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.labels",
        ],
        database_path=Path(
            os.getenv("DATABASE_PATH", str(DATA_DIR / "email-assistant.db"))
        ),
        max_emails_per_run=int(os.getenv("MAX_EMAILS_PER_RUN", "20")),
        retry_attempts=int(os.getenv("RETRY_ATTEMPTS", "3")),
        retry_delay_seconds=float(os.getenv("RETRY_DELAY_SECONDS", "2.0")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


def validate_settings(settings: Settings) -> None:
    """Raise ValueError if required settings are missing."""
    if settings.llm_provider == LLMProvider.OPENAI and not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
    if settings.llm_provider == LLMProvider.ANTHROPIC and not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
    if settings.llm_provider == LLMProvider.GROK and not settings.grok_api_key:
        raise ValueError("XAI_API_KEY is required when LLM_PROVIDER=grok")
    if settings.llm_provider == LLMProvider.GEMINI and not settings.gemini_api_key:
        raise ValueError(
            "GEMINI_API_KEY (or GOOGLE_API_KEY) is required when LLM_PROVIDER=gemini"
        )
    if not settings.gmail_credentials_path.exists():
        raise FileNotFoundError(
            f"Gmail credentials not found at {settings.gmail_credentials_path}. "
            "Download credentials.json from Google Cloud Console and place it there."
        )
