"""
Mail → Calendar Agent  (CrewAI edition)
Scans Gmail, classifies events by priority, auto-adds to Google Calendar,
and saves organisational/misc events to a local HTML review page.

Framework : CrewAI (Agent → Tools → Tasks → Crew)
LLM       : Google Gemini 2.5 Flash  (via LiteLLM integration)
"""

import os
import json
import base64
import webbrowser
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR         = Path(__file__).parent
TOKEN_FILE       = BASE_DIR / "token.json"
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
INBOX_FILE       = BASE_DIR / "pending_review.html"
LOG_FILE         = BASE_DIR / "agent.log"
EMAILS_TO_SCAN   = 20          # change as needed

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

# Google Calendar colorId mapping
COLOR_IDS = {"high": "11", "medium": "6", "low": "7"}
COLOR_HEX = {"high": "#ef4444", "medium": "#f97316", "low": "#3b82f6"}

# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ── Google Auth ───────────────────────────────────────────────────────────────

def get_google_services():
    """Authenticate once, cache token.json for future runs."""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    "credentials.json not found. Follow README.md step 2 to create it."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        log("Google authentication successful — token saved.")
    gmail    = build("gmail",    "v1", credentials=creds)
    calendar = build("calendar", "v3", credentials=creds)
    return gmail, calendar

# ── Gmail helpers ─────────────────────────────────────────────────────────────

def decode_body(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    except Exception:
        return ""

def get_email_text(payload) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        return decode_body(payload.get("body", {}).get("data", ""))
    if mime.startswith("multipart"):
        for part in payload.get("parts", []):
            text = get_email_text(part)
            if text:
                return text
    return ""

def fetch_emails(gmail_service, count: int) -> list[dict]:
    """Return the latest `count` emails as plain dicts."""
    result = gmail_service.users().messages().list(
        userId="me", maxResults=count
    ).execute()
    messages = result.get("messages", [])
    emails = []
    for m in messages:
        msg = gmail_service.users().messages().get(
            userId="me", id=m["id"], format="full"
        ).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        body = get_email_text(msg["payload"])[:2000]   # cap to save tokens
        emails.append({
            "id":      m["id"],
            "from":    headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date":    headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
            "body":    body,
        })
    log(f"Fetched {len(emails)} emails from Gmail.")
    return emails

# ── Calendar helpers ──────────────────────────────────────────────────────────

def build_event_body(ev: dict, priority: str) -> dict:
    """Build a Google Calendar event resource dict."""
    color_id = COLOR_IDS.get(priority, "7")

    if ev.get("start_time") and ev.get("date"):
        start = {"dateTime": f"{ev['date']}T{ev['start_time']}:00", "timeZone": "Asia/Kolkata"}
        if ev.get("end_time"):
            end = {"dateTime": f"{ev['date']}T{ev['end_time']}:00", "timeZone": "Asia/Kolkata"}
        else:
            dt = datetime.fromisoformat(f"{ev['date']}T{ev['start_time']}:00")
            end_dt = dt + timedelta(hours=1)
            end = {"dateTime": end_dt.isoformat(), "timeZone": "Asia/Kolkata"}
    else:
        start = {"date": ev.get("date", datetime.today().strftime("%Y-%m-%d"))}
        end   = {"date": ev.get("date", datetime.today().strftime("%Y-%m-%d"))}

    body = {
        "summary":     ev["title"],
        "description": ev.get("description", ""),
        "start":       start,
        "end":         end,
        "colorId":     color_id,
    }
    if ev.get("location"):
        body["location"] = ev["location"]
    return body

def add_to_calendar(calendar_service, ev: dict, priority: str) -> bool:
    """Create a calendar event.  Returns True on success."""
    try:
        body = build_event_body(ev, priority)
        calendar_service.events().insert(calendarId="primary", body=body).execute()
        log(f"  ✅ Added [{priority.upper()}]: {ev['title']} on {ev.get('date','?')}")
        return True
    except Exception as exc:
        log(f"  ❌ Failed to add '{ev['title']}': {exc}")
        return False

# ── HTML Review Page ──────────────────────────────────────────────────────────

def gcal_url(ev: dict) -> str:
    """Build a Google Calendar quick-add URL."""
    date = (ev.get("date") or "").replace("-", "")
    st   = (ev.get("start_time") or "").replace(":", "")
    et   = (ev.get("end_time")   or "").replace(":", "")

    if date and st:
        dates = f"{date}T{st}00Z/{date}T{et or st}00Z"
    elif date:
        dates = f"{date}/{date}"
    else:
        dates = ""

    params = {
        "action":   "TEMPLATE",
        "text":     ev.get("title", ""),
        "details":  ev.get("description", ""),
        "location": ev.get("location", ""),
        "dates":    dates,
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(params)

def generate_review_html(inbox_items: list[dict], summary: str) -> str:
    if not inbox_items:
        cards_html = """
        <div class="empty">
          <div class="empty-icon">📭</div>
          <p>Nothing to review — inbox is clear!</p>
        </div>"""
    else:
        cards = []
        for item in inbox_items:
            p = item.get("suggested_priority", "low")
            hex_color = COLOR_HEX.get(p, "#3b82f6")
            icon = {"high": "🔴", "medium": "🟠", "low": "🔵"}.get(p, "🔵")
            url  = gcal_url(item)
            meta_parts = []
            if item.get("date"):       meta_parts.append(f"📆 {item['date']}")
            if item.get("start_time"): meta_parts.append(f"🕐 {item['start_time']}" + (f"–{item['end_time']}" if item.get("end_time") else ""))
            if item.get("location"):   meta_parts.append(f"📍 {item['location']}")
            if item.get("from"):       meta_parts.append(f"✉️ {item['from']}")
            meta_html = "  ·  ".join(meta_parts)

            cards.append(f"""
        <div class="card" style="border-left-color:{hex_color}">
          <div class="card-top">
            <div>
              <div class="card-title">{item['title']}</div>
              <div class="card-meta">{meta_html}</div>
              <div class="card-reason">⚠️ {item.get('review_reason','Organisational email')}</div>
            </div>
            <span class="badge" style="background:{hex_color}22;color:{hex_color};border:1px solid {hex_color}44">
              {icon} {p.capitalize()}
            </span>
          </div>
          <div class="card-actions">
            <a href="{url}" target="_blank" class="btn-add" style="background:{hex_color}">
              ＋ Add to Google Calendar
            </a>
          </div>
          <div class="card-desc">{item.get('description','')}</div>
        </div>""")
        cards_html = "\n".join(cards)

    now = datetime.now().strftime("%d %b %Y, %I:%M %p")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mail → Calendar · Review Inbox</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono&display=swap');
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'DM Sans', sans-serif;
    background: #0c0e14;
    color: #e2e8f0;
    min-height: 100vh;
    padding: 40px 20px;
  }}
  .container {{ max-width: 620px; margin: 0 auto; }}
  header {{ text-align: center; margin-bottom: 32px; }}
  .logo {{ font-size: 28px; margin-bottom: 10px; }}
  h1 {{ font-size: 24px; font-weight: 700; letter-spacing: -0.5px; margin-bottom: 6px; }}
  .sub {{ color: #4b5563; font-size: 13px; }}
  .run-info {{
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px; padding: 10px 16px;
    font-size: 12px; color: #6b7280;
    margin-bottom: 28px; text-align: center;
  }}
  .summary {{
    background: rgba(99,102,241,0.08);
    border: 1px solid rgba(99,102,241,0.2);
    border-radius: 8px; padding: 12px 16px;
    font-size: 13px; color: #a5b4fc;
    margin-bottom: 24px;
  }}
  .section-label {{
    font-size: 11px; color: #4b5563; letter-spacing: 1px;
    text-transform: uppercase; font-weight: 600; margin-bottom: 12px;
  }}
  .card {{
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.08);
    border-left: 3px solid #3b82f6;
    border-radius: 10px; padding: 16px;
    margin-bottom: 12px; transition: background 0.15s;
  }}
  .card:hover {{ background: rgba(255,255,255,0.05); }}
  .card-top {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 10px; }}
  .card-title {{ font-weight: 600; font-size: 15px; margin-bottom: 4px; }}
  .card-meta {{ font-size: 12px; color: #6b7280; margin-bottom: 4px; }}
  .card-reason {{ font-size: 11px; color: #4b5563; font-style: italic; }}
  .card-desc {{ font-size: 12px; color: #4b5563; margin-top: 8px; line-height: 1.5; }}
  .badge {{
    font-size: 10px; font-weight: 700; letter-spacing: 0.8px;
    text-transform: uppercase; padding: 3px 9px;
    border-radius: 20px; white-space: nowrap; flex-shrink: 0;
  }}
  .card-actions {{ display: flex; gap: 8px; }}
  .btn-add {{
    display: inline-block; padding: 8px 18px; border-radius: 7px;
    font-size: 13px; font-weight: 600; color: #fff;
    text-decoration: none; transition: opacity 0.15s;
  }}
  .btn-add:hover {{ opacity: 0.85; }}
  .empty {{ text-align: center; padding: 60px 0; color: #4b5563; }}
  .empty-icon {{ font-size: 40px; margin-bottom: 12px; }}
  footer {{ text-align: center; color: #1f2937; font-size: 11px; margin-top: 40px; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="logo">✉️ → 📅</div>
    <h1>Review Inbox</h1>
    <p class="sub">Organisational &amp; misc events — decide what to add</p>
  </header>
  <div class="run-info">Last scanned: {now}</div>
  {'<div class="summary">📋 ' + summary + '</div>' if summary else ''}
  <div class="section-label">{len(inbox_items)} item{"s" if len(inbox_items) != 1 else ""} pending review</div>
  {cards_html}
  <footer>Generated by Mail → Calendar Agent (CrewAI) · Running locally on Windows</footer>
</div>
</body>
</html>"""

# ── Gemini API Key ────────────────────────────────────────────────────────────

def get_gemini_api_key() -> str:
    """
    Look for the Gemini API key in two places (in order):
      1. config.txt in the same folder as agent.py
      2. GEMINI_API_KEY environment variable
    """
    config_file = BASE_DIR / "config.txt"
    if config_file.exists():
        key = config_file.read_text(encoding="utf-8").strip()
        if key and not key.startswith("#"):
            return key
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    raise EnvironmentError(
        "Gemini API key not found.\n"
        "Easiest fix: create a file called config.txt in the same folder as agent.py\n"
        "and paste your API key as the only line in that file.\n"
        "Get a free key at: https://aistudio.google.com/apikey"
    )

# ══════════════════════════════════════════════════════════════════════════════
#  CrewAI  ─  Tools, Agent, Tasks, Crew
# ══════════════════════════════════════════════════════════════════════════════

# We authenticate once and share the service objects via module-level variables
# so that every tool can use them without re-authenticating.
_gmail_svc = None
_cal_svc   = None

def _ensure_google_services():
    global _gmail_svc, _cal_svc
    if _gmail_svc is None or _cal_svc is None:
        _gmail_svc, _cal_svc = get_google_services()

# ── Tool 1: Fetch Emails ─────────────────────────────────────────────────────

@tool("Fetch Emails from Gmail")
def fetch_emails_tool(count: int = 20) -> str:
    """Fetch the latest emails from the user's Gmail inbox.
    Returns a JSON string containing a list of email objects with
    id, from, subject, date, snippet, and body fields.
    The 'count' parameter controls how many emails to fetch (default 20).
    """
    _ensure_google_services()
    emails = fetch_emails(_gmail_svc, count)
    return json.dumps(emails, indent=2, ensure_ascii=False)

# ── Tool 2: Add Event to Calendar ────────────────────────────────────────────

@tool("Add Event to Google Calendar")
def add_event_tool(event_json: str) -> str:
    """Add a single event to the user's Google Calendar.
    Expects a JSON string with these fields:
      title (str), date (YYYY-MM-DD), start_time (HH:MM or null),
      end_time (HH:MM or null), location (str or null),
      description (str), priority (high|medium|low).
    Returns a success or failure message.
    """
    _ensure_google_services()
    try:
        ev = json.loads(event_json)
    except json.JSONDecodeError:
        return "Error: could not parse event JSON."

    priority = ev.get("priority", "low")
    ok = add_to_calendar(_cal_svc, ev, priority)
    if ok:
        return f"Successfully added '{ev.get('title','')}' to Google Calendar with {priority.upper()} priority."
    return f"Failed to add '{ev.get('title','')}' to Google Calendar."

# ── Tool 3: Save Review Page ─────────────────────────────────────────────────

@tool("Save Inbox Review Page")
def save_review_page_tool(inbox_json: str, summary: str = "") -> str:
    """Save organisational/misc events to a local HTML review page and open it
    in the browser so the user can decide which to add manually.
    Expects 'inbox_json' as a JSON array of event objects, each with:
      id, title, date, start_time, end_time, location, description,
      from, suggested_priority, review_reason.
    'summary' is an optional one-line summary shown at the top of the page.
    Returns a confirmation message.
    """
    try:
        inbox_items = json.loads(inbox_json)
    except json.JSONDecodeError:
        return "Error: could not parse inbox JSON."

    html = generate_review_html(inbox_items, summary)
    INBOX_FILE.write_text(html, encoding="utf-8")
    log(f"Review page saved → {INBOX_FILE}")

    if inbox_items:
        log(f"Opening review page in browser ({len(inbox_items)} items)…")
        webbrowser.open(INBOX_FILE.as_uri())
        return f"Saved and opened review page with {len(inbox_items)} item(s) for manual review."
    return "No inbox items to review — review page updated (empty)."

# ── LLM Setup ─────────────────────────────────────────────────────────────────

def _build_llm() -> LLM:
    """Create a CrewAI LLM pointing at Gemini 2.5 Flash."""
    api_key = get_gemini_api_key()
    return LLM(
        model="gemini/gemini-2.5-flash",
        api_key=api_key,
    )

# ── Agent Definition ──────────────────────────────────────────────────────────

AGENT_BACKSTORY = (
    "You are a smart email-to-calendar assistant. You scan a user's Gmail, "
    "identify any events or meetings, classify them by priority, and decide "
    "whether to auto-add them to Google Calendar or hold them for manual review.\n\n"
    "## Priority Rules\n"
    "- HIGH (red): compulsory, mandatory, must attend, required, urgent, critical, "
    "deadline, final, last chance, attendance required, action required\n"
    "- MEDIUM (orange): direct meeting invites, interviews, appointments, scheduled "
    "calls, project reviews, team syncs, client meetings\n"
    "- LOW (blue): optional webinars, casual invites, 'feel free to join'\n\n"
    "## Auto-Add vs Inbox\n"
    "AUTO-ADD (straight to calendar): emails from a real person directly addressing "
    "the user — direct meeting invites, calendar invitations, thread replies.\n"
    "INBOX (hold for review): emails from organisations, companies, newsletters, "
    "no-reply addresses, mailing lists, promotions, mass announcements."
)

def _build_agent(llm: LLM) -> Agent:
    return Agent(
        role="Email-to-Calendar Assistant",
        goal=(
            "Scan the user's Gmail inbox, identify events/meetings, classify by "
            "priority (high/medium/low), auto-add personal invites to Google "
            "Calendar, and save organisational/misc events to a review page."
        ),
        backstory=AGENT_BACKSTORY,
        tools=[fetch_emails_tool, add_event_tool, save_review_page_tool],
        llm=llm,
        verbose=True,
    )

# ── Task Definitions ──────────────────────────────────────────────────────────

def _build_tasks(agent: Agent) -> list[Task]:

    scan_task = Task(
        description=(
            f"Use the 'Fetch Emails from Gmail' tool to fetch the latest {EMAILS_TO_SCAN} emails. "
            "Return the raw JSON list of emails exactly as the tool outputs it."
        ),
        expected_output="A JSON array of email objects fetched from Gmail.",
        agent=agent,
    )

    classify_task = Task(
        description=(
            "Analyse the emails from the previous task. For each email that contains "
            "an event, meeting, or actionable date:\n"
            "1. Determine its priority (high / medium / low) using the priority rules.\n"
            "2. Decide: AUTO-ADD (personal invites) or INBOX (organisational/mass emails).\n"
            "3. For every AUTO-ADD event, call the 'Add Event to Google Calendar' tool "
            "   with a JSON string containing: title, date (YYYY-MM-DD), start_time "
            "   (HH:MM or null), end_time (HH:MM or null), location (or null), "
            "   description, and priority.\n\n"
            "After adding all auto-add events, compile the INBOX items into a JSON array "
            "where each object has: id, title, date, start_time, end_time, location, "
            "description, from, suggested_priority, review_reason.\n\n"
            "Return a JSON object with:\n"
            "  - auto_added_count: number of events added to the calendar\n"
            "  - inbox_items: the JSON array of inbox items\n"
            "  - summary: a one-sentence summary of what was found"
        ),
        expected_output=(
            "A JSON object containing auto_added_count (int), inbox_items (array), "
            "and summary (string)."
        ),
        agent=agent,
    )

    review_task = Task(
        description=(
            "Take the inbox_items array and summary from the previous task's output. "
            "Call the 'Save Inbox Review Page' tool with:\n"
            "  - inbox_json: the JSON array of inbox items (as a string)\n"
            "  - summary: the one-sentence summary\n\n"
            "Return a final status message summarising how many events were auto-added "
            "and how many are pending review."
        ),
        expected_output=(
            "A final status message, e.g. 'Done. Added 3 events to Google Calendar. "
            "2 items saved to review page.'"
        ),
        agent=agent,
    )

    return [scan_task, classify_task, review_task]

# ── Crew Orchestration ────────────────────────────────────────────────────────

def build_crew() -> Crew:
    """Assemble the full CrewAI Crew."""
    llm = _build_llm()
    agent = _build_agent(llm)
    tasks = _build_tasks(agent)
    return Crew(
        agents=[agent],
        tasks=tasks,
        process=Process.sequential,
        verbose=True,
    )

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log("=" * 55)
    log("Mail → Calendar Agent (CrewAI) starting…")

    crew = build_crew()
    result = crew.kickoff()

    log(f"Crew finished.  Final output:\n{result}")
    log("=" * 55)

if __name__ == "__main__":
    main()
