# Jarvis 2.0 — Agentic Edition

Fresh rebuild of the personal AI agent. Agentic work: freelancing, browser
use, personal assistance, online jobs.

## What's new vs 1.0

- **Provider abstraction** (`providers.py`) — `LLM_PROVIDER=gemini` (default)
  or `openai` (any OpenAI-compatible endpoint: OpenAI, Groq, OpenRouter,
  DeepSeek, Ollama). Switch in `.env`, no code changes.
- **Quota-aware brain** (`quota.py`) — every model call counted against a
  daily budget (`OMNI_DAILY_BUDGET`, default 18). Budget gone = honest
  Tanglish message, never silence, never a mid-task crash.
- **Tool-loop budgets** — max 8 rounds, stops before the budget hits zero,
  final-answer nudge so you never get "(no reply — try again)".
- **Economical skills** — `get_price` (gold/forex/crypto in ONE call),
  `deep_research`, `draft_doc`, `find_gigs`, `find_jobs`. Rule: data via
  API, browser only for *interaction*.
- **Approval gates** — tools that change the outside world (submitting web
  forms) ask you on Telegram with Yes/No buttons first.
- **/usage** command on Telegram — see today's model-call count.

## Kept from 1.0

SQLite memory + graph memory, Telegram front door (owner-locked), 08:00 IST
morning brief + reminders, voice notes (hear + speak), Playwright browser,
code sandbox, Streamlit UI.

## Run locally

```bash
cp .env.example .env   # fill GEMINI_API_KEY + TELEGRAM_BOT_TOKEN
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python seed.py          # first time only
python telegram_bot.py  # or: streamlit run app.py
```

## Deploy (Docker, e.g. AWS EC2)

```bash
docker compose up -d --build
docker compose exec bot python seed.py   # first time only
```

## Dev loop

```bash
git pull && docker compose up -d --build   # on the server after each push
```

`.env` and the memory DB live outside the image — rebuilds never wipe them.
