"""Omni-Core Phase 5 — voice: hear (STT) and speak (TTS) via Gemini.

- transcribe(): Gemini Flash reads the audio (Tanglish/Tamil/English).
- speak(): Gemini TTS model returns audio; WAV passes through, raw
  L16 PCM is wrapped into a WAV container with the stdlib wave module.
Both verified live on the owner's key (round-trip test, 2026-10-20).
"""
import io
import os
import wave

from google import genai
from google.genai import types

FLASH_MODEL = os.environ.get("OMNI_FLASH_MODEL", "gemini-3.5-flash")
TTS_MODEL = os.environ.get("OMNI_TTS_MODEL", "gemini-3.8-flash-tts")
TTS_VOICE = os.environ.get("OMNI_TTS_VOICE", "Kore")
MAX_SPEAK_CHARS = 800


def _client() -> genai.Client:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key or key == "your-key-here":
        raise RuntimeError("GEMINI_API_KEY is not set in .env.")
    return genai.Client(api_key=key)


def transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    client = _client()
    resp = client.models.generate_content(
        model=FLASH_MODEL,
        contents=[
            "Transcribe exactly what is said in this audio, word for word. "
            "The speaker may mix Tamil and English (Tanglish). "
            "Reply with only the transcript.",
            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
        ],
    )
    return (resp.text or "").strip()


def wav_wrap(pcm: bytes, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def speak(text: str) -> bytes:
    """Return WAV bytes of the (trimmed) text spoken aloud."""
    text = (text or "").strip()[:MAX_SPEAK_CHARS]
    if not text:
        return b""
    client = _client()
    resp = client.models.generate_content(
        model=TTS_MODEL,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=TTS_VOICE
                    )
                )
            ),
        ),
    )
    part = resp.candidates[0].content.parts[0]
    data = part.inline_data.data
    mime = (part.inline_data.mime_type or "").lower()
    if "wav" in mime:
        return data
    rate = 24000
    if "rate=" in mime:
        try:
            rate = int(mime.split("rate=")[1].split(";")[0])
        except ValueError:
            pass
    return wav_wrap(data, rate)
