"""Omni-Core Phase 4 — proactive scheduler.

Fires due reminders and a daily morning brief over Telegram. Runs two
ways (same tick logic):
  - inside telegram_bot.py (checked on every poll cycle), or
  - standalone:  python scheduler.py
Times are IST. Brief time: OMNI_BRIEF_TIME (default 08:00).
"""
import json
import os
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import memory
import reminders

IST = ZoneInfo("Asia/Kolkata")
BRIEF_TIME = os.environ.get("OMNI_BRIEF_TIME", "08:00")


def now_ist() -> datetime:
    return datetime.now(IST)


def compose_brief(now: datetime) -> str:
    lines = [f"☀️ Kaalai vanakkam, sir — {now.strftime('%A, %d %B %Y')}", ""]
    pending = [
        f"• {t} ({d})" for _id, t, d in reminders.due_pending(now.strftime(reminders.FMT))
    ]
    upcoming = [
        f"• {t} — fires {due}" for t, _w, due, fired in reminders.list_all()
        if due and not fired
    ]
    if upcoming:
        lines.append("⏰ Reminders on deck:")
        lines.extend(upcoming[:5])
    else:
        lines.append("⏰ No timed reminders pending.")
    radar = [f for f in memory.list_facts()
             if "deadline" in f.lower() or "pending" in f.lower()]
    if radar:
        lines.append("")
        lines.append("📌 On your radar:")
        lines.extend(f"• {f}" for f in radar[:4])
    return "\n".join(lines)


def tick(send) -> list[str]:
    """Fire what is due. `send(text)` delivers one message, or None to
    disable delivery (nothing is marked fired without a channel).
    Returns what was sent (for logs/tests)."""
    if send is None:
        return []
    sent = []
    now = now_ist()
    for rid, text, due in reminders.due_pending(now.strftime(reminders.FMT)):
        msg = f"⏰ Reminder, sir: {text} (due {due})"
        send(msg)
        reminders.mark_fired(rid)
        sent.append(msg)
    today = now.strftime("%Y-%m-%d")
    if now.strftime("%H:%M") >= BRIEF_TIME and reminders.get_state("last_brief") != today:
        brief = compose_brief(now)
        send(brief)
        reminders.set_state("last_brief", today)
        sent.append(brief)
    return sent


def _telegram_send():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    owner = os.environ.get("OMNI_OWNER_CHAT_ID", "").strip()
    if not token or not owner:
        return None

    def send(text: str):
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps({"chat_id": int(owner), "text": text}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "omni-core"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()

    return send


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    send = _telegram_send()
    if send is None:
        print("Telegram not configured (TELEGRAM_BOT_TOKEN / OMNI_OWNER_CHAT_ID) — "
              "scheduler has no delivery channel. Set them in .env, or run telegram_bot.py.")
        return
    print(f"Scheduler running — checks every 30s, brief at {BRIEF_TIME} IST.")
    while True:
        try:
            for msg in tick(send):
                print(f"sent: {msg.splitlines()[0]}")
        except Exception as e:
            print(f"tick error: {e}")
        time.sleep(30)


if __name__ == "__main__":
    main()
