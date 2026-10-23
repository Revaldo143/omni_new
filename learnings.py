"""Correction memory — Jarvis 2.0 self-learning loop (part 1).

When sir corrects the bot ("illa, apdi illa — ippadi pannu"), the brain
saves the rule here as plain text. Every future reply injects these
learnings into the system prompt, so corrections stick.

File: learnings.md next to this module. Human-readable, human-editable.
Not synced to git (personal)."""

from __future__ import annotations

import datetime
import os
from pathlib import Path

HERE = Path(__file__).parent
PATH = HERE / "learnings.md"

HEADER = "# Learnings — things sir taught me (auto-saved, editable)\n"


def _ensure() -> None:
    if not PATH.exists():
        PATH.write_text(HEADER, encoding="utf-8")


def add_learning(rule: str) -> str:
    """Save one correction/rule. Returns the saved line."""
    _ensure()
    rule = " ".join(rule.strip().split())
    if not rule:
        return "Empty rule — nothing saved."
    today = datetime.date.today().isoformat()
    # avoid exact duplicates
    existing = PATH.read_text(encoding="utf-8")
    if rule in existing:
        return "Already known, sir — not duplicated."
    with open(PATH, "a", encoding="utf-8") as f:
        f.write(f"- [{today}] {rule}\n")
    return f"Learned, sir: {rule}"


def list_learnings() -> list[str]:
    _ensure()
    lines = []
    for ln in PATH.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln.startswith("- ["):
            lines.append(ln[2:])
    return lines


def learnings_text(max_chars: int = 2000) -> str:
    """Compact block for the system prompt."""
    items = list_learnings()
    if not items:
        return ""
    txt = "\n".join(f"{i+1}. {it}" for i, it in enumerate(items[-20:]))
    return txt[:max_chars]
