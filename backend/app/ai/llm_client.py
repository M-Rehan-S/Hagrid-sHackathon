"""LLM client wrapping Groq (primary) and Gemini (fallback).

Usage::

    from app.ai.llm_client import chat

    response_text = chat(system_prompt, user_prompt)
    # Returns None on timeout / failure / NO_ANSWER sentinel.

Model names live in env vars:
    GROQ_LLM_MODEL      (default: llama-3.3-70b-versatile)
    GEMINI_LLM_MODEL    (default: gemini-1.5-flash)
"""

from __future__ import annotations

import os
import time
from typing import Optional

_GROQ_DEFAULT = "llama-3.3-70b-versatile"
_GEMINI_DEFAULT = "gemini-1.5-flash"
_TIMEOUT = 10  # seconds
_RETRIES = 1


def _call_groq(system_prompt: str, user_prompt: str) -> Optional[str]:
    """Call Groq chat completion; return text or None."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.getenv("GROQ_LLM_MODEL", _GROQ_DEFAULT).strip() or _GROQ_DEFAULT

    try:
        import requests

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 1024,
            "temperature": 0.1,
        }
        resp = requests.post(url, json=body, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _call_gemini(system_prompt: str, user_prompt: str) -> Optional[str]:
    """Call Gemini generateContent; return text or None."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.getenv("GEMINI_LLM_MODEL", _GEMINI_DEFAULT).strip() or _GEMINI_DEFAULT

    try:
        import requests

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        body = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
        }
        resp = requests.post(url, json=body, timeout=_TIMEOUT)
        resp.raise_for_status()
        return (
            resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        )
    except Exception:
        return None


def chat(system_prompt: str, user_prompt: str) -> Optional[str]:
    """Call the LLM with one retry; return text or None on failure.

    Tries Groq first, then Gemini.  Returns None if both fail or time out.
    """
    for _attempt in range(_RETRIES + 1):
        result = _call_groq(system_prompt, user_prompt)
        if result is not None:
            return result
        result = _call_gemini(system_prompt, user_prompt)
        if result is not None:
            return result
        if _attempt < _RETRIES:
            time.sleep(0.5)

    return None
