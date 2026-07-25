"""
Rule-based parser — no LLM call, no API key, zero cost.

Handles replies shaped like Prince actually writes them:
  "1 aur 3 done, 2 abhi chal raha hai"
  "1,2 done rest not started"
  "sab done"
  "1 done, baaki nahi hua"

Trade-off (be aware): this is regex + keyword matching, not a language
model. It's reliable for structured, predictable replies like the ones
above. If you go off-script with something very indirect or sarcastic,
it may default to "Not Started" for anything it can't confidently
match — which is the safe failure mode (worst case: an already-done
task gets asked about again tomorrow, nothing gets silently lost).

Swap-in note: if you ever want the flexible version back, this file
exposes the exact same function signatures as the old llm_parser.py
did, so main.py doesn't need to change.
"""
import re

VALID_STATUSES = {"Done", "In Progress", "Not Started"}

DONE_WORDS = [
    "done", "complete", "completed", "finished", "finish",
    "ho gaya", "hogaya", "ho gya", "hogya", "khatam", "khtm",
    "kar liya", "karliya", "kar diya", "kardiya",
]
PROGRESS_WORDS = [
    "progress", "in progress", "chal raha", "chalraha", "chal rha",
    "working", "wip", "shuru", "start kiya", "startkiya", "adhoora",
    "half", "aadha",
]
NOT_STARTED_WORDS = [
    "not started", "notstarted", "nahi kiya", "nahikiya", "nahi hua",
    "nahihua", "baaki", "baki", "pending", "nahi start", "abhi nahi",
    "nai hua", "nai kiya",
]
ALL_WORDS = ["sab", "all", "sabkuch", "sabhi", "everything"]
CONFIRM_WORDS = [
    "ok", "okay", "haan", "han", "yes", "confirm", "theek", "thik",
    "sahi", "sahi hai", "theek hai", "thik hai", "kar do", "kardo",
    "proceed", "go ahead",
]


def _clause_status(clause: str) -> str | None:
    if any(w in clause for w in DONE_WORDS):
        return "Done"
    if any(w in clause for w in PROGRESS_WORDS):
        return "In Progress"
    if any(w in clause for w in NOT_STARTED_WORDS):
        return "Not Started"
    return None


def parse_reply(tasks: list[dict], reply_text: str) -> dict[int, str]:
    """Same signature/behaviour as the old LLM version: returns
    {1: "Done", 2: "In Progress", ...} for every task index."""
    text = reply_text.lower().strip()
    n = len(tasks)
    result: dict[int, str] = {}

    # "sab done" / "all completed" with no numbers at all
    if any(w in text for w in ALL_WORDS):
        blanket_status = _clause_status(text)
        if blanket_status:
            for i in range(1, n + 1):
                result[i] = blanket_status

    # Split into clauses on common separators
    clauses = re.split(r",|;|\band\b|\baur\b", text)

    for clause in clauses:
        status = _clause_status(clause)
        if status is None:
            continue
        numbers = [int(x) for x in re.findall(r"\b(\d+)\b", clause) if 1 <= int(x) <= n]
        for num in numbers:
            result[num] = status
        # "baaki" / "rest" / "others" in a clause with a status but no
        # numbers -> apply to everything not yet assigned
        if not numbers and any(w in clause for w in ["baaki", "baki", "rest", "others", "remaining"]):
            for i in range(1, n + 1):
                if i not in result:
                    result[i] = status

    # Anything never mentioned defaults to Not Started (safe default)
    for i in range(1, n + 1):
        result.setdefault(i, "Not Started")

    return result


def parse_override_reply(reply_text: str, today_date_str: str) -> dict:
    """Same signature as the old LLM version: {"confirm_rest": bool,
    "overrides": [{"task": "...", "date": "YYYY-MM-DD"}]}.

    Only understands explicit ISO dates in "move X to YYYY-MM-DD" —
    it does not resolve relative dates like "kal"/"parso". If you want
    that, either type the date out, or this is exactly the kind of gap
    an LLM-based parser closes later.
    """
    text = reply_text.strip()
    text_lower = text.lower()

    overrides = []
    for match in re.finditer(r"move\s+(.+?)\s+to\s+(\d{4}-\d{2}-\d{2})", text_lower):
        task_fragment, date_str = match.group(1).strip(), match.group(2).strip()
        overrides.append({"task": task_fragment, "date": date_str})

    confirm_rest = True  # default: always commit the rest unless told otherwise
    if any(w in text_lower for w in ["only", "sirf", "just this", "baki mat"]):
        confirm_rest = False

    return {"confirm_rest": confirm_rest, "overrides": overrides}
