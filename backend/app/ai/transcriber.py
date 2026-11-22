"""Audio transcription module for POST /api/v1/ai/transcribe (PROPOSAL.md §7.5).

Provider chain: Groq Whisper (primary) → Gemini (fallback) → 503 AI_UNAVAILABLE.

Returns::

    {"text": str, "confidence": float}

Raises ``TranscribeError`` on validation errors (400) or service unavailability (503).
"""

from __future__ import annotations

import base64
import io
import os
from typing import Optional

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB

_GROQ_WHISPER_DEFAULT = "whisper-large-v3"
_TIMEOUT = 30  # seconds – audio upload is slow


class TranscribeError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Groq Whisper
# ---------------------------------------------------------------------------
def _transcribe_groq(
    audio_bytes: bytes,
    filename: str,
    lang: str,
    api_key: str,
) -> Optional[dict]:
    """Call Groq Whisper API; return dict or None on error."""
    model = os.getenv("GROQ_WHISPER_MODEL", _GROQ_WHISPER_DEFAULT).strip() or _GROQ_WHISPER_DEFAULT

    try:
        import requests

        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {api_key}"}

        # Determine MIME type from filename
        lower = filename.lower()
        if lower.endswith(".mp3"):
            mime = "audio/mpeg"
        elif lower.endswith(".wav"):
            mime = "audio/wav"
        elif lower.endswith(".ogg") or lower.endswith(".oga"):
            mime = "audio/ogg"
        elif lower.endswith(".flac"):
            mime = "audio/flac"
        elif lower.endswith(".webm"):
            mime = "audio/webm"
        elif lower.endswith(".m4a"):
            mime = "audio/mp4"
        else:
            mime = "audio/mpeg"

        files = {"file": (filename, io.BytesIO(audio_bytes), mime)}
        data = {"model": model, "language": lang, "response_format": "json"}

        resp = requests.post(url, headers=headers, files=files, data=data, timeout=_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        text = body.get("text", "").strip()
        if not text:
            return None
        return {"text": text, "confidence": 0.90}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Gemini audio transcription (inline base64)
# ---------------------------------------------------------------------------
def _transcribe_gemini(
    audio_bytes: bytes,
    filename: str,
    lang: str,
    api_key: str,
) -> Optional[dict]:
    """Call Gemini generateContent with audio as inline base64; return dict or None."""
    try:
        import requests

        model = os.getenv("GEMINI_LLM_MODEL", "gemini-1.5-flash").strip() or "gemini-1.5-flash"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        lower = filename.lower()
        if lower.endswith(".mp3"):
            mime = "audio/mpeg"
        elif lower.endswith(".wav"):
            mime = "audio/wav"
        elif lower.endswith(".ogg") or lower.endswith(".oga"):
            mime = "audio/ogg"
        elif lower.endswith(".flac"):
            mime = "audio/flac"
        elif lower.endswith(".webm"):
            mime = "audio/webm"
        elif lower.endswith(".m4a"):
            mime = "audio/mp4"
        else:
            mime = "audio/mpeg"

        b64 = base64.b64encode(audio_bytes).decode("utf-8")
        body = {
            "contents": [{
                "parts": [
                    {"inline_data": {"mime_type": mime, "data": b64}},
                    {"text": f"Transcribe this audio to text. Language hint: {lang}. Return only the transcribed text."},
                ]
            }],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 1024},
        }
        resp = requests.post(url, json=body, timeout=_TIMEOUT)
        resp.raise_for_status()
        candidates = resp.json().get("candidates", [])
        if candidates:
            text = candidates[0]["content"]["parts"][0]["text"].strip()
            if text:
                return {"text": text, "confidence": 0.75}
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def transcribe_audio(audio_bytes: bytes, filename: str, lang: str = "ur") -> dict:
    """Transcribe audio bytes to text.

    Args:
        audio_bytes: Raw audio file contents.
        filename: Original filename (used for MIME sniffing).
        lang: BCP-47 language code hint (default "ur").

    Returns:
        {"text": str, "confidence": float}

    Raises:
        TranscribeError: 400 for validation errors, 503 if no provider succeeds.
    """
    if not audio_bytes:
        raise TranscribeError("VALIDATION_ERROR", "No audio data provided.", 400)
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise TranscribeError(
            "VALIDATION_ERROR",
            f"Audio file too large. Maximum allowed size is 25 MB.",
            400,
        )

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

    if groq_key:
        result = _transcribe_groq(audio_bytes, filename, lang, groq_key)
        if result:
            return result

    if gemini_key:
        result = _transcribe_gemini(audio_bytes, filename, lang, gemini_key)
        if result:
            return result

    raise TranscribeError(
        "AI_UNAVAILABLE",
        "Audio transcription is temporarily unavailable. Please try again later.",
        503,
    )
