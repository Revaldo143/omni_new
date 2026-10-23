"""Structured reminders (Phase 4) — shared by the MCP tools and the
scheduler. A reminder fires only when it has a real due time
('YYYY-MM-DD HH:MM', IST); free-text reminders are stored, never fired.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "omni_memory.db"
FMT = "%Y-%m-%d %H:%M"


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS reminders ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, when_text TEXT, "
        "created_at TEXT DEFAULT (datetime('now')))"
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(reminders)")}
    if "due_at" not in cols:
        conn.execute("ALTER TABLE reminders ADD COLUMN due_at TEXT")
    if "fired" not in cols:
        conn.execute("ALTER TABLE reminders ADD COLUMN fired INTEGER DEFAULT 0")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS scheduler_state ("
        "key TEXT PRIMARY KEY, value TEXT)"
    )
    return conn


def parse_due(when: str) -> str | None:
    """Return canonical 'YYYY-MM-DD HH:MM' if `when` looks like a real
    due time (ISO or that format), else None."""
    w = (when or "").strip().replace("T", " ")
    for fmt in (FMT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(w, fmt)
            return dt.strftime(FMT)
        except ValueError:
            continue
    return None


def add(text: str, when: str) -> tuple[str, str | None]:
    due = parse_due(when)
    with _conn() as conn:
        conn.execute(
            "INSERT INTO reminders (text, when_text, due_at) VALUES (?, ?, ?)",
            (text, when, due),
        )
    return when, due


def due_pending(now_str: str) -> list[tuple[int, str, str]]:
    """Reminders due at or before now_str (canonical FMT), not yet fired."""
    with _conn() as conn:
        return conn.execute(
            "SELECT id, text, due_at FROM reminders "
            "WHERE due_at IS NOT NULL AND due_at <= ? AND COALESCE(fired, 0) = 0 "
            "ORDER BY due_at",
            (now_str,),
        ).fetchall()


def mark_fired(rid: int) -> None:
    with _conn() as conn:
        conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (rid,))


def list_all() -> list[tuple[str, str, str | None, int]]:
    with _conn() as conn:
        return conn.execute(
            "SELECT text, when_text, due_at, COALESCE(fired, 0) FROM reminders ORDER BY id"
        ).fetchall()


def get_state(key: str) -> str:
    with _conn() as conn:
        row = conn.execute(
            "SELECT value FROM scheduler_state WHERE key = ?", (key,)
        ).fetchone()
    return row[0] if row else ""


def set_state(key: str, value: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO scheduler_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
