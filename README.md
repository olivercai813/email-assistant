# Email Assistant

An AI-powered Gmail inbox assistant that triages unread mail, decides whether each message needs a reply, and drafts responses for you to review before anything is sent. Built with **Google Gemini**, LangGraph, and a Streamlit dashboard.

## Features

- **Gmail Inbox Integration**: Authenticates via OAuth 2.0 and fetches unread messages from your inbox
- **AI-Powered Triage**: Uses **Gemini** to analyze each email and assign a priority, summary, action items, and deadlines
- **Smart Reply Detection**: Determines whether a human reply is genuinely expected or beneficial — drafts are only generated when needed
- **Draft Reply Generation**: Gemini writes a polished reply you can edit, approve, or reject in the dashboard
- **Human-in-the-Loop Sending**: Nothing is sent automatically; outbound mail requires an explicit confirmation checkbox
- **Gmail Label Sync**: Applies priority labels (`AI-High`, `AI-Medium`, `AI-Low`, `AI-Newsletter`) directly in Gmail
- **Interactive Review Dashboard**: Streamlit UI with search, filters, metrics, and tabbed views for triage and bulk review
- **Detailed Email Tracking**:
  - Priority classification (High, Medium, Low, Newsletter)
  - One-line summaries and extracted action items
  - Deadline detection from email body text
  - Reply status lifecycle (pending → approved/rejected → sent)
  - Processing history with skip logic for already-analyzed messages

## Tech Stack

### Application
- **Python 3.12+** — Core runtime
- **Streamlit** — Review dashboard and approval UI
- **Pandas** — Table view and data display

### AI & Workflow
- **Google Gemini** (`gemini-2.5-flash`) — Email analysis and draft reply generation via Google AI Studio
- **LangGraph** — Stateful workflow orchestration (analyze → conditional reply → finalize)
- **LangChain** — LLM abstraction and structured JSON invocation
- **Pydantic** — Configuration and data validation

### Integrations
- **Gmail API** — Message fetch, labeling, and reply sending
- **Google OAuth 2.0** — Secure desktop authentication flow

### Data & Storage
- **SQLite** — Local persistence for processed emails, analysis results, and reply status
- **python-dotenv** — Environment-based configuration

## How It Works

```
Gmail → Gemini analysis → draft (if needed) → dashboard review → send (with your approval)
```

Unread emails are fetched from Gmail, analyzed by Gemini, and saved locally with priority labels. If a reply is recommended, Gemini drafts one for you to review in the Streamlit dashboard. Nothing is sent until you approve it.

## Key Features Explained

### Priority Classification

Gemini assigns one of four priority levels using explicit rules:

- **High** — Forms to complete, school/academic mail, deadlines, urgent requests
- **Medium** — Follow-ups, scheduling, account tasks requiring a response
- **Low** — FYI messages, confirmations, receipts, service notifications
- **Newsletter** — Mass marketing and editorial digests only (not transactional account mail)

### Reply Recommendation

`reply_recommended` is set to `true` only when a human response is genuinely expected or beneficial. The workflow skips draft generation entirely when no reply is needed, saving API quota and keeping the **Needs attention** tab focused on actionable mail.

### Human-in-the-Loop Sending

Every outbound reply goes through a three-step gate:

1. Gemini drafts the reply
2. You edit the text in the dashboard
3. You check "I confirm I want to send this reply" and click **Approve & send**

Rejected drafts are marked `reply_rejected` and never sent.

## Getting Started

**Requirements:** Python 3.12+, Google account, [Gemini API key](https://aistudio.google.com/apikey), Gmail OAuth credentials

```bash
git clone https://github.com/your-username/email-assistant.git
cd email-assistant
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Add your Gemini key to `.env`:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-2.5-flash
```

### Gmail OAuth

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the **Gmail API**
3. Configure the **OAuth consent screen** (External) and add your Gmail as a test user
4. Create an OAuth client ID (**Desktop app**) and download the JSON
5. Save as `credentials/credentials.json`

On first run, a browser window handles sign-in and writes `credentials/token.json`.

### Run

```bash
python run_dashboard.py
```

Open http://localhost:8501. Use the sidebar to process unread emails and review drafts under **Needs attention**.

CLI processing (same pipeline, no UI):

```bash
python run.py
```

Do not run both at once. Lower `MAX_EMAILS_PER_RUN` if you hit Gemini rate limits (429 errors).

## Troubleshooting

| Issue | Fix |
|---|---|
| `credentials.json` not found | Place OAuth JSON in `credentials/` |
| `redirect_uri_mismatch` | Use a Desktop OAuth client, not Web |
| `access_denied` | Add your email as an OAuth test user |
| `invalid_grant` | Delete `credentials/token.json` and sign in again |
| Invalid Gemini key | Create a key at [AI Studio](https://aistudio.google.com/apikey) |
| `429` rate limits | Wait and retry; lower `MAX_EMAILS_PER_RUN` |
| Stale errors in dashboard | Reset database from the sidebar |
| `'app' is not a package` | Run `python run_dashboard.py` from the project root |

## Security

- Do not commit `.env`, `credentials.json`, or `token.json`
- OAuth tokens are stored locally in `credentials/token.json`
- Outbound mail requires explicit dashboard confirmation

## License

MIT
