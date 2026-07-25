# Prep Tracker WhatsApp Bot

Fully agentic version of the daily prep check-in: WhatsApp pings you at
9AM with today's tasks, pings you again at 11PM, you reply in plain
Hinglish/English, and it updates your **Google Sheet** + **Google
Calendar** on its own — including rescheduling incomplete tasks to the
lightest upcoming day.

You never open Claude to do this. You only reply on WhatsApp.

---

## Architecture (why each piece exists)

```
cron (9AM/11PM) --> your FastAPI app --> Twilio --> your WhatsApp
                                                          |
                                                     you reply
                                                          |
                                                          v
Twilio webhook --> your FastAPI app --> rule-based reply parser
                                              |
                                              v
                                   Google Sheets (status + reschedule)
                                              |
                                              v
                                     Google Calendar (sync)
```

This is the zero-cost version: no Anthropic key, no per-message billing.
The reply parser (`app/reply_parser.py`) is regex + keyword matching,
not an LLM call — it mirrors the backend-skill-to-AI-skill mapping from
your roadmap in a different way: the webhook is still just an API
contract, and this is the classic "do you actually need an LLM here"
call every AI-engineer makes. For structured replies like yours it's
plenty reliable; swap in an LLM later if you want (see
`reply_parser.py`'s docstring — same function signatures, drop-in
replacement).

### Reschedule flow — two phases, bot proposes then confirms

**Phase 1 (11PM reply):** Done tasks get marked Done immediately.
Incomplete tasks get a *proposed* date (scans 7 days forward, weekday
cap 3h, weekend cap 5h) — but nothing moves yet. Status becomes
"Pending Confirmation" and you get a message listing the proposals.

**Phase 2 (your next reply):** Since something is "Pending
Confirmation", your next message is read as a confirm/override, not a
new check-in.
- "ok" / "haan" / "theek hai" → commits every proposal as-is.
- "move DSA to 2026-08-03" → commits that one task to the date you
  named; everything else still commits at its original proposal.

This is what actually satisfies "pucho bhi aur batao bhi" — the bot
proposes and tells you where, then waits for your yes/override before
touching the Sheet's Date column.

---

## Step 1 — Twilio WhatsApp Sandbox (free, ~10 min)

1. Sign up at twilio.com (free trial).
2. Console → Messaging → Try it out → **Send a WhatsApp message**.
3. It gives you a sandbox number (e.g. `+1 415 523 8886`) and a join
   code like `join <two-words>`.
4. From your own WhatsApp, send that join code to that number. This
   links your number to the sandbox for testing.
5. Copy your **Account SID** and **Auth Token** from the Twilio
   console into `.env`.

> Sandbox limitation: Twilio's free sandbox requires you to re-send the
> join code roughly every 3 days, and messages you send *to* yourself
> only work within a 24h window after you last messaged the bot. Fine
> for personal use; if this annoys you, a paid Twilio WhatsApp Business
> number removes both limits.

## Step 2 — Google Service Account (for Sheets + Calendar API access)

1. console.cloud.google.com → new project → enable **Google Sheets
   API** and **Google Calendar API**.
2. IAM & Admin → Service Accounts → Create → download the JSON key.
3. Open that JSON, copy the `client_email` (looks like
   `xxx@yyy.iam.gserviceaccount.com`).
4. **Share your Google Sheet** ("Prep Tracker — Backend+AI (Live)")
   with that email, Editor access.
5. **Share your Google Calendar** with that same email: Calendar
   settings → Share with specific people → Editor.
6. Put the JSON key file path in `GOOGLE_SERVICE_ACCOUNT_JSON`.

## Step 3 — Fill in `.env`

Copy `.env.example` to `.env` and fill every value. `SHEET_ID` is
already set to your Prep Tracker sheet's ID.

## Step 4 — Run it locally first

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Test the morning trigger manually:
```bash
curl -X POST http://localhost:8000/trigger/morning
```
You should get a WhatsApp message within seconds.

## Step 5 — Deploy (Render, free tier)

1. Push this folder to a GitHub repo.
2. render.com → New → Web Service → connect the repo.
3. Build command: `pip install -r requirements.txt`
   Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add all `.env` values as Render environment variables. For
   `GOOGLE_SERVICE_ACCOUNT_JSON`, use Render's **Secret File** feature
   to upload the JSON key, and point the env var at its mounted path
   (e.g. `/etc/secrets/service-account.json`).
5. Deploy. Note your live URL, e.g. `https://prep-bot.onrender.com`.

## Step 6 — Point Twilio's webhook at your deployed app

Twilio console → WhatsApp Sandbox Settings → "When a message comes in":
```
https://prep-bot.onrender.com/webhook/whatsapp
```
Method: POST.

## Step 7 — Schedule the 9AM / 11PM triggers

Render's free tier has no built-in cron, so use a free external
scheduler — **cron-job.org** is easiest:

1. Create a cron job hitting
   `https://prep-bot.onrender.com/trigger/morning` daily at `09:00
   Asia/Kolkata`.
2. Another hitting `.../trigger/checkin` daily at `23:00 Asia/Kolkata`.
3. Method: POST.

(Alternative: GitHub Actions with a `schedule:` cron trigger calling
these endpoints via `curl` — better if you want the trigger logic
version-controlled alongside the code.)

## Step 8 — Test end to end

Wait for (or manually trigger) the 11PM check-in, reply naturally:
> "1 and 3 done, 2 abhi chal raha hai"

Within a few seconds you should get a confirmation message, and your
Sheet + Calendar should reflect it.

---

## Known limitations (be aware of these)

- **Rule-based parser, not an LLM.** Stick to clear phrasing like "1
  and 3 done, 2 in progress" or "sab done" — it looks for numbers next
  to keywords (done/progress/not started, English + common Hinglish).
  Something very indirect may fall through to "Not Started" (the safe
  default — you'll just get asked about it again, nothing gets lost).
- **Override dates must be typed exactly** as `YYYY-MM-DD` — "move DSA
  to kal" won't resolve; "move DSA to 2026-08-03" will.

- **Reschedule window is 7 days forward.** If the whole week is full,
  the bot leaves the task in place and flags it — it won't silently
  overflow into week 3.
- **One task-list snapshot per webhook call.** If you reply twice in
  quick succession, the second reply re-reads fresh sheet state, so
  it's safe, just not instant-cumulative within the same second.
- **Twilio sandbox 24h window** (see Step 1) — upgrade to a paid
  WhatsApp Business number if this becomes annoying.
- **No auth on `/trigger/*` endpoints** in this starter — anyone with
  the URL can fire them. Fine behind an unguessable Render URL for
  personal use; add an API key header if you want it hardened.
