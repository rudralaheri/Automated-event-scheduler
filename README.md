# Mail → Calendar Agent — Windows Setup Guide

This agent scans your Gmail, adds events to Google Calendar with priority colours,
and opens a browser review page for organisational/misc emails.

**Built with [CrewAI](https://docs.crewai.com/)** — a lightweight AI agent framework
that provides Agent / Task / Tool / Crew abstractions on top of Google Gemini 2.5 Flash.

---

## Agent Framework (CrewAI)

The agent is structured using CrewAI's core building blocks:

| Component | What it does |
|---|---|
| **Agent** | *Email-to-Calendar Assistant* — reasons about emails using Gemini LLM |
| **Tool 1** | `fetch_emails_tool` — pulls latest emails from Gmail API |
| **Tool 2** | `add_event_tool` — creates a Google Calendar event |
| **Tool 3** | `save_review_page_tool` — generates & opens the HTML review page |
| **Task 1** | Scan — fetch emails from inbox |
| **Task 2** | Classify & Add — prioritise events, auto-add personal ones to calendar |
| **Task 3** | Review — save organisational items to the review page |
| **Crew** | Orchestrates the agent through all three tasks sequentially |

---

## What you'll need

- Python 3.10 or newer → https://www.python.org/downloads/
- An Anthropic API key → https://console.anthropic.com/
- A Google Cloud project (free) for Gmail + Calendar API access

Total setup time: ~15 minutes.

---

## Step 1 — Copy files & install Python packages

1. Create a folder anywhere, e.g. `C:\Users\YourName\mail_calendar_agent`
2. Copy `agent.py`, `requirements.txt`, and `run_agent.bat` into that folder
3. Open **Command Prompt** (`Win + R` → type `cmd` → Enter)
4. Run:

```
cd C:\Users\YourName\mail_calendar_agent
pip install -r requirements.txt
```

---

## Step 2 — Get your Google credentials (one-time)

1. Go to https://console.cloud.google.com/
2. Click **"Create Project"** → name it anything (e.g. `MailCalendarAgent`) → Create
3. In the left menu go to **APIs & Services → Library**
4. Search for **"Gmail API"** → Enable it
5. Search for **"Google Calendar API"** → Enable it
6. Go to **APIs & Services → OAuth consent screen**
   - Choose **External** → Fill in app name (anything) → Save
   - Under **Scopes** click "Add or Remove Scopes" → add these two:
     - `https://www.googleapis.com/auth/gmail.readonly`
     - `https://www.googleapis.com/auth/calendar.events`
   - Under **Test users** → add your own Gmail address → Save
7. Go to **APIs & Services → Credentials**
   - Click **"+ Create Credentials"** → **OAuth client ID**
   - Application type: **Desktop app** → Name it anything → Create
   - Click **Download JSON** on the new credential
   - Rename the downloaded file to `credentials.json`
   - Move it into your `mail_calendar_agent` folder

---

## Step 3 — Get your free Gemini API key

1. Go to https://aistudio.google.com/apikey (sign in with any Google account)
2. Click **"Create API key"** → copy the key shown
3. Open **Start → search "Environment Variables"** → click "Edit the system environment variables"
4. Click **"Environment Variables…"** → Under "User variables" click **New**
   - Variable name:  `GEMINI_API_KEY`
   - Variable value: `AIza...your key here...`
5. Click OK on all dialogs
6. **Restart your Command Prompt** after this step

> **Free tier limits** (as of 2025): 1,500 requests/day and 1 million tokens/minute on
> `gemini-2.0-flash` — far more than enough for twice-daily email scans.

---

## Step 4 — First run (authorise Google)

In Command Prompt:

```
cd C:\Users\YourName\mail_calendar_agent
python agent.py
```

A browser window will open asking you to sign in with Google and grant access.
Do that once — it saves a `token.json` file so future runs are fully automatic.

After authorising you'll see the agent scan your emails and output results.

---

## Step 5 — Edit run_agent.bat

Open `run_agent.bat` in Notepad and update the two paths:

```bat
SET AGENT_DIR=C:\Users\YourName\mail_calendar_agent
SET PYTHON=C:\Users\YourName\AppData\Local\Programs\Python\Python312\python.exe
```

To find your Python path, run this in Command Prompt:
```
where python
```

---

## Step 6 — Schedule it to run twice a day (Task Scheduler)

1. Press `Win + S` → search **"Task Scheduler"** → Open it
2. In the right panel click **"Create Basic Task…"**
3. Name: `Mail Calendar Agent` → Next
4. Trigger: **Daily** → Next
5. Set start time: `08:00 AM` → Next
6. Action: **Start a program** → Next
7. Program/script: Browse to your `run_agent.bat` file → Next → Finish

**Add the second daily run (8 PM):**
1. Find the task you just created in the Task Scheduler Library
2. Right-click → **Properties** → **Triggers** tab → **New**
3. Set it to **Daily** at `08:00 PM` → OK

That's it — the agent now runs at 8 AM and 8 PM every day with no action needed from you.

---

## How it works

| Event type | What happens |
|---|---|
| Direct invite / personal email | Automatically added to Google Calendar |
| 🔴 High priority (compulsory, mandatory, urgent…) | Added in **red** |
| 🟠 Medium priority (meetings, calls, reviews) | Added in **orange** |
| 🔵 Low priority (optional webinars, casual invites) | Added in **teal** |
| Organisational / newsletter / no-reply | Saved to `pending_review.html` — browser opens for you to decide |

---

## Files in this folder

```
mail_calendar_agent/
├── agent.py              ← main script
├── requirements.txt      ← Python dependencies
├── run_agent.bat         ← called by Task Scheduler
├── credentials.json      ← your Google OAuth file (you add this)
├── token.json            ← auto-created after first login
├── pending_review.html   ← auto-created, opens in browser
└── agent.log             ← log of every run
```

---

## Changing number of emails scanned

Open `agent.py` and edit line:
```python
EMAILS_TO_SCAN  = 20
```

---

## Troubleshooting

**"credentials.json not found"**
→ Make sure you downloaded it from Google Cloud and placed it in the same folder as `agent.py`.

**"GEMINI_API_KEY not set"**
→ Re-check Step 3 and restart your terminal.

**Browser doesn't open for Google login**
→ Run `python agent.py` manually from Command Prompt — it always opens a browser on first run.

**Task Scheduler runs but nothing happens**
→ Check `agent.log` in the folder — it records every run and any errors.
