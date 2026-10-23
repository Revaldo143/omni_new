"""Seed Omni-Core's memory with what bro already knows about Revaldo.

Run once:  python seed.py   (safe to re-run — facts dedupe, graph merges)
Only verified facts from his real history. No guesses: if it is not in
bro's long-term memory of him, it is not seeded here.
"""
import graph_memory
import memory

FACTS = [
    "His name is Revaldo; call him sir.",
    "He writes in Tanglish (Tamil-English mix) often — reply in Tanglish when he does.",
    "He prefers brief, direct, numbers-first answers.",
    "Judge-facing artifacts (demo videos, Devpost text, READMEs) must be English-only — his strict QC rule.",
    "He gives explicit approval before irreversible actions: pushes, publishes, spends.",
    "Handoff (Amazon Developer Hackathon entry): Devpost submit + making the demo video public are still pending. Deadline Oct 24, 2026, 12:30am IST.",
    "Look Roulette (YouCam hackathon entry): Devpost draft is saved; the demo video stays unlisted until Nov 1, 2026. Deadline Nov 2, 2026.",
    "TimeMachine (Graph Hacks 2026 entry) is submitted and closed.",
    "Project Omni-Core is his JARVIS build — this agent itself, layer by layer.",
    "For crypto, he wants exact verified contract addresses, never just coin names — copycat contracts share names.",
    "His meme-coin trading bot is on standby by his order ('do not trade yet'); do not suggest trades.",
]

ENTITIES = [
    ("Revaldo", "person", "The boss. Builder, solo hacker."),
    ("Handoff", "project", "Amazon Developer Hackathon entry — the gatekeeper shift agent. Deadline Oct 24, 2026."),
    ("Look Roulette", "project", "YouCam hackathon entry — slot-machine makeup discovery. Deadline Nov 2, 2026."),
    ("TimeMachine", "project", "Graph Hacks 2026 entry — valid-time memory for agents. Submitted."),
    ("Omni-Core", "project", "This agent system. JARVIS-class personal assistant, in build."),
    ("bro", "agent", "Revaldo's Muse assistant — the inspiration and builder of Omni-Core v1."),
]

LINKS = [
    ("Revaldo", "BUILT", "Handoff"),
    ("Revaldo", "BUILT", "Look Roulette"),
    ("Revaldo", "BUILT", "TimeMachine"),
    ("Revaldo", "BUILDING", "Omni-Core"),
    ("Omni-Core", "INSPIRED_BY", "bro"),
]


def main():
    for f in FACTS:
        memory.add_fact(f)
    for name, etype, note in ENTITIES:
        graph_memory.add_entity(name, etype, note)
    for src, rel, dst in LINKS:
        graph_memory.add_relation(src, rel, dst)
    print(f"Seeded {len(FACTS)} facts.")
    print(graph_memory.stats())
    print(graph_memory.about("Revaldo"))


if __name__ == "__main__":
    main()
