"""
FastAPI backend for the prep-tracker WhatsApp bot.

Three endpoints, called by an external scheduler (cron-job.org, Render
Cron, or GitHub Actions on a schedule — see README):

  POST /trigger/morning   -> sends the 9AM task briefing
  POST /trigger/checkin   -> sends the 11PM "what got done" prompt
  POST /webhook/whatsapp  -> Twilio calls this when Prince replies

Reschedule rule (per Prince's spec), now a proper two-phase flow:

  Phase 1 (11PM check-in reply):
    - Done              -> mark Done, stays on today
    - In Progress /
      Not Started       -> scan forward through the week (weekday cap
                           3h, weekend cap 5h), find the lightest day,
                           and PROPOSE it — do NOT move it yet. Status
                           becomes "Pending Confirmation".
    - Bot sends the proposals and asks for confirmation.

  Phase 2 (his next reply, whenever it comes):
    - If any row is "Pending Confirmation", this reply is treated as
      the confirmation/override step, not a new check-in.
    - "ok" / "haan" / silence on specifics -> commit all proposals as-is.
    - "move <task> to <date>" -> commit that task to the given date
      instead of its proposal; everything else still commits normally.
"""
import logging
from datetime import datetime
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse

from . import config, sheets, whatsapp, reply_parser, calendar_sync

app = FastAPI(title="Prep Tracker WhatsApp Bot")
logger = logging.getLogger("prep-bot")


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _day_name(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%A")


@app.post("/trigger/morning")
def trigger_morning():
    try:
        date_str = _today_str()
        tasks = sheets.get_tasks_for_date(date_str)
        whatsapp.send_message(whatsapp.format_morning_brief(tasks))
        return {"sent": True, "task_count": len(tasks)}
    except Exception:
        logger.exception("trigger_morning failed")
        return JSONResponse(status_code=500, content={"ok": False, "error": "morning trigger failed, check Render logs"})


@app.post("/trigger/checkin")
def trigger_checkin():
    try:
        date_str = _today_str()
        tasks = sheets.get_tasks_for_date(date_str)
        whatsapp.send_message(whatsapp.format_checkin(tasks))
        return {"sent": True, "task_count": len(tasks)}
    except Exception:
        logger.exception("trigger_checkin failed")
        return JSONResponse(status_code=500, content={"ok": False, "error": "checkin trigger failed, check Render logs"})


def _commit_proposal(row: dict):
    target_date = row.get("Proposal Date") or row.get("Date")
    sheets.reschedule_task(row["_row_number"], target_date, _day_name(target_date))
    calendar_sync.append_rescheduled_task(target_date, row["Task"])
    return target_date


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, x_webhook_secret: str = Header(default="")):
    if config.WEBHOOK_SHARED_SECRET and x_webhook_secret != config.WEBHOOK_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")

    try:
        form = await request.form()
        reply_text = form.get("Body", "")
        today = _today_str()

        pending = sheets.get_pending_confirmations()

        # ---------- PHASE 2: confirming/overriding a previous proposal ----------
        if pending:
            parsed = reply_parser.parse_override_reply(reply_text, today)
            overridden_names = {o["task"].lower() for o in parsed["overrides"]}

            committed_lines = []

            # Apply explicit overrides first
            for override in parsed["overrides"]:
                match = sheets.find_task_by_name(override["task"])
                if not match:
                    committed_lines.append(f"⚠️ Couldn't find a pending task matching '{override['task']}'")
                    continue
                sheets.reschedule_task(match["_row_number"], override["date"], _day_name(override["date"]))
                calendar_sync.append_rescheduled_task(override["date"], match["Task"])
                committed_lines.append(f"→ '{match['Task']}' moved to {override['date']} ({_day_name(override['date'])}) [your choice]")

            # Commit everything else at its original proposed date, if confirmed
            if parsed["confirm_rest"]:
                for row in pending:
                    if row["Task"].lower() in overridden_names:
                        continue  # already handled above
                    target_date = _commit_proposal(row)
                    committed_lines.append(f"→ '{row['Task']}' moved to {target_date} ({_day_name(target_date)}) [confirmed]")

            whatsapp.send_message("✅ Updated:\n" + "\n".join(committed_lines) if committed_lines else "Nothing to update.")
            return {"ok": True, "committed": committed_lines}

        # ---------- PHASE 1: normal 11PM check-in reply ----------
        tasks = sheets.get_tasks_for_date(today)
        if not tasks:
            whatsapp.send_message("No tasks were scheduled today, nothing to update.")
            return {"ok": True}

        statuses = reply_parser.parse_reply(tasks, reply_text)  # {1: "Done", 2: "In Progress", ...}

        done_names, proposal_lines = [], []

        for i, task in enumerate(tasks, start=1):
            status = statuses.get(i, "Not Started")
            row = task["_row_number"]

            if status == "Done":
                sheets.update_status(row, "Done")
                done_names.append(task["Task"])
            else:
                target_date = sheets.find_lightest_upcoming_day(today, window_days=7)
                if target_date is None:
                    sheets.update_status(row, status)
                    proposal_lines.append(f"⚠️ Couldn't propose a slot for '{task['Task']}' — next 7 days are full")
                    continue
                sheets.propose_reschedule(row, target_date)
                proposal_lines.append(f"• '{task['Task']}' → proposed: {target_date} ({_day_name(target_date)})")

        calendar_sync.sync_day_status(today, sheets.get_tasks_for_date(today))

        summary_lines = []
        if done_names:
            summary_lines.append("✅ Marked done:")
            summary_lines += [f"  - {n}" for n in done_names]
        if proposal_lines:
            summary_lines.append("\n📅 Proposed reschedule (not moved yet):")
            summary_lines += proposal_lines
            summary_lines.append(
                "\nReply 'ok' to confirm all, or 'move <task name> to <YYYY-MM-DD>' "
                "to change specific ones — the rest will still confirm."
            )
        whatsapp.send_message("\n".join(summary_lines) if summary_lines else "Nothing to update.")

        return {"ok": True, "done": done_names, "proposals": proposal_lines}

    except Exception:
        logger.exception("whatsapp_webhook failed")
        return JSONResponse(status_code=500, content={"ok": False, "error": "webhook processing failed, check Render logs"})


@app.get("/health")
def health():
    return {"status": "ok"}
