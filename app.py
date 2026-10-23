"""Omni-Core — Revaldo's JARVIS. Streamlit UI.

Run:  streamlit run app.py     (needs .env with GEMINI_API_KEY)
"""
import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import brain  # noqa: E402
import graph_memory  # noqa: E402
import memory  # noqa: E402

AGENT_NAME = os.environ.get("AGENT_NAME", "Jarvis")

st.set_page_config(page_title=f"{AGENT_NAME} — Omni-Core", page_icon="🦾")
st.title(f"🦾 {AGENT_NAME}")
st.caption("Omni-Core · your JARVIS · remembers, thinks, does · Gemini routed brain")

with st.sidebar:
    st.subheader("🧠 What I remember about you, sir")
    facts = memory.list_facts()
    if not facts:
        st.write("Nothing yet — run `python seed.py`, or tell me: **remember: …**")
    for f in facts:
        col1, col2 = st.columns([5, 1])
        col1.write(f"• {f}")
        if col2.button("✕", key=f"del_{f}"):
            memory.delete_fact(f)
            st.rerun()
    new_fact = st.text_input("Add a fact", placeholder="e.g. My gym time is 6 AM")
    if st.button("Save fact") and new_fact.strip():
        memory.add_fact(new_fact.strip())
        st.rerun()
    st.divider()
    st.caption("Knowledge graph: " + graph_memory.stats())
    st.caption(f"Last brain: {brain.LAST_ROUTE['model']} — {brain.LAST_ROUTE['note']}")
    if st.button("🗑️ Clear chat history"):
        memory.clear_history()
        st.session_state.pop("ui_messages", None)
        st.rerun()

if "ui_messages" not in st.session_state:
    st.session_state.ui_messages = memory.recent_messages(limit=50)

for msg in st.session_state.ui_messages:
    with st.chat_message("user" if msg["role"] == "user" else "assistant"):
        st.write(msg["text"])

prompt = st.chat_input(f"Talk to {AGENT_NAME}, sir… (tip: 'deep:' prefix = Pro brain)")
if prompt:
    st.session_state.ui_messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.write(prompt)
    with st.chat_message("assistant"):
        try:
            reply = brain.chat(prompt)
        except Exception as e:
            reply = f"⚠️ {brain.format_error(e)}"
        st.write(reply)
        st.caption(f"🧠 {brain.LAST_ROUTE['model']} · {brain.LAST_ROUTE['note']}")
    st.session_state.ui_messages.append({"role": "model", "text": reply})
