# Email Assistant

Python app that reads unread Gmail messages, runs them through a LangGraph workflow with your choice of LLM, and stores structured results in SQLite. A Streamlit dashboard lets you review summaries, edit draft replies, and send mail only after you confirm.

Replies are never sent automatically.

## What it does

- Authenticates with Gmail (OAuth 2.0)
- Fetches unread inbox messages
- For each message: priority, summary, action items, deadlines, optional draft reply
- Applies Gmail labels: `AI-High`, `AI-Medium`, `AI-Low`, `AI-Newsletter`
- Skips messages already in the local database
- Dashboard: search, filter, approve/reject/send

**LLM providers:** Gemini (AI Studio), OpenAI, Anthropic, Grok (xAI)

## Architecture

```
Gmail API  →  LangGraph workflow  →  SQLite
                    ↓
              LLM provider
                    ↓
           Streamlit dashboard
```

Workflow: `analyze_email` → (if reply needed) `generate_reply` → `finalize`

## Project layout

```
email-assistant/
├── app/
│   ├── main.py                 # Processing entry point
│   ├── config.py
│   ├── auth/gmail_oauth.py
│   ├── gmail/client.py
│   ├── database/
│   ├── llm/interface.py
│   ├── prompts/templates.py
│   ├── workflow/
│   └── dashboard/streamlit_app.py
├── credentials/                # credentials.json, token.json (gitignored)
├── data/                       # SQLite DB (gitignored)
├── run.py                      # CLI processor
├── run_dashboard.py
├── requirements.txt
└── .env.example
```

## Setup

**Requirements:** Python 3.12+, Google account, LLM API key

```bash
git clone https://github.com/your-username/email-assistant.git
cd email-assistant
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # then edit with your keys
```

### Gmail OAuth

1. [Google Cloud Console](https://console.cloud.google.com/) → new project
2. Enable **Gmail API**
3. **OAuth consent screen** → External → add your Gmail as a test user
4. **Credentials** → OAuth client ID → **Desktop app** → download JSON
5. Save as `credentials/credentials.json`

On Windows, if the file downloads as `credentials.json.json`, rename it.

First run opens a browser for sign-in and writes `credentials/token.json`. Delete that file to re-authenticate.

### LLM keys

Set `LLM_PROVIDER` and the matching key in `.env`.

**Gemini** (default in `.env.example`):

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-2.5-flash
```

Get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). New keys use an `AQ.` prefix; older keys use `AIza`. `GOOGLE_API_KEY` works as an alias.

Free tier has tight limits (~5 requests/minute, ~20/day for `gemini-2.5-flash`). Use `MAX_EMAILS_PER_RUN=5` for large inboxes. Avoid `gemini-2.0-flash` on free tier (quota is often zero). GCP trial credits do not pay for AI Studio usage.

**OpenAI:**

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

**Anthropic:**

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-20250514
```

**Grok (xAI):**

```env
LLM_PROVIDER=grok
XAI_API_KEY=xai-...
GROK_MODEL=grok-3-mini
```

Grok (xAI) is not Groq (`gsk_...` keys). Groq is unsupported.

## Configuration

| Variable | Description | Default |
|---|---|---|
| `LLM_PROVIDER` | `openai`, `anthropic`, `grok`, `gemini` | `openai` |
| `GEMINI_API_KEY` | AI Studio API key | — |
| `GEMINI_MODEL` | Gemini model | `gemini-2.5-flash` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `OPENAI_MODEL` | OpenAI model | `gpt-4o-mini` |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `ANTHROPIC_MODEL` | Anthropic model | `claude-sonnet-4-20250514` |
| `XAI_API_KEY` | xAI API key | — |
| `GROK_MODEL` | Grok model | `grok-3-mini` |
| `GROK_BASE_URL` | xAI base URL | `https://api.x.ai/v1` |
| `GMAIL_CREDENTIALS_PATH` | OAuth credentials file | `credentials/credentials.json` |
| `GMAIL_TOKEN_PATH` | Saved OAuth token | `credentials/token.json` |
| `DATABASE_PATH` | SQLite path | `data/email-assistant.db` |
| `MAX_EMAILS_PER_RUN` | Emails per run | `20` |
| `RETRY_ATTEMPTS` | LLM retry count | `3` |
| `RETRY_DELAY_SECONDS` | Retry backoff (seconds) | `2.0` |
| `LOG_LEVEL` | Log level | `INFO` |

## Running

**Dashboard** (recommended):

```bash
python run_dashboard.py
```

Open http://localhost:8501. Use the sidebar to process unread mail, filter results, and reset the database to reprocess. Reply actions are under the **Needs attention** tab.

**CLI:**

```bash
python run.py
```

Same processor as the dashboard button. Do not run both at once.

Processing can take a while on Gemini free tier due to rate limits. Already-processed messages are skipped until you reset the database.

## Troubleshooting

| Issue | Fix |
|---|---|
| `credentials.json` not found | Place OAuth JSON in `credentials/` |
| `redirect_uri_mismatch` | Use a Desktop OAuth client, not Web |
| `access_denied` | Add your email as OAuth test user |
| `invalid_grant` | Delete `credentials/token.json`, sign in again |
| Gemini `API key not valid` | Use an AI Studio key (`AQ.` or `AIza`), not GCP OAuth credentials |
| Gemini `429 RESOURCE_EXHAUSTED` | Rate limit; wait, lower `MAX_EMAILS_PER_RUN`, retry later |
| Stale errors in dashboard | Reset database in sidebar, or delete `data/email-assistant.db` |
| `'app' is not a package` | Run `python run_dashboard.py`, not `streamlit run` directly |
| Database locked | Only one processor at a time |

## Security

- Do not commit `.env`, `credentials.json`, or `token.json`
- OAuth tokens stay in `credentials/token.json` locally
- Sending requires an explicit checkbox in the dashboard

## License

MIT
