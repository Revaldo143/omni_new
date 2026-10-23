"""Omni-Core Layer 1 — MCP tools server for the personal agent.

Run standalone:  python tools_server.py   (stdio transport)
Tools: datetime, web search, web page reader, calculator,
       memory (save/recall facts), reminders.
"""
import ast
import html
import operator
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

import memory
import sandbox
import graph_memory
import reminders

mcp = FastMCP("omni-core")
DB_PATH = Path(__file__).parent / "omni_memory.db"


# ---------------- time ----------------
@mcp.tool()
def get_datetime() -> str:
    """Current date and time in India (IST), plus UTC."""
    ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    return ist.strftime("IST: %A, %d %B %Y, %I:%M %p")


# ---------------- calculator ----------------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand)
    raise ValueError("unsupported expression")


@mcp.tool()
def calculate(expression: str) -> str:
    """Evaluate a basic arithmetic expression, e.g. '2500 * 18 / 100'."""
    try:
        return str(_eval(ast.parse(expression, mode="eval")))
    except Exception as e:
        return f"Error: {e}"


# ---------------- web ----------------
def _fetch(url: str, params: dict | None = None) -> str:
    """Fetch a URL via curl (proxy-friendly on locked-down networks)."""
    if params:
        from urllib.parse import urlencode
        url = f"{url}?{urlencode(params)}"
    out = subprocess.run(
        ["curl", "-s", "-L", "--max-time", "20", "-A",
         "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", url],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(f"curl failed ({out.returncode})")
    return out.stdout


def _clean(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


@mcp.tool()
def web_search(query: str) -> str:
    """Search the web (Bing). Returns top results with titles, URLs, snippets."""
    try:
        page = _fetch("https://www.bing.com/search", {"q": query})
    except Exception as e:
        return f"Search failed: {e}"
    results = []
    for block in re.findall(r'<li class="b_algo".*?</li>', page, re.S):
        m = re.search(r'<h2><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        p = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        if m:
            results.append(f"- {_clean(m.group(2))}\n  {m.group(1)}\n  {_clean(p.group(1)) if p else ''}")
        if len(results) >= 5:
            break
    return "\n".join(results) if results else "No results found."


@mcp.tool()
def read_webpage(url: str) -> str:
    """Fetch a web page and return its readable text (truncated)."""
    try:
        page = _fetch(url)
    except Exception as e:
        return f"Fetch failed: {e}"
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    text = _clean(text)
    return re.sub(r"\s+", " ", text).strip()[:4000]


# ---------------- code sandbox (Layer 3) ----------------
@mcp.tool()
def run_python(code: str) -> str:
    """Run Python code in a sandbox (E2B cloud microVM if E2B_API_KEY is set,
    otherwise a local fallback) and return its printed output.
    Use for data work, quick scripts, charts math, text processing, etc."""
    return sandbox.run_python(code)


# ---------------- memory ----------------
@mcp.tool()
def save_fact(fact: str) -> str:
    """Save a durable fact about the user to long-term memory."""
    memory.add_fact(fact)
    graph_memory.add_entity(fact, "fact")
    return f"Saved: {fact}"


@mcp.tool()
def recall_facts() -> str:
    """List everything saved in the user's long-term memory."""
    facts = memory.list_facts()
    return "\n".join(f"- {f}" for f in facts) if facts else "Nothing saved yet."


# ---------------- reminders ----------------
@mcp.tool()
def set_reminder(text: str, when: str) -> str:
    """Store a reminder. For it to actually FIRE, pass 'when' as a real
    due time 'YYYY-MM-DD HH:MM' (IST) — call get_datetime first if you
    are unsure of today's date. Free text like 'tomorrow morning' is
    stored as a note and will NOT fire."""
    label, due = reminders.add(text, when)
    if due:
        return f"Reminder set: '{text}' — fires {due} IST."
    return f"Reminder stored as a note (no fire time): '{text}' ({label})."


@mcp.tool()
def list_reminders() -> str:
    """List stored reminders with their fire times and status."""
    rows = reminders.list_all()
    if not rows:
        return "No reminders stored."
    out = []
    for text, when_text, due, fired in rows:
        if fired:
            status = "fired ✅"
        elif due:
            status = f"fires {due}"
        else:
            status = "note only (no fire time)"
        out.append(f"- {text} — {status}")
    return "\n".join(out)


# ---------------- graph memory (Layer 4) ----------------
@mcp.tool()
def remember_entity(name: str, type: str = "thing", note: str = "") -> str:
    """Save an entity (person, place, project, thing) into the knowledge
    graph. Use for anything the user mentions that has identity —
    people, their shop, projects, places."""
    return graph_memory.add_entity(name, type, note)


@mcp.tool()
def link_entities(source: str, relation: str, target: str) -> str:
    """Create a relationship between two entities in the knowledge graph,
    e.g. source='Kirana Store', relation='OPENS_AT', target='6 AM'."""
    return graph_memory.add_relation(source, relation, target)


@mcp.tool()
def recall_about(name: str) -> str:
    """Everything the knowledge graph knows about an entity, including
    its relationships in both directions."""
    return graph_memory.about(name)


@mcp.tool()
def search_memory(keyword: str) -> str:
    """Search the knowledge graph for entities matching a keyword."""
    return graph_memory.search(keyword)


# ---------------- browser control (Phase 2) ----------------
import json as _json
import subprocess as _sp
import time as _time
import urllib.request as _urlreq
from pathlib import Path as _Path

_BROWSER = "http://127.0.0.1:8777"
_no_proxy = _urlreq.build_opener(_urlreq.ProxyHandler({}))


def _browser_call(action: str, args: dict | None = None) -> str:
    def _post(act, payload):
        req = _urlreq.Request(
            _BROWSER + "/" + act,
            data=_json.dumps(payload or {}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with _no_proxy.open(req, timeout=45) as r:
            return _json.loads(r.read())

    try:
        with _no_proxy.open(_BROWSER + "/health", timeout=2) as r:
            r.read()
    except Exception:
        # Daemon down — start it detached, then wait for health.
        flags = getattr(_sp, "DETACHED_PROCESS", 0) if os.name == "nt" else 0
        kw = {"start_new_session": True} if os.name != "nt" else {"creationflags": flags}
        _sp.Popen(
            [sys.executable, str(_Path(__file__).parent / "browser_service.py")],
            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, **kw,
        )
        for _ in range(30):
            _time.sleep(0.5)
            try:
                with _no_proxy.open(_BROWSER + "/health", timeout=2) as r:
                    r.read()
                break
            except Exception:
                continue
    try:
        out = _post(action, args)
    except Exception as e:
        return f"Browser error: {e} (is Playwright installed? run: python -m playwright install chromium)"
    if not out.get("ok"):
        return f"Browser error: {out.get('error', 'unknown')}"
    bits = [f"Title: {out.get('title', '')}", f"URL: {out.get('url', '')}"]
    if out.get("path"):
        bits.append(f"Screenshot saved: {out['path']}")
    if out.get("text"):
        bits.append(out["text"])
    return "\n".join(bits)


@mcp.tool()
def browser_open(url: str) -> str:
    """Open a URL in the agent's own visible browser (persistent logins).
    Returns the page title and readable text."""
    return _browser_call("open", {"url": url})


@mcp.tool()
def browser_read() -> str:
    """Read the current browser page (title, URL, text)."""
    return _browser_call("read")


@mcp.tool()
def browser_click(text: str = "", selector: str = "") -> str:
    """Click something on the current page — by visible text or CSS selector."""
    return _browser_call("click", {"text": text, "selector": selector})


@mcp.tool()
def browser_type(selector: str, text: str, submit: bool = False) -> str:
    """Type into a field (CSS selector, e.g. 'input[name=q]'). Set submit
    to press Enter afterwards (e.g. for search boxes)."""
    return _browser_call("type", {"selector": selector, "text": text, "submit": submit})


@mcp.tool()
def browser_screenshot() -> str:
    """Take a screenshot of the current page; returns the saved file path."""
    return _browser_call("screenshot")


@mcp.tool()
def browser_close() -> str:
    """Close the agent's browser."""
    return _browser_call("close")


# ---------------- economical data skills (Jarvis 2.0) ----------------
# One HTTP call per answer — never burn 10 browser steps for a price.

def _json_fetch(url: str) -> dict:
    import json as _json
    out = subprocess.run(
        ["curl", "-s", "-L", "--max-time", "15", "-A", "curl/8.5.0", url],
        capture_output=True, text=True, timeout=25,
    )
    if out.returncode != 0:
        raise RuntimeError(f"fetch failed ({out.returncode})")
    return _json.loads(out.stdout)


@mcp.tool()
def get_price(symbol: str) -> str:
    """Get a live price in ONE call. symbol: XAU (gold), XAG (silver),
    forex like EURUSD / USDINR / GBPUSD, or crypto like BTC / ETH / SOL
    (also accepts full names: bitcoin, ethereum, solana). No API key needed."""
    s = symbol.strip().upper().replace("/", "")
    try:
        if s in ("XAU", "GOLD"):
            d = _json_fetch("https://api.gold-api.com/price/XAU")
            return f"Gold (XAU): ${d['price']:,.2f}/oz  (updated {d.get('updatedAtReadable', '')})"
        if s in ("XAG", "SILVER"):
            d = _json_fetch("https://api.gold-api.com/price/XAG")
            return f"Silver (XAG): ${d['price']:,.2f}/oz  (updated {d.get('updatedAtReadable', '')})"
        # forex: 6-letter pair like EURUSD
        if len(s) == 6 and s.isalpha():
            base, tgt = s[:3], s[3:]
            d = _json_fetch(
                f"https://api.frankfurter.app/latest?from={base}&to={tgt}")
            rate = d["rates"][tgt]
            return f"{base}/{tgt}: {rate}  (ECB reference, {d.get('date', '')})"
        # crypto
        cmap = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
                "DOGE": "dogecoin", "XRP": "ripple"}
        cid = cmap.get(s, s.lower())
        d = _json_fetch(
            f"https://api.coingecko.com/api/v3/simple/price?ids={cid}&vs_currencies=usd")
        return f"{symbol.upper()}: ${d[cid]['usd']:,.2f}  (CoinGecko)"
    except Exception as e:
        return f"Price lookup failed for {symbol}: {e}"


@mcp.tool()
def deep_research(topic: str) -> str:
    """Research a topic: runs several searches, reads the top pages, and
    returns a compiled brief with sources. Use for freelance gig research,
    market questions, learning a subject. Bounded: ~4 searches + 4 pages."""
    brief = [f"# Research: {topic}\n"]
    queries = [topic, f"{topic} guide", f"{topic} 2026"]
    seen = 0
    for q in queries:
        res = web_search(q)
        brief.append(f"## Search: {q}\n{res}\n")
        for m in re.finditer(r"https?://[^\s)]+", res):
            if seen >= 4:
                break
            url = m.group(0)
            if "bing.com" in url:
                continue
            page = read_webpage(url)
            brief.append(f"### Source: {url}\n{page[:1500]}\n")
            seen += 1
        if seen >= 4:
            break
    return "\n".join(brief)[:8000]


@mcp.tool()
def draft_doc(title: str, content_markdown: str) -> str:
    """Save a markdown draft (proposal, report, notes) to the drafts folder.
    Returns the file path."""
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", title).strip("_")[:40] or "draft"
    path = Path(__file__).parent / "drafts" / f"{safe}.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(f"# {title}\n\n{content_markdown}\n", encoding="utf-8")
    return f"Draft saved: {path}"


@mcp.tool()
def find_gigs(keywords: str) -> str:
    """Search freelance gigs (Upwork, Fiverr, Freelancer, Toptal, Contra).
    Returns recent listings with links. Bounded: 3 searches."""
    out = []
    for q in [f"site:upwork.com {keywords} freelance job",
              f"{keywords} freelance gig hiring 2026",
              f"site:contra.com {keywords} freelance"]:
        out.append(f"## {q}\n{web_search(q)}")
    return "\n".join(out)[:6000]


@mcp.tool()
def find_jobs(keywords: str, location: str = "remote") -> str:
    """Search online jobs (LinkedIn, Indeed, Wellfound, YC Jobs).
    Bounded: 3 searches."""
    out = []
    for q in [f"site:linkedin.com/jobs {keywords} {location}",
              f"{keywords} remote jobs hiring 2026",
              f"site:wellfound.com {keywords} startup jobs"]:
        out.append(f"## {q}\n{web_search(q)}")
    return "\n".join(out)[:6000]


# ---------------- self-learning loop (Jarvis 2.0) ----------------
# Part 2: the agent can propose new skills. A proposal needs sir's explicit
# Telegram approval (the code is shown in the approval prompt). Approved
# skills land in skills/ and become real MCP tools on the very next turn,
# because the MCP server process restarts for every chat turn.
# Part 1 (correction memory) lives in learnings.py.

import concurrent.futures
import importlib.util
import json as _json

import learnings

SKILLS_DIR = Path(__file__).parent / "skills"
SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


def _register_skill(meta: dict, run_fn) -> None:
    """Turn a SPEC + run() into a real MCP tool with a typed signature."""
    props = (meta.get("parameters") or {}).get("properties", {}) or {}
    required = set((meta.get("parameters") or {}).get("required", []) or [])
    sig_parts = []
    for pname in props:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", pname):
            raise ValueError(f"bad parameter name: {pname}")
        sig_parts.append(f"{pname}: str" if pname in required
                         else f"{pname}: str = ''")
    fname = re.sub(r"\W", "_", meta["name"])
    fwd = ", ".join(f"{p}={p}" for p in props)
    code = (
        f"def {fname}({', '.join(sig_parts)}):\n"
        f'    """{meta["description"]}"""\n'
        f"    return _SKILL_RUN({fwd})"
    )
    g = {"_SKILL_RUN": lambda **kw: str(run_fn(**kw))}
    ns: dict = {}
    exec(code, g, ns)
    mcp.tool(name=meta["name"], description=meta["description"])(ns[fname])


def _load_skills() -> None:
    if not SKILLS_DIR.is_dir():
        return
    for f in sorted(SKILLS_DIR.glob("*.py")):
        if f.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"jarvis_skill_{f.stem}", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            _register_skill(mod.SPEC, mod.run)
        except Exception as e:
            print(f"[skills] {f.stem} failed to load: {e}")


def _validate_skill_code(name: str, code: str):
    """Compile + exec the proposed code, return (SPEC, run_fn) or raise."""
    if not SKILL_NAME_RE.match(name):
        raise ValueError(
            "name must match ^[a-z][a-z0-9_]{2,40}$ (lowercase, 3-40 chars)")
    compiled = compile(code, f"<skill:{name}>", "exec")
    ns: dict = {}
    exec(compiled, {"__builtins__": __builtins__}, ns)
    spec_meta, run_fn = ns.get("SPEC"), ns.get("run")
    if not isinstance(spec_meta, dict):
        raise ValueError("code must define SPEC = {...} dict")
    if spec_meta.get("name") != name:
        raise ValueError("SPEC['name'] must equal the proposed name")
    if not spec_meta.get("description"):
        raise ValueError("SPEC needs a description")
    params = spec_meta.get("parameters") or {}
    if not isinstance(params.get("properties"), dict):
        raise ValueError("SPEC['parameters']['properties'] must be a dict")
    if not callable(run_fn):
        raise ValueError("code must define run(**kwargs)")
    return spec_meta, run_fn


@mcp.tool()
def propose_skill(name: str, code: str, test_args_json: str = "{}") -> str:
    """Propose a NEW skill (Python tool) you don't have yet. NEEDS SIR'S
    APPROVAL — he sees the code on Telegram and taps Yes/No.

    code must define:
      SPEC = {"name": "<same as name>", "description": "...",
              "parameters": {"type": "object",
                             "properties": {"arg": {"type": "string"}},
                             "required": ["arg"]}}
      def run(**kwargs) -> str: ...

    All args arrive as strings. Keep it dependency-free (stdlib only) and
    fast. test_args_json: sample args for the smoke test, e.g.
    '{"arg": "hello"}'. The skill activates only if the smoke test passes.
    """
    try:
        target = SKILLS_DIR / f"{name}.py"
        if target.exists():
            return f"Skill '{name}' already exists — propose an update instead."
        spec_meta, run_fn = _validate_skill_code(name, code)
        try:
            test_args = _json.loads(test_args_json or "{}")
        except Exception:
            return "test_args_json is not valid JSON."
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(run_fn, **test_args)
            try:
                out = fut.result(timeout=30)
            except concurrent.futures.TimeoutError:
                return ("Smoke test timed out after 30s — skill NOT "
                        "activated. Make it faster or bounded.")
        result_preview = str(out)[:300]
        SKILLS_DIR.mkdir(exist_ok=True)
        target.write_text(code, encoding="utf-8")
        return (f"✅ Skill '{name}' approved and ACTIVATED. Smoke test output: "
                f"{result_preview}\nIt is a real tool from the next message.")
    except Exception as e:
        return f"Skill NOT activated: {e}"


@mcp.tool()
def learn_correction(rule: str) -> str:
    """Save something sir just corrected — a preference, a fact about how
    he wants things done, a mistake not to repeat. One clear sentence.
    It persists in learnings.md and is injected into every future reply."""
    try:
        return learnings.add_learning(rule)
    except Exception as e:
        return f"Could not save: {e}"


_load_skills()


if __name__ == "__main__":
    mcp.run()  # stdio
