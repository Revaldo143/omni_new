"""Diagnose the Omni-Core setup. Run:  python diagnose.py

Checks: Python version, timezone data (Windows needs the tzdata package),
.env key presence, MCP server connection, tool calls, and one real
Gemini call. Prints the FULL error when something fails — send that
output to whoever is helping you debug.
"""
import asyncio
import os
import sys
import traceback

print(f"Python: {sys.version.split()[0]}  exe: {sys.executable}")

try:
    from zoneinfo import ZoneInfo
    from datetime import datetime

    print("Timezone OK:", datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%H:%M IST"))
except Exception:
    print("Timezone FAILED (install tzdata: pip install tzdata):")
    traceback.print_exc()

from dotenv import load_dotenv

load_dotenv()
key = os.environ.get("GEMINI_API_KEY", "").strip()
print("GEMINI_API_KEY in .env:", "present" if key and key != "your-key-here" else "MISSING")
print("Model:", os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"))


async def check_mcp():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = StdioServerParameters(
        command=sys.executable,
        args=["tools_server.py"],
        env={k: v for k, v in os.environ.items() if isinstance(v, str)},
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = await s.list_tools()
            print(f"MCP OK: {len(tools.tools)} tools:", [t.name for t in tools.tools])
            r = await s.call_tool("get_datetime", {})
            print("get_datetime ->", "".join(c.text for c in r.content if getattr(c, "type", "") == "text"))
            r = await s.call_tool("calculate", {"expression": "6*7"})
            print("calculate ->", "".join(c.text for c in r.content if getattr(c, "type", "") == "text"))


try:
    asyncio.run(check_mcp())
except BaseException:
    print("MCP FAILED — full error:")
    traceback.print_exc()

if key and key != "your-key-here":
    try:
        from google import genai

        c = genai.Client(api_key=key)
        resp = c.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"),
            contents="Say OK in one word.",
        )
        print("Gemini call OK:", (resp.text or "").strip()[:50])
    except Exception:
        print("Gemini call FAILED — full error:")
        traceback.print_exc()
print("Done.")
