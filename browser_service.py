"""Omni-Core Phase 2 — browser daemon.

A small long-running process that owns ONE Playwright Chromium with a
persistent profile (browser_profile/), so logins survive across chats.
The MCP tools talk to it over localhost HTTP (127.0.0.1:8777).

Run manually:  python browser_service.py
Started automatically by the browser tools when needed.
Headless only if OMNI_BROWSER_HEADLESS=1 — default is a visible window
so Revaldo can watch and take over, JARVIS-style.
"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).parent
PROFILE = HERE / "browser_profile"
SHOTS = HERE / "browser_shots"
PORT = 8777

_state = {"pw": None, "ctx": None, "page": None}


def _ensure_page():
    """Return a live page, (re)launching the browser if needed."""
    from playwright.sync_api import sync_playwright

    page = _state["page"]
    if page is not None:
        try:
            if not page.is_closed():
                return page
        except Exception:
            pass
    if _state["pw"] is None:
        _state["pw"] = sync_playwright().start()
    headless = os.environ.get("OMNI_BROWSER_HEADLESS", "") == "1"
    _state["ctx"] = _state["pw"].chromium.launch_persistent_context(
        str(PROFILE), headless=headless
    )
    pages = _state["ctx"].pages
    _state["page"] = pages[0] if pages else _state["ctx"].new_page()
    return _state["page"]


def _page_text(page, limit=4000):
    try:
        text = page.inner_text("body")
    except Exception:
        text = ""
    return " ".join(text.split())[:limit]


def do_open(args):
    page = _ensure_page()
    page.goto(args["url"], timeout=30000, wait_until="domcontentloaded")
    return {"title": page.title(), "url": page.url, "text": _page_text(page)}


def do_read(args):
    page = _ensure_page()
    return {"title": page.title(), "url": page.url, "text": _page_text(page)}


def do_click(args):
    page = _ensure_page()
    target = args.get("text") or args.get("selector") or ""
    if not target:
        return {"error": "give text or selector"}
    try:
        if args.get("text"):
            page.get_by_text(target, exact=False).first.click(timeout=8000)
        else:
            page.click(target, timeout=8000)
    except Exception as e:
        return {"error": f"click failed: {e}"}
    page.wait_for_timeout(800)
    return {"title": page.title(), "url": page.url, "text": _page_text(page, 2000)}


def do_type(args):
    page = _ensure_page()
    selector, text = args.get("selector", ""), args.get("text", "")
    if not selector:
        return {"error": "give a selector (e.g. input[name=q])"}
    try:
        page.fill(selector, text, timeout=8000)
        if args.get("submit"):
            page.press(selector, "Enter")
            page.wait_for_timeout(1000)
    except Exception as e:
        return {"error": f"type failed: {e}"}
    return {"title": page.title(), "url": page.url, "text": _page_text(page, 2000)}


def do_screenshot(args):
    page = _ensure_page()
    SHOTS.mkdir(exist_ok=True)
    path = SHOTS / f"shot-{time.strftime('%Y%m%d-%H%M%S')}.png"
    page.screenshot(path=str(path))
    return {"path": str(path), "url": page.url}


def do_close(args):
    try:
        if _state["ctx"]:
            _state["ctx"].close()
        if _state["pw"]:
            _state["pw"].stop()
    finally:
        _state.update(pw=None, ctx=None, page=None)
    return {"closed": True}


ACTIONS = {
    "open": do_open, "read": do_read, "click": do_click,
    "type": do_type, "screenshot": do_screenshot, "close": do_close,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the daemon quiet
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"ok": True}) if self.path == "/health" else self._send({}, 404)

    def do_POST(self):
        action = self.path.lstrip("/")
        if action not in ACTIONS:
            return self._send({"error": f"unknown action {action}"}, 404)
        try:
            args = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self._send({"ok": True, **ACTIONS[action](args)})
        except Exception as e:
            self._send({"ok": False, "error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    PROFILE.mkdir(exist_ok=True)
    print(f"browser daemon on 127.0.0.1:{PORT}", flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
