"""
Keeps Google Calendar in sync with the Sheet. We don't try to track a
separate event-per-task — instead, each day's 9AM/11PM events get their
*description* rewritten to reflect current status, and if a task moves
to a new day, we append it to that day's existing events (creating them
if they don't exist yet).
"""
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

from . import config

SCOPES = ["https://www.googleapis.com/auth/calendar"]

_service = None


def _get_service():
    global _service
    if _service is None:
        creds = Credentials.from_service_account_info(
            config.GOOGLE_SERVICE_ACCOUNT_INFO, scopes=SCOPES
        )
        _service = build("calendar", "v3", credentials=creds)
    return _service


def _day_bounds(date_str: str):
    start = f"{date_str}T00:00:00+05:30"
    end = f"{date_str}T23:59:59+05:30"
    return start, end


def find_event_by_title_on_date(date_str: str, title_contains: str):
    service = _get_service()
    start, end = _day_bounds(date_str)
    events = service.events().list(
        calendarId=config.CALENDAR_ID,
        timeMin=start,
        timeMax=end,
        q=title_contains,
        singleEvents=True,
    ).execute()
    items = events.get("items", [])
    return items[0] if items else None


def update_event_description(event_id: str, new_description: str):
    service = _get_service()
    service.events().patch(
        calendarId=config.CALENDAR_ID,
        eventId=event_id,
        body={"description": new_description},
    ).execute()


def sync_day_status(date_str: str, tasks: list[dict]):
    """Rewrite the 9AM event's description with current status for each task."""
    event = find_event_by_title_on_date(date_str, "Today's Prep Tasks")
    if not event:
        return
    lines = ["Today's tasks:"]
    for t in tasks:
        lines.append(f"- [{t['Status']}] {t['Task']} ({t['Time (hrs)']}h)")
    update_event_description(event["id"], "\n".join(lines))


def append_rescheduled_task(date_str: str, task_text: str):
    """
    Add a rescheduled task to an existing day's 9AM/11PM events, or
    create a fresh pair of events if that day has none yet.
    """
    service = _get_service()
    morning = find_event_by_title_on_date(date_str, "Today's Prep Tasks")
    night = find_event_by_title_on_date(date_str, "Task Check-in")

    if morning:
        new_desc = (morning.get("description", "") + f"\n- [Pending] {task_text} (rescheduled)")
        update_event_description(morning["id"], new_desc)
    else:
        service.events().insert(calendarId=config.CALENDAR_ID, body={
            "summary": "🌅 9AM — Today's Prep Tasks (Backend+AI Prep)",
            "description": f"Today's tasks:\n- [Pending] {task_text} (rescheduled)",
            "start": {"dateTime": f"{date_str}T09:00:00", "timeZone": config.TIMEZONE},
            "end": {"dateTime": f"{date_str}T09:15:00", "timeZone": config.TIMEZONE},
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 0}]},
        }).execute()

    if night:
        new_desc = (night.get("description", "") + f"\n- {task_text} (rescheduled)")
        update_event_description(night["id"], new_desc)
    else:
        service.events().insert(calendarId=config.CALENDAR_ID, body={
            "summary": "🌙 11PM — Task Check-in (reply to Claude with status)",
            "description": f"Review and reply with status for:\n- {task_text} (rescheduled)",
            "start": {"dateTime": f"{date_str}T23:00:00", "timeZone": config.TIMEZONE},
            "end": {"dateTime": f"{date_str}T23:15:00", "timeZone": config.TIMEZONE},
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 0}]},
        }).execute()
