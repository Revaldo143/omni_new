"""LLM provider abstraction — Jarvis 2.0.

The brain talks to providers through one neutral interface, so the model
behind Jarvis can be switched in .env without touching any other code:

    LLM_PROVIDER=gemini      # Google AI Studio (default)
    LLM_PROVIDER=openai      # any OpenAI-compatible endpoint:
                             # OpenAI, Groq, OpenRouter, DeepSeek, Ollama...

Env vars:
    GEMINI_API_KEY, OMNI_FLASH_MODEL, OMNI_PRO_MODEL
    OPENAI_API_KEY, OPENAI_BASE_URL (default https://api.openai.com/v1),
    OPENAI_MODEL, OPENAI_TIMEOUT_S (default 120)

One "generate" = one model turn. The agentic tool loop lives in brain.py.
Quota/cost accounting also lives in brain.py (it counts generate calls).
"""

from __future__ import annotations

import http.client
import json
import os
import urllib.request
from dataclasses import dataclass, field


# ---------------------------------------------------------------- proxy fix
# This VM reaches the internet through an egress proxy that blackholes
# CONNECT tunnels without a curl-style User-Agent. Harmless everywhere else.

_PROXY_PATCHED = False


def _maybe_patch_proxy() -> None:
    global _PROXY_PATCHED
    if _PROXY_PATCHED or not os.environ.get("HTTPS_PROXY"):
        return
    _orig = http.client.HTTPConnection.set_tunnel

    def _patched(self, host, port=None, headers=None):  # type: ignore[no-untyped-def]
        headers = dict(headers or {})
        headers.setdefault("Proxy-Connection", "Keep-Alive")
        headers.setdefault("User-Agent", "curl/8.5.0")
        _orig(self, host, port, headers)

    http.client.HTTPConnection.set_tunnel = _patched  # type: ignore[method-assign]
    _PROXY_PATCHED = True


# ------------------------------------------------------------------ types

@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ProviderResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


# Neutral message format used by brain.py.
# {"role": "user"|"model"|"tool", "text": str, "tool_call_id": str|None,
#  "tool_name": str|None}
Message = dict


class LLMProvider:
    name = "base"

    def generate(
        self,
        system: str,
        history: list[Message],
        tools: list[dict] | None = None,
    ) -> ProviderResponse:
        raise NotImplementedError


# ------------------------------------------------------------------ gemini

class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        _maybe_patch_proxy()
        from google import genai

        # Bind the client to this instance: a temporary Client gets GC'd and
        # its __del__ closes the shared httpx client (google-genai #1763).
        self._client = genai.Client(api_key=api_key)
        self._types = __import__("google.genai.types", fromlist=["types"])
        self.model = model

    def _to_contents(self, history: list[Message]) -> list:
        t = self._types
        contents = []
        for m in history:
            role, text = m["role"], m.get("text", "")
            if role == "tool":
                parts = [
                    t.Part.from_function_response(
                        name=m.get("tool_name", "tool"),
                        response={"result": text},
                    )
                ]
                contents.append(t.Content(role="user", parts=parts))
            elif role == "model" and m.get("tool_calls"):
                parts = []
                if text:
                    parts.append(t.Part.from_text(text=text))
                for tc in m["tool_calls"]:
                    parts.append(t.Part.from_function_call(
                        name=tc["name"], args=tc.get("args") or {}))
                contents.append(t.Content(role="model", parts=parts))
            else:
                contents.append(
                    t.Content(
                        role="user" if role == "user" else "model",
                        parts=[t.Part.from_text(text=text)],
                    )
                )
        return contents

    def generate(self, system, history, tools=None):
        t = self._types
        tool_objs = None
        if tools:
            tool_objs = [
                t.Tool(
                    function_declarations=[
                        t.FunctionDeclaration(
                            name=td["name"],
                            description=td.get("description", ""),
                            parameters=td.get("parameters"),
                        )
                        for td in tools
                    ]
                )
            ]
        resp = self._client.models.generate_content(
            model=self.model,
            contents=self._to_contents(history),
            config=t.GenerateContentConfig(
                system_instruction=system,
                tools=tool_objs,
            ),
        )
        text, calls = None, []
        try:
            cand = (resp.candidates or [None])[0]
            parts = (cand.content.parts or []) if cand and cand.content else []
        except Exception:
            parts = []
        texts = [p.text for p in parts if getattr(p, "text", None)]
        if texts:
            text = "".join(texts).strip() or None
        for i, p in enumerate(parts):
            fc = getattr(p, "function_call", None)
            if fc:
                args = dict(fc.args or {})
                calls.append(ToolCall(id=f"gem-{i}", name=fc.name, args=args))
        if text is None and not calls:
            # SDK shortcut may hold the text even when parts look odd.
            try:
                text = (resp.text or "").strip() or None
            except Exception:
                pass
        return ProviderResponse(text=text, tool_calls=calls)


# ------------------------------------------------------- openai-compatible

class OpenAICompatProvider(LLMProvider):
    """Any endpoint speaking POST {base_url}/chat/completions."""

    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str, timeout_s: int = 120):
        _maybe_patch_proxy()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "jarvis-2.0",
        }

    def generate(self, system, history, tools=None):
        messages: list[dict] = [{"role": "system", "content": system}]
        for m in history:
            role = m["role"]
            if role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.get("tool_call_id", ""),
                        "content": m.get("text", ""),
                    }
                )
            elif role == "model":
                amsg: dict = {"role": "assistant",
                             "content": m.get("text", "")}
                if m.get("tool_calls"):
                    import json as _json
                    amsg["tool_calls"] = [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"],
                                      "arguments": _json.dumps(
                                          tc.get("args") or {})}}
                        for tc in m["tool_calls"]
                    ]
                messages.append(amsg)
            else:
                messages.append({"role": "user", "content": m.get("text", "")})
        body: dict = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": td["name"],
                        "description": td.get("description", ""),
                        "parameters": td.get("parameters") or {"type": "object", "properties": {}},
                    },
                }
                for td in tools
            ]
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
            payload = json.loads(r.read().decode())
        choice = (payload.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = (msg.get("content") or "").strip() or None
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            calls.append(
                ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), args=args)
            )
        return ProviderResponse(text=text, tool_calls=calls)


# ---------------------------------------------------------------- factory

def get_provider(model: str) -> LLMProvider:
    """Build the configured provider for one model name."""
    which = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
    if which == "openai":
        return OpenAICompatProvider(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            model=model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            timeout_s=int(os.environ.get("OPENAI_TIMEOUT_S", "120")),
        )
    return GeminiProvider(
        api_key=os.environ.get("GEMINI_API_KEY", ""),
        model=model,
    )
