# email-assistant

A production-ready Python application that connects to Gmail, processes unread emails through a **LangGraph** workflow powered by OpenAI, Anthropic, Grok (xAI), or **Gemini** (Google AI Studio), assigns priority labels, generates structured summaries and draft replies, and provides a **Streamlit dashboard** for review and approval.

> **Important:** This application **never sends emails automatically**. All AI-generated replies require explicit user confirmation in the dashboard before being sent.

---

## Features

- **Gmail OAuth 2.0** authentication with token refresh
- **Unread email retrieval** via the Gmail API
- **LangGraph workflow** for multi-step email analysis and reply generation
- **Configurable LLM provider** — OpenAI, Anthropic, Grok, or Gemini via environment variables
- **Structured JSON output** for each email:
  - Priority (High, Medium, Low, Newsletter)
  - Concise summary
  - Action items
  - Deadlines
  - Reply recommendation
- **Professional draft replies** for emails that need a response
- **Gmail label application** based on assigned priority (`AI-High`, `AI-Medium`, `AI-Low`, `AI-Newsletter`)
- **SQLite persistence** to prevent duplicate processing and maintain history
- **Streamlit dashboard** with metrics, search, and approve/reject controls
- **Retry logic**, structured logging, and type hints throughout

---

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Gmail API      │────▶│  LangGraph       │────▶│  SQLite DB      │
│  (OAuth 2.0)    │     │  Workflow        │     │  (history)      │
└─────────────────┘     └────────┬─────────┘     └─────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │  LLM Provider    │
                        │  OpenAI/Anthropic│
                        │  /Grok/Gemini    │
                        └──────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Streamlit Dashboard                                            │
│  • Metrics  • Search  • Review drafts  • Approve/Reject/Send   │
└─────────────────────────────────────────────────────────────────┘
```

### LangGraph Workflow

```
analyze_email ──▶ [reply_recommended?] ──yes──▶ generate_reply ──▶ finalize
                      │
                      no
                      └──────────────────────────────────────────▶ finalize
```

---

## Folder Structure

```
email-assistant/
├── app/
│   ├── __init__.py
│   ├── config.py              # Environment-based configuration
│   ├── main.py                # Email processing orchestrator
│   ├── auth/
│   │   └── gmail_oauth.py     # OAuth 2.0 credential management
│   ├── gmail/
│   │   └── client.py          # Gmail API wrapper
│   ├── database/
│   │   ├── models.py          # Data models and enums
│   │   └── repository.py      # SQLite data access layer
│   ├── llm/
│   │   └── interface.py       # Configurable LLM provider
│   ├── prompts/
│   │   └── templates.py       # Prompt templates
│   ├── workflow/
│   │   ├── state.py           # LangGraph state definitions
│   │   └── graph.py           # LangGraph workflow graph
│   ├── dashboard/
│   │   └── streamlit_app.py   # Streamlit dashboard
│   └── utils/
│       ├── logging.py         # Logging setup
│       └── retry.py           # Retry decorator
├── credentials/               # Place credentials.json here (gitignored)
├── data/                      # SQLite database (gitignored)
├── .env.example               # Environment variable template
├── .gitignore
├── requirements.txt
├── run.py                     # CLI: process unread emails
├── run_dashboard.py           # Launch Streamlit dashboard
└── README.md
```

---

## Installation

### Prerequisites

- Python 3.12 or higher
- A Google account with Gmail
- An LLM API key — currently uses **Gemini** (free tier via [AI Studio](https://aistudio.google.com/apikey))

### 1. Clone the repository

```bash
git clone https://github.com/your-username/email-assistant.git
cd email-assistant
```

### 2. Create a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your API keys and preferences (see [Configuration](#configuration) below).

---

## Google Cloud & Gmail API Setup

Follow these steps if you have never configured Gmail OAuth before.

### Step 1: Create a Google Cloud Project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project dropdown at the top and select **New Project**.
3. Enter a project name (e.g., `email-assistant`) and click **Create**.
4. Make sure your new project is selected in the project dropdown.

### Step 2: Enable the Gmail API

1. In the Cloud Console, go to **APIs & Services → Library**.
2. Search for **Gmail API**.
3. Click on it and press **Enable**.

### Step 3: Configure the OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**.
2. Choose **External** (unless you have a Google Workspace org) and click **Create**.
3. Fill in the required fields:
   - **App name:** email-assistant
   - **User support email:** your email
   - **Developer contact email:** your email
4. Click **Save and Continue** through the Scopes and Test Users steps.
5. On the **Test users** step, click **Add Users** and add your Gmail address.
6. Click **Save and Continue**, then **Back to Dashboard**.

> While the app is in "Testing" mode, only test users you add can authenticate.

### Step 4: Create OAuth Desktop Credentials

1. Go to **APIs & Services → Credentials**.
2. Click **Create Credentials → OAuth client ID**.
3. Select **Application type: Desktop app**.
4. Name it (e.g., `email-assistant-desktop`) and click **Create**.
5. Click **Download JSON** to download the credentials file.

### Step 5: Place `credentials.json`

Move the downloaded file to the `credentials/` directory and rename it:

```
email-assistant/credentials/credentials.json
```

> **Windows tip:** If your browser saves the file as `credentials.json.json`, rename it to `credentials.json`.

> This file is gitignored. Never commit it to version control.

### How the OAuth Flow Works

1. On first run, the application reads `credentials/credentials.json`.
2. A browser window opens asking you to sign in to Google and grant permissions.
3. After you approve, a `credentials/token.json` file is created automatically.
4. On subsequent runs, the stored token is reused. If it expires, it is refreshed automatically.
5. If authentication fails, delete `credentials/token.json` and run again to re-authenticate.

---

## LLM API Keys

### Gemini (Google AI Studio) — recommended for free tier

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
2. Sign in and click **Create API key** (select or create a Google Cloud project).
3. Copy the key and set it in `.env`:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=AQ....your-key-here
GEMINI_MODEL=gemini-2.5-flash
```

**Key format:** New keys from AI Studio start with `AQ.` (auth keys). Older keys start with `AIza`. Both work with this app.

**Free tier limits:** Gemini free tier has strict rate limits (e.g. 5 requests/minute for `gemini-2.5-flash`). Each email uses 1–2 API calls. For large inboxes, set `MAX_EMAILS_PER_RUN=5` and run multiple times, waiting a minute between runs.

**Model note:** Avoid `gemini-2.0-flash` on the free tier — its quota is often `0`. Use `gemini-2.5-flash` instead.

**Billing note:** Google Cloud's $300 trial credits do **not** apply to AI Studio Gemini usage. Gmail OAuth and Gemini API are separate billing systems.

`GOOGLE_API_KEY` also works as an alias for `GEMINI_API_KEY`.

### OpenAI

1. Go to [platform.openai.com](https://platform.openai.com/).
2. Sign up or log in.
3. Navigate to **API Keys** and click **Create new secret key**.
4. Copy the key and set it in `.env`:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

### Anthropic

1. Go to [console.anthropic.com](https://console.anthropic.com/).
2. Sign up or log in.
3. Navigate to **API Keys** and create a new key.
4. Copy the key and set it in `.env`:

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-20250514
```

### Grok (xAI)

1. Go to [console.x.ai](https://console.x.ai/).
2. Sign up or log in.
3. Navigate to **API Keys** and create a new key.
4. Copy the key and set it in `.env`:

```env
LLM_PROVIDER=grok
XAI_API_KEY=xai-...
GROK_MODEL=grok-3-mini
```

Other Grok models include `grok-3`, `grok-3-fast`, and `grok-2-1212`.

> **Don't confuse Grok with Groq:** Grok is xAI (`xai-...` keys at [console.x.ai](https://console.x.ai/)). Groq is a different service (`gsk_...` keys) and is not supported by this app.

---

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Description | Default |
|---|---|---|
| `LLM_PROVIDER` | `openai`, `anthropic`, `grok`, or `gemini` | `openai` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `OPENAI_MODEL` | OpenAI model name | `gpt-4o-mini` |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `ANTHROPIC_MODEL` | Anthropic model name | `claude-sonnet-4-20250514` |
| `XAI_API_KEY` | xAI (Grok) API key | — |
| `GROK_MODEL` | Grok model name | `grok-3-mini` |
| `GROK_BASE_URL` | xAI API base URL | `https://api.x.ai/v1` |
| `GEMINI_API_KEY` | Google AI Studio API key (`AQ.` or `AIza`) | — |
| `GEMINI_MODEL` | Gemini model name | `gemini-2.5-flash` |
| `GMAIL_CREDENTIALS_PATH` | Path to OAuth credentials | `credentials/credentials.json` |
| `GMAIL_TOKEN_PATH` | Path to saved OAuth token | `credentials/token.json` |
| `DATABASE_PATH` | SQLite database path | `data/email-assistant.db` |
| `MAX_EMAILS_PER_RUN` | Max unread emails per run | `20` |
| `RETRY_ATTEMPTS` | API retry attempts | `3` |
| `RETRY_DELAY_SECONDS` | Base retry delay (seconds) | `2.0` |
| `LOG_LEVEL` | Logging level | `INFO` |

---

## Running the Application

### Process unread emails (CLI)

```bash
python run.py
```

Or:

```bash
python -m app.main
```

This will:
1. Authenticate with Gmail
2. Fetch unread inbox emails
3. Skip any already processed (tracked in SQLite)
4. Run each email through the LangGraph workflow
5. Apply priority labels in Gmail
6. Save results to the database

Already-processed emails are skipped on subsequent runs. If a run fails partway through, re-run `python run.py` — it picks up where it left off.

### Launch the Streamlit dashboard

```bash
python run_dashboard.py
```

Open your browser at **http://localhost:8501**.

> Use `python run_dashboard.py` rather than `streamlit run app/dashboard/streamlit_app.py` directly — the launcher sets the correct Python path.

You can run the dashboard in a **second terminal** while `python run.py` is processing emails. Use the dashboard to view results; avoid clicking **Process Unread Emails** while a CLI run is already in progress.

---

## Dashboard Overview

The Streamlit dashboard provides:

### Metrics Bar
- **Total Processed** — all emails processed by the assistant
- **High / Medium / Low / Newsletter** — counts by priority
- **Pending Replies** — emails awaiting your approval

### Sidebar
- **Process Unread Emails** — triggers a new processing run
- **Search** — filter by subject, sender, or summary
- **Priority & Status filters**

### Email Detail View
Each processed email expands to show:
- Priority badge (color-coded)
- Processing status and timestamps
- AI-generated summary
- Action items and deadlines
- Draft reply (editable)
- **Approve & Send** — requires checkbox confirmation; sends via Gmail API
- **Reject** — marks the draft as rejected without sending

### Expected Interface

```
┌──────────────────────────────────────────────────────────────┐
│  📧 email-assistant                                            │
├──────────┬───────────────────────────────────────────────────┤
│ Actions  │  Total: 42  │ High: 5 │ Medium: 12 │ Low: 20 │ … │
│          ├───────────────────────────────────────────────────┤
│ Process  │  ▼ Project Update — alice@company.com (High)     │
│ Unread   │     Summary: Alice needs the Q3 report by Friday   │
│          │     Action Items: • Prepare Q3 report              │
│ Filters  │     Draft Reply: [editable text area]              │
│          │     ☑ I confirm I want to send this reply          │
│ Search   │     [✅ Approve & Send]  [❌ Reject]               │
└──────────┴───────────────────────────────────────────────────┘
```

---

## Troubleshooting

### OAuth & Gmail Issues

| Problem | Solution |
|---|---|
| `credentials.json` not found | Download OAuth credentials from Google Cloud Console and place in `credentials/` |
| `redirect_uri_mismatch` | Ensure you created a **Desktop app** OAuth client, not Web |
| `access_denied` | Add your Gmail address as a test user in the OAuth consent screen |
| `invalid_grant` | Delete `credentials/token.json` and re-authenticate |
| Browser doesn't open during OAuth | Run `python run.py` from your terminal; ensure a default browser is configured |
| `insufficientPermissions` | Delete `token.json`, re-auth, and ensure all Gmail scopes are granted |

### API & Environment Issues

| Problem | Solution |
|---|---|
| `OPENAI_API_KEY is required` | Set `OPENAI_API_KEY` in `.env` when `LLM_PROVIDER=openai` |
| `ANTHROPIC_API_KEY is required` | Set `ANTHROPIC_API_KEY` in `.env` when `LLM_PROVIDER=anthropic` |
| `XAI_API_KEY is required` | Set `XAI_API_KEY` in `.env` when `LLM_PROVIDER=grok` |
| `GEMINI_API_KEY is required` | Set `GEMINI_API_KEY` in `.env` when `LLM_PROVIDER=gemini` |
| `API key not valid` (Gemini) | Create a new key at [AI Studio](https://aistudio.google.com/apikey). Use the full `AQ.` or `AIza` key — not GCP OAuth credentials. |
| `429 RESOURCE_EXHAUSTED` (Gemini) | Free-tier rate limit hit. Wait 1 minute, reduce `MAX_EMAILS_PER_RUN` (e.g. `5`), and re-run. |
| `limit: 0` for `gemini-2.0-flash` | Switch to `GEMINI_MODEL=gemini-2.5-flash` in `.env`. |
| Dashboard shows old errors for all emails | Failed runs are saved to the database. Delete `data/email-assistant.db` to start fresh, or re-run after fixing the API key. |
| `'app' is not a package` (dashboard) | Launch with `python run_dashboard.py` from the project root. |
| LLM returns invalid JSON | Try a more capable model (e.g., `gpt-4o` or `claude-sonnet-4-20250514`) |
| Rate limit errors | Reduce `MAX_EMAILS_PER_RUN` or increase `RETRY_DELAY_SECONDS` |
| Database locked | Ensure only one processor instance runs at a time |

---

## Security Notes

- Never commit `.env`, `credentials.json`, or `token.json` to version control.
- The application requires explicit user confirmation before sending any email.
- OAuth tokens are stored locally in `credentials/token.json`.
- Use the minimum Gmail API scopes needed for the application's functionality.

---

## License

MIT
