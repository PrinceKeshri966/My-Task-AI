"""Send WhatsApp messages via Twilio."""
from twilio.rest import Client
from . import config

_client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)


def send_message(body: str):
    _client.messages.create(
        from_=config.TWILIO_WHATSAPP_FROM,
        to=config.MY_WHATSAPP_NUMBER,
        body=body,
    )


def format_morning_brief(tasks: list[dict]) -> str:
    if not tasks:
        return "🌅 Good morning! No tasks scheduled for today — check your sheet."
    lines = ["🌅 *Today's Prep Tasks*\n"]
    for t in tasks:
        lines.append(f"• [{t['Category']}] {t['Task']} (~{t['Time (hrs)']}h)")
    lines.append("\nGrind time. I'll check in at 11PM 👊")
    return "\n".join(lines)


def format_checkin(tasks: list[dict]) -> str:
    if not tasks:
        return "🌙 No tasks were scheduled today."
    lines = ["🌙 *Check-in time* — what got done today?\n"]
    for i, t in enumerate(tasks, start=1):
        lines.append(f"{i}. {t['Task']}")
    lines.append(
        "\nReply naturally, e.g.:\n"
        "\"1 and 3 done, 2 in progress, rest not started\"\n"
        "I'll update your sheet + calendar and reschedule anything incomplete."
    )
    return "\n".join(lines)
