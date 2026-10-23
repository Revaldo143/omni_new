"""Jarvis 2.0 brain — provider-agnostic, quota-aware, budget-capped.

- LLM_PROVIDER=gemini (default) or openai (any OpenAI-compatible endpoint).
- Cheap model for routine chat, smart model for hard thinking ("deep:" forces it).
- Every model call is counted against a daily budget (quota.py). When the
  budget is gone the user gets an honest Tanglish message — never silence.
- Tool loop: max 8 iterations, stops early when budget runs low.
- Approval gates: tools that can change the outside world (submitting forms)
  need the caller's approver() to say yes. Default: deny.

Inject `approver` (callable) from the front-end:
    brain.chat("hi", approver=lambda name, args: True)   # tests / CLI
Telegram passes an interactive one (inline Yes/No buttons).
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import traceback
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import graph_memory  # noqa: F401  (ensures graph tables exist early)
import learnings
import memory
import personality
import providers
import quota

HERE = Path(__file__).parent

PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()

# Model names per provider. Gemini: env-driven (his key uses 3.6-flash).
# OpenAI-compat: one model for both tiers unless OPENAI_SMART_MODEL is set.
if PROVIDER == "openai":
    CHEAP_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    SMART_MODEL = os.environ.get("OPENAI_SMART_MODEL", CHEAP_MODEL)
else:
    CHEAP_MODEL = os.environ.get("OMNI_FLASH_MODEL", "gemini-3.5-flash")
    SMART_MODEL = os.environ.get("OMNI_PRO_MODEL", "gemini-3.1-pro-preview")

LAST_ROUTE = {"model": CHEAP_MODEL, "note": "flash", "provider": PROVIDER}

MAX_TOOL_ROUNDS = 8
RESERVE_CALLS = 2  # never spend the last N budget calls inside a tool loop

SMART_WORDS = (
    "think", "plan", "analyze", "analyse", "compare", "decide", "decision",
    "strategy", "design", "architect", "debug", "error", "why", "explain",
    "research", "build", "code", "write a", "evaluate", "review", "best",
    "yosi", "yosichu", "plan pannu", "compare pannu", "mudivu",
    "eppadi", "reason", "solve",
)
REMEMBER_RE = re.compile(r"^\s*(remember|nyabagam vai|save)[:\-]?\s*(.+)", re.I)


def route_model(text: str) -> tuple[str, str]:
    t = text.strip().lower()
    if t.startswith("deep:"):
        return SMART_MODEL, "smart (forced: deep:)"
    if len(text) > 300:
        return SMART_MODEL, "smart (long task)"
    if any(w in t for w in SMART_WORDS):
        return SMART_MODEL, "smart (complex)"
    return CHEAP_MODEL, "cheap"


# ------------------------------------------------------------------ errors

def _is_quota_error(e: BaseException) -> bool:
    # Unwrap tenacity RetryError / chained causes — the real 429 often hides
    # inside .last_attempt or __cause__ where a plain str() check misses it.
    seen, stack = set(), [e]
    while stack:
        cur = stack.pop()
        if id(cur) in seen or not isinstance(cur, BaseException):
            continue
        seen.add(id(cur))
        s = str(cur)
        if any(k in s for k in ("429", "503", "404", "RESOURCE_EXHAUSTED",
                                "quota", "Quota", "rate_limit")):
            return True
        for nxt in (getattr(cur, "__cause__", None),
                    getattr(cur, "__context__", None)):
            if isinstance(nxt, BaseException):
                stack.append(nxt)
        la = getattr(cur, "last_attempt", None)
        if la is not None:
            try:
                exc = la.exception()
            except Exception:
                exc = None
            if isinstance(exc, BaseException):
                stack.append(exc)
    return False


def format_error(e: BaseException) -> str:
    if isinstance(e, BaseExceptionGroup):
        return "; ".join(format_error(sub) for sub in e.exceptions)
    return f"{type(e).__name__}: {e}"


def _log_error(e: BaseException) -> None:
    try:
        with open(HERE / "jarvis_error.log", "a", encoding="utf-8") as f:
            f.write("\n--- chat error ---\n")
            traceback.print_exception(e, file=f)
    except Exception:
        pass


# ---------------------------------------------------------- approval gates

def needs_approval(tool_name: str, args: dict) -> bool:
    """Tools that change the outside world need an explicit yes."""
    if tool_name == "browser_type" and args.get("submit"):
        return True  # submitting a form can post/buy/register
    if tool_name == "propose_skill":
        return True  # new code running as a tool — sir reviews it first
    return False


def _describe_call(name: str, args: dict) -> str:
    argstr = ", ".join(f"{k}={str(v)[:60]}" for k, v in args.items())
    return f"{name}({argstr})"


# ------------------------------------------------------------------ prompt

def _system_prompt() -> str:
    facts = memory.list_facts()
    summary = memory.latest_summary() or ""
    base = personality.build_system_prompt("Jarvis", facts, summary)
    learned = learnings.learnings_text()
    learned_block = (
        f"\n\nThings sir taught you (never forget these):\n{learned}"
        if learned else ""
    )
    return base + learned_block + (
        "\n\nJarvis 2.0 rules — follow strictly:\n"
        "1. PRICES: always use get_price for gold/forex/crypto. One call. "
        "Never open the browser for a price.\n"
        "2. DATA before BROWSER: for facts, use search/research tools. "
        "The browser is for *interacting* with pages, not reading data.\n"
        "3. ECONOMY: you have a daily model-call budget. Batch independent "
        "tool calls in one block. Short answers.\n"
        "4. If a tool needs approval and it is denied, say so plainly and "
        "offer an alternative.\n"
        "5. LEARNING: if sir corrects you ('illa', 'apdi illa', 'thappu'), "
        "call learn_correction with one clear sentence capturing the rule.\n"
        "6. SKILLS: if a task needs a tool you don't have, write it with "
        "propose_skill (SPEC + run, stdlib only, with a smoke test). "
        "Sir approves the code on Telegram before it activates.\n"
    )


def _sanitize(schema: dict) -> dict:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    keep: dict = {"type": "object"}
    if isinstance(schema.get("properties"), dict):
        keep["properties"] = {p: _sanitize(s)
                              for p, s in schema["properties"].items()}
    if isinstance(schema.get("required"), list):
        keep["required"] = schema["required"]
    return keep


# ---------------------------------------------------------------- tool loop

async def _run_with_tools(user_text: str, model: str,
                          approver=None) -> str:
    provider_name = PROVIDER
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(HERE / "tools_server.py")],
        env={k: v for k, v in os.environ.items() if isinstance(v, str)},
    )
    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(stdio_client(server))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        tools_result = await session.list_tools()
        tools = [
            {"name": t.name,
             "description": t.description or "",
             "parameters": _sanitize(t.inputSchema)}
            for t in tools_result.tools
        ]

        history: list[dict] = [
            {"role": m["role"], "text": m["text"]}
            for m in memory.recent_messages(limit=20)
        ]
        history.append({"role": "user", "text": user_text})

        provider = providers.get_provider(model)
        system = _system_prompt()

        for round_i in range(MAX_TOOL_ROUNDS):
            ok, _, _ = quota.check()
            if not ok:
                return quota.quota_message()
            # Keep a reserve so the final answer can still be written.
            if round_i > 0 and quota.remaining() <= RESERVE_CALLS:
                break
            resp = provider.generate(system, history, tools)
            quota.bump(provider_name, model)
            if not resp.tool_calls:
                text = (resp.text or "").strip()
                if text:
                    return text
                break
            history.append({
                "role": "model",
                "text": resp.text or "",
                "tool_calls": [
                    {"id": c.id, "name": c.name, "args": c.args}
                    for c in resp.tool_calls
                ],
            })
            for call in resp.tool_calls:
                if needs_approval(call.name, call.args):
                    allowed = False
                    if approver is not None:
                        allowed = await asyncio.to_thread(
                            approver, call.name, call.args)
                    if not allowed:
                        history.append({
                            "role": "tool", "tool_call_id": call.id,
                            "tool_name": call.name,
                            "text": ("REFUSED: this action needs your explicit "
                                     "approval. Ask the user first."),
                        })
                        continue
                result = await session.call_tool(call.name, call.args)
                text = "".join(
                    c.text for c in result.content
                    if getattr(c, "type", "") == "text"
                )
                history.append({
                    "role": "tool", "tool_call_id": call.id,
                    "tool_name": call.name, "text": text[:4000],
                })

        # Loop ended without a final answer — one last no-tools nudge.
        ok, _, _ = quota.check()
        if not ok:
            return quota.quota_message()
        provider = providers.get_provider(model)
        resp = provider.generate(
            system, history + [{"role": "user",
                                "text": ("Summarize the tool results above into "
                                         "a short final answer for the user.")}],
            tools=None)
        quota.bump(provider_name, model)
        text = (resp.text or "").strip()
        return text or ("⚠️ Sir, tools run pannen aana final answer kedaikala — "
                        "konjam specific ah ketta try pannren.")


def _generate(user_text: str, model: str, approver=None) -> str:
    return asyncio.run(_run_with_tools(user_text, model, approver))


# ------------------------------------------------------------------- chat

COMPACT_AT = 60
COMPACT_TAKE = 40


def _maybe_compact() -> None:
    try:
        if memory.message_count() <= COMPACT_AT:
            return
        old = memory.oldest_messages(COMPACT_TAKE)
        if not old:
            return
        transcript = "\n".join(f"{m['role']}: {m['text']}" for m in old)
        prev = memory.latest_summary()
        if prev:
            transcript = (f"Previous summary:\n{prev}\n\nOlder messages:\n"
                          f"{transcript}")
        ok, _, _ = quota.check()
        if not ok:
            return
        provider = providers.get_provider(CHEAP_MODEL)
        resp = provider.generate(
            "Summarize into a compact factual brief (max 150 words): keep "
            "names, decisions, preferences, open tasks and dates. No fluff.",
            [{"role": "user", "text": transcript}])
        quota.bump(PROVIDER, CHEAP_MODEL)
        summary = (resp.text or "").strip()
        if summary:
            memory.apply_compaction(summary, [m["id"] for m in old])
    except Exception:
        pass


def chat(user_text: str, approver=None) -> str:
    """One message end-to-end: route, quota, tools, memory, compaction."""
    m = REMEMBER_RE.match(user_text)
    if m:
        fact = m.group(2).strip()
        memory.add_fact(fact)
        try:
            graph_memory.add_entity(fact, "fact")
        except Exception:
            pass
        memory.add_message("user", user_text)
        reply = "Note panniten, sir. ✅"
        memory.add_message("model", reply)
        return reply

    clean_text = user_text.strip()
    if clean_text.lower().startswith("deep:"):
        clean_text = clean_text[5:].strip()

    ok, used, b = quota.check()
    if not ok:
        return quota.quota_message()

    model, why = route_model(user_text)
    quota_hit = False
    try:
        reply = _generate(clean_text, model, approver)
        LAST_ROUTE.update(model=model, note=why, provider=PROVIDER)
    except RuntimeError:
        raise
    except Exception as e:
        quota_hit = _is_quota_error(e)
        _log_error(e)
        if quota_hit:
            reply = quota.provider_quota_message()
            LAST_ROUTE.update(model=model, note="quota exhausted",
                              provider=PROVIDER)
        else:
            # Non-quota failure: one cheap no-tools retry, then honest error.
            try:
                provider = providers.get_provider(CHEAP_MODEL)
                ok2, _, _ = quota.check()
                if not ok2:
                    return quota.quota_message()
                resp = provider.generate(
                    _system_prompt(),
                    [{"role": "user", "text": clean_text}])
                quota.bump(PROVIDER, CHEAP_MODEL)
                reply = (resp.text or "").strip()
                LAST_ROUTE.update(model=CHEAP_MODEL, note="cheap (no tools)",
                                  provider=PROVIDER)
            except Exception as e2:
                _log_error(e2)
                if _is_quota_error(e2):
                    return quota.provider_quota_message()
                raise

    try:
        memory.add_message("user", user_text)
        if reply:
            memory.add_message("model", reply)
        _maybe_compact()
    except Exception as e:
        if _is_quota_error(e):
            return quota.provider_quota_message()
        raise

    if reply:
        return reply
    return quota.provider_quota_message() if quota_hit else (
        "⚠️ Sir, answer empty ah vanthuruchu — marupadiyum try pannunga.")
