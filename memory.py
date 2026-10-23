"""Persistent memory for the personal agent.

Two stores, both in one SQLite file:
  - facts: durable things the user wants remembered (name, preferences, ...)
  - messages: full conversation history (last N are sent to the model)
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "omni_memory.db"


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,          -- 'user' | 'model'
            text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """
    )
    return conn


# ---------- facts ----------
def add_fact(fact: str) -> None:
    fact = fact.strip()
    if not fact:
        return
    with _conn() as conn:
        if not conn.execute("SELECT 1 FROM facts WHERE fact = ?", (fact,)).fetchone():
            conn.execute("INSERT INTO facts (fact) VALUES (?)", (fact,))


def list_facts() -> list[str]:
    with _conn() as conn:
        return [r[0] for r in conn.execute("SELECT fact FROM facts ORDER BY id")]


def delete_fact(fact: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM facts WHERE fact = ?", (fact,))


# ---------- conversation history ----------
def add_message(role: str, text: str) -> None:
    with _conn() as conn:
        conn.execute("INSERT INTO messages (role, text) VALUES (?, ?)", (role, text))


def recent_messages(limit: int = 20) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, text FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"role": r, "text": t} for r, t in reversed(rows)]


def clear_history() -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM summaries")


# ---------- event compaction (Layer 4) ----------
def message_count() -> int:
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


def oldest_messages(limit: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, role, text FROM messages ORDER BY id ASC LIMIT ?", (limit,)
        ).fetchall()
    return [{"id": i, "role": r, "text": t} for i, r, t in rows]


def apply_compaction(summary_text: str, message_ids: list[int]) -> None:
    """Replace old messages with a summary (event compaction)."""
    if not message_ids:
        return
    with _conn() as conn:
        conn.execute("INSERT INTO summaries (text) VALUES (?)", (summary_text,))
        conn.execute(
            f"DELETE FROM messages WHERE id IN ({','.join('?' * len(message_ids))})",
            message_ids,
        )


def latest_summary() -> str:
    with _conn() as conn:
        row = conn.execute(
            "SELECT text FROM summaries ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row[0] if row else ""
