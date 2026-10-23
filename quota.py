"""Daily LLM usage tracker — Jarvis 2.0.

Counts every model call per (day, provider, model) in SQLite and enforces a
daily budget. Free tiers die silently at 20/day; this makes the limit VISIBLE
and lets the brain degrade gracefully instead of crashing mid-task.

Env:
    OMNI_DAILY_BUDGET — max model calls per day (default 18, just under the
                        Gemini free-tier 20 so we never slam the wall)

The DB lives next to the memory DB (same directory as this file).
"""

from __future__ import annotations

import datetime
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "jarvis_quota.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute(
        "CREATE TABLE IF NOT EXISTS usage("
        "day TEXT, provider TEXT, model TEXT, calls INTEGER, "
        "PRIMARY KEY(day, provider, model))"
    )
    return c


def _today() -> str:
    return datetime.date.today().isoformat()


def budget() -> int:
    try:
        return max(1, int(os.environ.get("OMNI_DAILY_BUDGET", "18")))
    except ValueError:
        return 18


def used_today(provider: str = "", model: str = "") -> int:
    """Calls made today, optionally filtered."""
    c = _conn()
    try:
        if provider and model:
            row = c.execute(
                "SELECT calls FROM usage WHERE day=? AND provider=? AND model=?",
                (_today(), provider, model),
            ).fetchone()
            return row[0] if row else 0
        row = c.execute(
            "SELECT COALESCE(SUM(calls),0) FROM usage WHERE day=?", (_today(),)
        ).fetchone()
        return row[0] if row else 0
    finally:
        c.close()


def remaining() -> int:
    return max(0, budget() - used_today())


def check() -> tuple[bool, int, int]:
    """(ok, used, budget). ok=False means: do not call the model."""
    u, b = used_today(), budget()
    return (u < b, u, b)


def bump(provider: str, model: str, n: int = 1) -> None:
    c = _conn()
    try:
        c.execute(
            "INSERT INTO usage(day, provider, model, calls) VALUES(?,?,?,?) "
            "ON CONFLICT(day, provider, model) DO UPDATE SET calls=calls+?",
            (_today(), provider, model, n, n),
        )
        c.commit()
    finally:
        c.close()


def quota_message() -> str:
    u, b = used_today(), budget()
    return (
        "⚠️ Sir, inniku quota mudinjiduchu — "
        f"daily budget {b} calls la {u} use aachu. "
        "Naalaikku auto reset aagidum. Udane continue panna, .env la "
        "vera model/provider ku maathunga (LLM_PROVIDER=openai, illa "
        "OMNI_FLASH_MODEL vera model)."
    )
