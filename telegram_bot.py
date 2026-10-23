"""Jarvis 2.0 — Telegram front door.

Long-polling bot, no server needed:  python telegram_bot.py

New in 2.0: approval gates. When the brain wants to run a tool that can
change the outside world (e.g. submitting a web form), the bot asks YOU
with inline Yes/No buttons and waits (3 min) before proceeding.

Setup: same as before — TELEGRAM_BOT_TOKEN + OMNI_OWNER_CHAT_ID in .env.
"""

import itertools
import json
import os
import threading
import time
import urllib.request

from dotenv import load_dotenv

load_dotenv()  # before importing brain — it reads env at import time

import brain  # noqa: E402
import memory  # noqa: E402
import scheduler  # noqa: E402
import voice  # noqa: E402

VOICE_REPLY = os.environ.get("OMNI_VOICE_REPLY", "1") == "1"

API = "https://api.telegram.org/bot{token}/{method}"
OWNER = os.environ.get("OMNI_OWNER_CHAT_ID", "").strip()


def api(token: str, method: str, payload: dict, timeout: int = 45) -> dict:
    req = urllib.request.Request(
        API.format(token=token, method=method),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "jarvis-2.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def split_reply(text: str, limit: int = 3900) -> list[str]:
    """Telegram caps messages at 4096 chars — split on line breaks,
    hard-chunking any single line that is longer than the limit."""
    parts, cur = [], ""
    for line in (text or "(no reply)").splitlines(keepends=True):
        while len(line) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) > limit and cur:
            parts.append(cur)
            cur = ""
        cur += line
    if cur:
        parts.append(cur)
    return parts or ["(no reply)"]


# ---------------------------------------------------------- approval gates

_approvals: dict = {}
_approval_lock = threading.Lock()
_approval_counter = itertools.count(1)


def make_approver(token: str, chat_id: int):
    """Build the approver callback brain.py needs. Sends an inline
    Yes/No prompt and blocks (max 3 min) for the user's tap."""

    def approver(tool_name: str, args: dict) -> bool:
        key = f"appr{next(_approval_counter)}"
        ev = threading.Event()
        with _approval_lock:
            _approvals[key] = {"event": ev, "ok": False}
        argstr = ", ".join(f"{k}={str(v)[:80]}" for k, v in args.items())
        if tool_name == "propose_skill":
            code = str(args.get("code", ""))[:2500]
            text = (f"🔧 *New skill proposal*\n`{args.get('name', '')}`\n\n"
                    f"```python\n{code}\n```\n\n"
                    f"Activate this skill? (smoke test runs on Yes)")
        else:
            text = (f"⚠️ *Approval needed*\n`{tool_name}({argstr})`\n\n"
                    f"This action can change the outside world. Allow?")
        try:
            api(token, "sendMessage", {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "reply_markup": {"inline_keyboard": [[
                    {"text": "✅ Yes", "callback_data": f"{key}:yes"},
                    {"text": "❌ No", "callback_data": f"{key}:no"},
                ]]},
            })
        except Exception as e:
            print(f"approval prompt failed: {e}")
            with _approval_lock:
                _approvals.pop(key, None)
            return False
        ev.wait(timeout=180)
        with _approval_lock:
            rec = _approvals.pop(key, {"ok": False})
        return bool(rec["ok"])

    return approver


def _handle_callback(token: str, cq: dict) -> None:
    data = cq.get("data", "") or ""
    key, _, decision = data.partition(":")
    with _approval_lock:
        rec = _approvals.get(key)
        if rec is not None:
            rec["ok"] = (decision == "yes")
            rec["event"].set()
    try:
        api(token, "answerCallbackQuery",
            {"callback_query_id": cq.get("id", ""),
             "text": "Approved ✅" if decision == "yes" else "Denied"})
    except Exception:
        pass


# ---------------------------------------------------------------- handlers

def _owner_gate(chat_id: int, send) -> bool:
    if not OWNER:
        send(chat_id, f"👋 Your chat ID is {chat_id}.\n"
                      "Put it in .env as OMNI_OWNER_CHAT_ID and restart the bot — "
                      "then I will answer only you, sir.")
        return False
    if str(chat_id) != OWNER:
        send(chat_id, "🔒 Private assistant. I answer only my owner.")
        return False
    return True


def handle_text(chat_id: int, text: str, send, token: str) -> None:
    if not _owner_gate(chat_id, send):
        return
    text = text.strip()
    if text == "/start":
        send(chat_id, "Vanakkam, sir. Jarvis 2.0 online. 🦾 Enna pannanum?")
        return
    if text == "/facts":
        facts = memory.list_facts()
        send(chat_id, "\n".join(f"• {f}" for f in facts) or "Nothing saved yet, sir.")
        return
    if text == "/reset":
        memory.clear_history()
        send(chat_id, "Chat history cleared, sir. Facts and graph safe irukku.")
        return
    if text == "/usage":
        u, b = __import__("quota").used_today(), __import__("quota").budget()
        send(chat_id, f"📊 Model calls today: {u}/{b}")
        return
    if text:
        try:
            reply = brain.chat(text, approver=make_approver(token, chat_id))
        except Exception as e:
            reply = f"⚠️ {brain.format_error(e)}"
        for part in split_reply(reply):
            send(chat_id, part)


def download_file(token: str, file_id: str) -> bytes:
    out = api(token, "getFile", {"file_id": file_id})
    path = out["result"]["file_path"]
    req = urllib.request.Request(
        f"https://api.telegram.org/file/bot{token}/{path}",
        headers={"User-Agent": "jarvis-2.0"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def send_audio_file(token: str, chat_id: int, wav: bytes) -> None:
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav)
        tmp = f.name
    try:
        subprocess.run(
            ["curl", "-s", "--max-time", "60",
             "-F", f"chat_id={chat_id}",
             "-F", f"audio=@{tmp}",
             f"https://api.telegram.org/bot{token}/sendAudio"],
            capture_output=True, timeout=75,
        )
    finally:
        os.unlink(tmp)


def handle_voice(chat_id: int, token: str, file_id: str, send) -> None:
    """A Telegram voice note: hear it, think, reply in text + voice."""
    if not _owner_gate(chat_id, send):
        return
    try:
        audio = download_file(token, file_id)
        heard = voice.transcribe(audio, "audio/ogg")
    except Exception as e:
        send(chat_id, f"⚠️ Voice puriyala, sir: {brain.format_error(e)}")
        return
    if not heard:
        send(chat_id, "⚠️ Onnum kekkala, sir — marupadiyum pesunga.")
        return
    send(chat_id, f"🎙️ Neenga sonnadhu: {heard}")
    try:
        reply = brain.chat(heard, approver=make_approver(token, chat_id))
    except Exception as e:
        reply = f"⚠️ {brain.format_error(e)}"
    for part in split_reply(reply):
        send(chat_id, part)
    if VOICE_REPLY:
        try:
            wav = voice.speak(reply)
            if wav:
                send_audio_file(token, chat_id, wav)
        except Exception as e:
            print(f"voice reply failed: {e}")


def main() -> None:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token == "your-token-here":
        print("TELEGRAM_BOT_TOKEN is not set in .env.")
        print("Create a free bot: Telegram → @BotFather → /newbot → copy the token.")
        return
    send = lambda cid, txt: api(token, "sendMessage", {"chat_id": cid, "text": txt})  # noqa: E731
    print("Jarvis 2.0 Telegram bot polling… (Ctrl+C to stop)")
    offset = 0
    while True:
        try:
            out = api(token, "getUpdates", {"offset": offset, "timeout": 30}, timeout=40)
        except Exception as e:
            print(f"poll error: {e} — retrying in 5s")
            time.sleep(5)
            continue
        for upd in out.get("result", []):
            offset = upd["update_id"] + 1
            if upd.get("callback_query"):
                _handle_callback(token, upd["callback_query"])
                continue
            msg = upd.get("message") or {}
            chat_id = (msg.get("chat") or {}).get("id")
            text = msg.get("text") or ""
            voice_note = msg.get("voice") or msg.get("audio") or {}
            if chat_id is not None:
                try:
                    api(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
                except Exception:
                    pass
                if voice_note.get("file_id"):
                    handle_voice(chat_id, token, voice_note["file_id"], send)
                elif text:
                    handle_text(chat_id, text, send, token)
        # Proactive — fire due reminders + morning brief.
        if OWNER:
            try:
                scheduler.tick(lambda txt: send(int(OWNER), txt))
            except Exception as e:
                print(f"scheduler tick error: {e}")


if __name__ == "__main__":
    main()
