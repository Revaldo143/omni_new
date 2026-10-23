"""Omni-Core Layer 3 — code execution sandbox.

Primary: E2B cloud microVM (Firecracker) — needs E2B_API_KEY in .env
         (free tier: https://e2b.dev — sign up, API key in dashboard).
Fallback: local subprocess with a timeout, in a temp dir, with a minimal
         environment (no API keys passed). NOT isolated — for convenience
         only. The result string always says which engine ran.
"""
import os
import subprocess
import sys
import tempfile

TIMEOUT_S = 20
MAX_OUT = 4000


def _run_e2b(code: str) -> str:
    from e2b_code_interpreter import Sandbox

    with Sandbox.create(timeout=60) as sbx:
        ex = sbx.run_code(code)
    if ex.error:
        return f"[E2B sandbox] Error: {ex.error.name}: {ex.error.value}"
    out = "".join(ex.logs.stdout)
    err = "".join(ex.logs.stderr)
    text = (ex.text or out).strip()
    if err.strip():
        text += f"\n[stderr] {err.strip()}"
    return f"[E2B sandbox] {text or '(no output)'}"[:MAX_OUT]


def _run_local(code: str) -> str:
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "en_US.UTF-8",
        "PYTHONIOENCODING": "utf-8",
    }
    if os.name == "nt":  # Windows needs these for python to start
        for k in ("SystemRoot", "TEMP", "USERPROFILE"):
            if k in os.environ:
                clean_env[k] = os.environ[k]
    with tempfile.TemporaryDirectory() as tmp:
        try:
            r = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=TIMEOUT_S,
                cwd=tmp, env=clean_env,
            )
        except subprocess.TimeoutExpired:
            return f"[local fallback — not isolated] Timed out after {TIMEOUT_S}s."
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    text = out or "(no output)"
    if r.returncode != 0 and err:
        text += f"\n[stderr] {err.splitlines()[-1]}"
    return f"[local fallback — not isolated] {text}"[:MAX_OUT]


def run_python(code: str) -> str:
    """Execute Python code and return its printed output / result."""
    if os.environ.get("E2B_API_KEY", "").strip():
        try:
            return _run_e2b(code)
        except Exception as e:
            return f"[E2B sandbox] Failed ({e}); local fallback NOT used automatically."
    return _run_local(code)
