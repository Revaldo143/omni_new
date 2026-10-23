# Omni-Core (Jarvis) — cloud image.
# python 3.12 slim + headless chromium for the MCP browser tool.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl (Telegram voice-note upload), ca-certificates, tzdata (scheduler runs on Asia/Kolkata).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tzdata && \
    rm -rf /var/lib/apt/lists

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Browser engine for the MCP browser tool. In cloud it runs headless
# via OMNI_BROWSER_HEADLESS=1 (see docker-compose.yml).
RUN python -m playwright install --with-deps chromium

COPY *.py .env.example entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Runtime state (memory DB, .env, browser profile, logs) lives in the
# jarvis_state volume; entrypoint.sh symlinks it into /app.
VOLUME ["/state"]

EXPOSE 8501

ENTRYPOINT ["/app/entrypoint.sh"]

# Default: web UI. The bot service overrides this in docker-compose.yml.
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
