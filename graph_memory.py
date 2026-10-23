"""Omni-Core Layer 4 — knowledge-graph memory.

Entities (people, places, projects, things) and relationships between
them, so the agent remembers *structure*, not just flat facts:
  (Kirana Store)-[:OPENS_AT]->(6 AM), (Revaldo)-[:RUNS]->(Kirana Store)

Backends:
  - FalkorDB when FALKORDB_HOST is set in .env (local server or
    FalkorDB Cloud; graph name: omni_memory)
  - Built-in SQLite graph (nodes/edges tables) otherwise — zero setup.

Every result is labeled with the backend that served it.
"""
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "omni_memory.db"
GRAPH_NAME = "omni_memory"


def _backend() -> str:
    return "falkordb" if os.environ.get("FALKORDB_HOST", "").strip() else "sqlite"


# ---------------- FalkorDB backend ----------------
def _falkor():
    from falkordb import FalkorDB

    db = FalkorDB(
        host=os.environ["FALKORDB_HOST"],
        port=int(os.environ.get("FALKORDB_PORT", "6379")),
        password=os.environ.get("FALKORDB_PASSWORD") or None,
    )
    return db.select_graph(GRAPH_NAME)


def _fk_add_entity(name, etype, note):
    g = _falkor()
    g.query(
        "MERGE (e:Entity {name: $name}) SET e.type = $type, e.note = $note",
        {"name": name, "type": etype, "note": note},
    )


def _fk_add_relation(src, relation, dst):
    g = _falkor()
    rel = "".join(c if c.isalnum() else "_" for c in relation.upper())
    g.query(
        f"MERGE (a:Entity {{name: $s}}) MERGE (b:Entity {{name: $d}}) "
        f"MERGE (a)-[:{rel}]->(b)",
        {"s": src, "d": dst},
    )


def _fk_about(name):
    g = _falkor()
    out = g.query(
        "MATCH (e:Entity {name: $n})-[r]->(o) RETURN type(r), o.name",
        {"n": name},
    ).result_set
    inc = g.query(
        "MATCH (e:Entity {name: $n})<-[r]-(o) RETURN type(r), o.name",
        {"n": name},
    ).result_set
    node = g.query(
        "MATCH (e:Entity {name: $n}) RETURN e.type, e.note", {"n": name}
    ).result_set
    return node, out, inc


def _fk_search(keyword):
    g = _falkor()
    rows = g.query(
        "MATCH (e:Entity) WHERE toLower(e.name) CONTAINS toLower($k) "
        "OR toLower(e.note) CONTAINS toLower($k) RETURN e.name, e.type LIMIT 20",
        {"k": keyword},
    ).result_set
    return rows


def _fk_stats():
    g = _falkor()
    n = g.query("MATCH (e:Entity) RETURN count(e)").result_set[0][0]
    r = g.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    return n, r


# ---------------- SQLite backend ----------------
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS g_nodes (
            name TEXT PRIMARY KEY, type TEXT DEFAULT 'thing', note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS g_edges (
            src TEXT, relation TEXT, dst TEXT,
            UNIQUE(src, relation, dst)
        );
        """
    )
    return conn


def _sq_add_entity(name, etype, note):
    with _conn() as c:
        c.execute(
            "INSERT INTO g_nodes (name, type, note) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET type=excluded.type, note=excluded.note",
            (name, etype, note),
        )


def _sq_add_relation(src, relation, dst):
    with _conn() as c:
        for n in (src, dst):
            c.execute("INSERT OR IGNORE INTO g_nodes (name) VALUES (?)", (n,))
        c.execute(
            "INSERT OR IGNORE INTO g_edges (src, relation, dst) VALUES (?, ?, ?)",
            (src, relation, dst),
        )


def _sq_about(name):
    with _conn() as c:
        node = c.execute("SELECT type, note FROM g_nodes WHERE name = ?", (name,)).fetchone()
        out = c.execute("SELECT relation, dst FROM g_edges WHERE src = ?", (name,)).fetchall()
        inc = c.execute("SELECT relation, src FROM g_edges WHERE dst = ?", (name,)).fetchall()
    return node, out, inc


def _sq_search(keyword):
    with _conn() as c:
        return c.execute(
            "SELECT name, type FROM g_nodes WHERE name LIKE ? OR note LIKE ? LIMIT 20",
            (f"%{keyword}%", f"%{keyword}%"),
        ).fetchall()


def _sq_stats():
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM g_nodes").fetchone()[0]
        r = c.execute("SELECT COUNT(*) FROM g_edges").fetchone()[0]
    return n, r


# ---------------- public API ----------------
def add_entity(name: str, etype: str = "thing", note: str = "") -> str:
    name = name.strip()
    if not name:
        return "Empty name — nothing stored."
    if _backend() == "falkordb":
        _fk_add_entity(name, etype, note)
    else:
        _sq_add_entity(name, etype, note)
    return f"[{_backend()}] Entity saved: {name} ({etype})"


def add_relation(src: str, relation: str, dst: str) -> str:
    src, dst, relation = src.strip(), dst.strip(), relation.strip()
    if not (src and dst and relation):
        return "Need source, relation and target."
    if _backend() == "falkordb":
        _fk_add_relation(src, relation, dst)
    else:
        _sq_add_relation(src, relation, dst)
    return f"[{_backend()}] Linked: {src} -[{relation}]-> {dst}"


def about(name: str) -> str:
    if _backend() == "falkordb":
        node, out, inc = _fk_about(name)
        node = node[0] if node else None
    else:
        node, out, inc = _sq_about(name)
    if not node:
        return f"[{_backend()}] Nothing known about '{name}' yet."
    lines = [f"[{_backend()}] {name} — type: {node[0] or 'thing'}, note: {node[1] or '-'}"]
    for rel, other in out:
        lines.append(f"  {name} -[{rel}]-> {other}")
    for rel, other in inc:
        lines.append(f"  {other} -[{rel}]-> {name}")
    return "\n".join(lines)


def search(keyword: str) -> str:
    rows = _fk_search(keyword) if _backend() == "falkordb" else _sq_search(keyword)
    if not rows:
        return f"[{_backend()}] No graph matches for '{keyword}'."
    return "\n".join(f"- {r[0]} ({r[1] or 'thing'})" for r in rows)


def stats() -> str:
    n, r = _fk_stats() if _backend() == "falkordb" else _sq_stats()
    return f"[{_backend()}] {n} entities, {r} relationships"
