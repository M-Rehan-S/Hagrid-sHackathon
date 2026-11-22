"""Tests for POST /api/v1/ai/transcribe (PROPOSAL.md §7.5)."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from flask import Flask

from app import auth as auth_module
from app.api.ai import ai_bp
from app.auth import register_auth_error_handler
from app.extensions import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(role: str = "citizen") -> tuple[Flask, SimpleNamespace]:
    actor = SimpleNamespace(
        id=str(uuid4()),
        tenant_id=str(uuid4()),
        role=role,
        is_active=True,
    )
    app = Flask(__name__)
    app.config.update(TESTING=True)
    register_auth_error_handler(app)
    app.register_blueprint(ai_bp, url_prefix="/api/v1/ai")
    return app, actor


def _make_audio(size: int = 1024) -> bytes:
    """Return a minimal valid MP3-ish bytes payload for testing."""
    return b"\x00" * size


# ---------------------------------------------------------------------------
# Auth / role guards
# ---------------------------------------------------------------------------

def test_transcribe_unauthenticated():
    app, _ = _make_app()
    data = {"audio": (io.BytesIO(_make_audio()), "test.mp3")}
    resp = app.test_client().post(
        "/api/v1/ai/transcribe",
        data=data,
        content_type="multipart/form-data",
    )
    assert resp.status_code == 401


def test_transcribe_forbidden_role(monkeypatch):
    app, actor = _make_app(role="officer")
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    monkeypatch.setattr(db, "session", MagicMock(**{"get.return_value": actor}))
    data = {"audio": (io.BytesIO(_make_audio()), "test.mp3")}
    resp = app.test_client().post(
        "/api/v1/ai/transcribe",
        data=data,
        content_type="multipart/form-data",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

def test_transcribe_no_audio_file(monkeypatch):
    app, actor = _make_app()
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    monkeypatch.setattr(db, "session", MagicMock(**{"get.return_value": actor}))
    resp = app.test_client().post(
        "/api/v1/ai/transcribe",
        data={"lang": "ur"},
        content_type="multipart/form-data",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert resp.status_code == 400
    assert resp.json["error"]["code"] == "VALIDATION_ERROR"


def test_transcribe_oversized_file(monkeypatch):
    from app.ai.transcriber import MAX_AUDIO_BYTES
    app, actor = _make_app()
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    monkeypatch.setattr(db, "session", MagicMock(**{"get.return_value": actor}))
    big = _make_audio(MAX_AUDIO_BYTES + 1)
    data = {"audio": (io.BytesIO(big), "big.mp3")}
    resp = app.test_client().post(
        "/api/v1/ai/transcribe",
        data=data,
        content_type="multipart/form-data",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert resp.status_code == 400
    assert resp.json["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# No API keys → 503 AI_UNAVAILABLE
# ---------------------------------------------------------------------------

def test_transcribe_no_api_keys(monkeypatch):
    app, actor = _make_app()
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    monkeypatch.setattr(db, "session", MagicMock(**{"get.return_value": actor}))
    # Ensure both env vars are empty
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    data = {"audio": (io.BytesIO(_make_audio()), "test.mp3"), "lang": "ur"}
    resp = app.test_client().post(
        "/api/v1/ai/transcribe",
        data=data,
        content_type="multipart/form-data",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert resp.status_code == 503
    assert resp.json["error"]["code"] == "AI_UNAVAILABLE"
    assert resp.json["data"] is None


# ---------------------------------------------------------------------------
# Mocked Groq success → 200
# ---------------------------------------------------------------------------

def test_transcribe_groq_success(monkeypatch):
    from app.services import audit as audit_svc
    app, actor = _make_app()
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    session = MagicMock()
    session.get.return_value = actor
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setattr(audit_svc.audit, "log", MagicMock())

    mock_result = {"text": "میرا نام فاطمہ ہے", "confidence": 0.90}
    with patch("app.ai.transcriber._transcribe_groq", return_value=mock_result):
        data = {"audio": (io.BytesIO(_make_audio()), "speech.mp3"), "lang": "ur"}
        resp = app.test_client().post(
            "/api/v1/ai/transcribe",
            data=data,
            content_type="multipart/form-data",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert resp.status_code == 200
    assert resp.json["error"] is None
    assert resp.json["data"]["text"] == "میرا نام فاطمہ ہے"
    assert resp.json["data"]["confidence"] == 0.90


def test_transcribe_groq_fails_gemini_fallback(monkeypatch):
    from app.services import audit as audit_svc
    app, actor = _make_app()
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    session = MagicMock()
    session.get.return_value = actor
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setattr(audit_svc.audit, "log", MagicMock())

    gemini_result = {"text": "Hello from Gemini", "confidence": 0.75}
    with patch("app.ai.transcriber._transcribe_groq", return_value=None), \
         patch("app.ai.transcriber._transcribe_gemini", return_value=gemini_result):
        data = {"audio": (io.BytesIO(_make_audio()), "speech.wav"), "lang": "en"}
        resp = app.test_client().post(
            "/api/v1/ai/transcribe",
            data=data,
            content_type="multipart/form-data",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert resp.status_code == 200
    assert resp.json["data"]["text"] == "Hello from Gemini"


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def test_transcribe_audit_logged(monkeypatch):
    from app.services import audit as audit_svc
    app, actor = _make_app()
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    session = MagicMock()
    session.get.return_value = actor
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    mock_log = MagicMock()
    monkeypatch.setattr(audit_svc.audit, "log", mock_log)

    mock_result = {"text": "Test transcript", "confidence": 0.90}
    with patch("app.ai.transcriber._transcribe_groq", return_value=mock_result):
        data = {"audio": (io.BytesIO(_make_audio()), "audio.mp3"), "lang": "ur"}
        resp = app.test_client().post(
            "/api/v1/ai/transcribe",
            data=data,
            content_type="multipart/form-data",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert resp.status_code == 200
    assert mock_log.called
    call_kwargs = mock_log.call_args.kwargs
    assert call_kwargs["action"] == "ai.transcribe"
    proposal = Path(__file__).resolve().parents[2] / "PROPOSAL.md"
    assert "`ai.transcribe`" in proposal.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# helper role is also allowed
# ---------------------------------------------------------------------------

def test_transcribe_helper_allowed(monkeypatch):
    app, actor = _make_app(role="helper")
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    session = MagicMock()
    session.get.return_value = actor
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    data = {"audio": (io.BytesIO(_make_audio()), "test.mp3")}
    resp = app.test_client().post(
        "/api/v1/ai/transcribe",
        data=data,
        content_type="multipart/form-data",
        headers={"Authorization": "Bearer valid-token"},
    )
    # 503 not 401/403 — the route was reached
    assert resp.status_code == 503
