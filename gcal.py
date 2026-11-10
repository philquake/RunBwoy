"""Google Calendar output: .ics export (no setup) and optional direct API sync (OAuth)."""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

DATA = os.environ.get("RUNCOACH_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CREDS = os.path.join(DATA, "google_credentials.json")   # OAuth desktop client you download from Google Cloud
TOKEN = os.path.join(DATA, "google_token.json")
STATE = os.path.join(DATA, "gcal_state.json")
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CAL_NAME = "Run Coach"
COLORS = {"training": "11", "meals": "10", "sleep": "9"}   # tomato, basil, blueberry


# ---------- ICS ----------
def _esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line):
    out, cur, n = [], "", 0
    for ch in line:
        b = len(ch.encode("utf-8"))
        if n + b > 73:
            out.append(cur)
            cur, n = " " + ch, 1 + b
        else:
            cur += ch
            n += b
    out.append(cur)
    return "\r\n".join(out)


def to_ics(events, tz):
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Run Coach//EN", "CALSCALE:GREGORIAN",
         f"X-WR-CALNAME:{CAL_NAME}", f"X-WR-TIMEZONE:{tz}"]
    for e in events:
        L += ["BEGIN:VEVENT", f"UID:{e['uid']}@runcoach.local", f"DTSTAMP:{now}",
              f"DTSTART;TZID={tz}:{e['start']:%Y%m%dT%H%M%S}", f"DTEND;TZID={tz}:{e['end']:%Y%m%dT%H%M%S}",
              f"SUMMARY:{_esc(e['summary'])}", f"DESCRIPTION:{_esc(e['description'])}",
              f"CATEGORIES:{e['kind']}"]
        if e["kind"] != "training":
            L.append("TRANSP:TRANSPARENT")          # meals/sleep don't make you look busy
        if e["kind"] != "meals":                     # reminders for runs and bedtime only
            L += ["BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT15M", f"DESCRIPTION:{_esc(e['summary'])}", "END:VALARM"]
        L.append("END:VEVENT")
    L.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in L) + "\r\n"


# ---------- Google API ----------
def status():
    try:
        import googleapiclient, google_auth_oauthlib  # noqa: F401
        libs = True
    except ImportError:
        libs = False
    return {"libraries": libs, "credentials_file": os.path.exists(CREDS), "authorised": os.path.exists(TOKEN),
            "credentials_path": CREDS,
            "calendar_id": (json.load(open(STATE)).get("calendar_id") if os.path.exists(STATE) else None)}


def _service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES) if os.path.exists(TOKEN) else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS, SCOPES)
            creds = flow.run_local_server(port=0)   # opens your browser once to sign in
        os.makedirs(DATA, exist_ok=True)
        with open(TOKEN, "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def sync(events, tz):
    """Create/update events in a dedicated 'Run Coach' calendar. Idempotent (stable event ids)."""
    from googleapiclient.errors import HttpError
    s = _service()
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    cal = st.get("calendar_id")
    if not cal:
        cal = s.calendars().insert(body={"summary": CAL_NAME, "timeZone": tz}).execute()["id"]
        os.makedirs(DATA, exist_ok=True)
        json.dump({"calendar_id": cal}, open(STATE, "w"))
    created = updated = deleted = 0
    keep = set()
    kinds = {e["kind"] for e in events}
    for e in events:
        body = {
            "id": hashlib.sha1(e["uid"].encode()).hexdigest(),
            "summary": e["summary"], "description": e["description"], "status": "confirmed",
            "start": {"dateTime": e["start"].isoformat(), "timeZone": tz},
            "end": {"dateTime": e["end"].isoformat(), "timeZone": tz},
            "colorId": COLORS.get(e["kind"], "1"),
            "extendedProperties": {"private": {"runcoach": "1", "kind": e["kind"]}},
            "transparency": "opaque" if e["kind"] == "training" else "transparent",
            "reminders": {"useDefault": False,
                          "overrides": [] if e["kind"] == "meals" else [{"method": "popup", "minutes": 15}]},
        }
        keep.add(body["id"])
        try:
            s.events().insert(calendarId=cal, body=body).execute()
            created += 1
        except HttpError as err:
            if err.resp.status == 409:
                s.events().update(calendarId=cal, eventId=body["id"], body=body).execute()
                updated += 1
            else:
                raise
    # cleanup: remove Run Coach events from today onwards that are no longer in the plan
    # (only kinds included in this sync, so syncing "training" alone never touches meals/sleep)
    start = min(e["start"] for e in events) if events else datetime.now()
    token = None
    while True:
        res = s.events().list(calendarId=cal, timeMin=(start - timedelta(days=1)).isoformat() + "Z",
                              singleEvents=True, maxResults=250, pageToken=token,
                              privateExtendedProperty="runcoach=1").execute()
        for it in res.get("items", []):
            k = it.get("extendedProperties", {}).get("private", {}).get("kind")
            when = it.get("start", {}).get("dateTime", "")[:19]      # local wall-clock, same tz as ours
            if it["id"] not in keep and k in kinds and when >= start.isoformat()[:19]:
                s.events().delete(calendarId=cal, eventId=it["id"]).execute()
                deleted += 1
        token = res.get("nextPageToken")
        if not token:
            break
    return {"calendar_id": cal, "created": created, "updated": updated, "deleted": deleted}
