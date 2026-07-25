"""
Thin wrapper around the Google Sheets API. The sheet is the single
source of truth for tasks — the bot reads today's rows to send the
9AM briefing, and writes Status/Date updates after the 11PM check-in.

Columns (row 1 is the header, exact order matters):
A Date | B Day | C Category | D Task | E Resource/Notes |
F Time (hrs) | G Deliverable | H Status | I Proposal Date

Column I is new: it holds a *proposed* reschedule date while we wait
for Prince to confirm or override it. Status "Pending Confirmation"
means "bot proposed a move, waiting on his reply" — it is NOT the
same as "Not Started".
"""
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

from . import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_client = None
PROPOSAL_COL = 9  # column I


def _get_client():
    global _client
    if _client is None:
        creds = Credentials.from_service_account_info(
            config.GOOGLE_SERVICE_ACCOUNT_INFO, scopes=SCOPES
        )
        _client = gspread.authorize(creds)
    return _client


def _worksheet():
    sheet = _get_client().open_by_key(config.SHEET_ID)
    ws = sheet.worksheet(config.SHEET_TAB_NAME)
    _ensure_proposal_column(ws)
    return ws


def _ensure_proposal_column(ws):
    """Adds the 'Proposal Date' header to column I if it isn't there yet.
    Runs on every call but is a no-op after the first time — cheap and
    means Prince never has to touch the sheet manually."""
    header = ws.row_values(1)
    if len(header) < PROPOSAL_COL or header[PROPOSAL_COL - 1] != "Proposal Date":
        ws.update_cell(1, PROPOSAL_COL, "Proposal Date")


def get_all_rows() -> list[dict]:
    """Returns every task row as a list of dicts, 1-indexed row_number included."""
    ws = _worksheet()
    records = ws.get_all_records()  # uses row 1 as headers
    for i, r in enumerate(records, start=2):  # row 1 is header, data starts at row 2
        r["_row_number"] = i
    return records


def get_tasks_for_date(date_str: str) -> list[dict]:
    """date_str format: YYYY-MM-DD"""
    return [r for r in get_all_rows() if r.get("Date") == date_str]


def update_status(row_number: int, status: str):
    ws = _worksheet()
    # Column H = Status (8th column)
    ws.update_cell(row_number, 8, status)


def reschedule_task(row_number: int, new_date_str: str, new_day_name: str):
    """Commit a move to a new date (used both for confirmed proposals and
    direct overrides). Clears any pending proposal marker."""
    ws = _worksheet()
    ws.update_cell(row_number, 1, new_date_str)    # Date
    ws.update_cell(row_number, 2, new_day_name)    # Day
    ws.update_cell(row_number, 8, "Pending")        # reset status
    ws.update_cell(row_number, PROPOSAL_COL, "")    # clear proposal


def propose_reschedule(row_number: int, proposed_date_str: str):
    """Stage a move without committing it — sets Status to 'Pending
    Confirmation' and records the proposed date in column I. The task
    stays on its ORIGINAL date/row until confirmed."""
    ws = _worksheet()
    ws.update_cell(row_number, 8, "Pending Confirmation")
    ws.update_cell(row_number, PROPOSAL_COL, proposed_date_str)


def get_pending_confirmations() -> list[dict]:
    """All rows currently awaiting a yes/override reply."""
    return [r for r in get_all_rows() if r.get("Status") == "Pending Confirmation"]


def day_cap_hours(date_str: str) -> float:
    """Weekday cap 3h (matches Prince's '2-3 hrs weekdays' answer),
    weekend cap 5h (more free time on Sat/Sun)."""
    weekday = datetime.strptime(date_str, "%Y-%m-%d").weekday()  # 5=Sat, 6=Sun
    return 5.0 if weekday >= 5 else 3.0


def compute_day_load(date_str: str) -> float:
    """Sum of Time(hrs) for all tasks currently scheduled on a date
    (committed only — pending proposals don't count toward load yet)."""
    tasks = get_tasks_for_date(date_str)
    total = 0.0
    for t in tasks:
        if t.get("Status") == "Pending Confirmation":
            continue
        try:
            total += float(t.get("Time (hrs)", 0) or 0)
        except (TypeError, ValueError):
            pass
    return total


def find_lightest_upcoming_day(after_date_str: str, window_days: int = 7) -> str | None:
    """Scan forward from after_date_str and return the first date under
    that day's cap (weekday vs weekend aware)."""
    d = datetime.strptime(after_date_str, "%Y-%m-%d")
    for i in range(1, window_days + 1):
        candidate = (d + timedelta(days=i)).strftime("%Y-%m-%d")
        if compute_day_load(candidate) < day_cap_hours(candidate):
            return candidate
    return None


def find_task_by_name(name_fragment: str, within_pending_only: bool = True) -> dict | None:
    """Fuzzy-ish match: case-insensitive substring match against Task text,
    scoped to pending-confirmation rows by default (that's all we should
    be able to override at confirmation time)."""
    rows = get_pending_confirmations() if within_pending_only else get_all_rows()
    name_fragment = name_fragment.lower().strip()
    for r in rows:
        if name_fragment in r.get("Task", "").lower():
            return r
    return None
