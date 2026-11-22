"""Tests for POST /api/v1/ai/extract-form (PROPOSAL.md §7.5)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from flask import Flask

from app import auth as auth_module
from app.api.ai import ai_bp
from app.auth import register_auth_error_handler
from app.extensions import db
from conftest import init_test_limiter


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
    init_test_limiter(app)
    app.register_blueprint(ai_bp, url_prefix="/api/v1/ai")
    return app, actor


def _auth_headers():
    return {"Authorization": "Bearer valid-token", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Auth / role guards
# ---------------------------------------------------------------------------

def test_extract_form_unauthenticated():
    app, _ = _make_app()
    resp = app.test_client().post("/api/v1/ai/extract-form", json={"text": "Hello"})
    assert resp.status_code == 401


def test_extract_form_forbidden_role(monkeypatch):
    app, actor = _make_app(role="officer")
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    monkeypatch.setattr(db, "session", MagicMock(**{"get.return_value": actor}))
    resp = app.test_client().post(
        "/api/v1/ai/extract-form",
        json={"text": "My CNIC is 1234567890123"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 403


def test_extract_form_forbidden_admin(monkeypatch):
    app, actor = _make_app(role="admin")
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    monkeypatch.setattr(db, "session", MagicMock(**{"get.return_value": actor}))
    resp = app.test_client().post(
        "/api/v1/ai/extract-form",
        json={"text": "My CNIC is 1234567890123"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_extract_form_missing_text(monkeypatch):
    app, actor = _make_app()
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    monkeypatch.setattr(db, "session", MagicMock(**{"get.return_value": actor}))
    resp = app.test_client().post(
        "/api/v1/ai/extract-form",
        json={},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json["error"]["code"] == "VALIDATION_ERROR"


def test_extract_form_blank_text(monkeypatch):
    app, actor = _make_app()
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    monkeypatch.setattr(db, "session", MagicMock(**{"get.return_value": actor}))
    resp = app.test_client().post(
        "/api/v1/ai/extract-form",
        json={"text": "   "},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("existing_form", ["not-an-object", ["unexpected"], 7])
def test_extract_form_rejects_non_object_existing_form(existing_form, monkeypatch):
    app, actor = _make_app()
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    monkeypatch.setattr(db, "session", MagicMock(**{"get.return_value": actor}))

    resp = app.test_client().post(
        "/api/v1/ai/extract-form",
        json={"text": "Please help with my application", "existing_form": existing_form},
        headers=_auth_headers(),
    )

    assert resp.status_code == 400
    assert resp.json["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Regex fallback extraction (no LLM keys)
# ---------------------------------------------------------------------------

def test_extract_form_regex_cnic(monkeypatch):
    from app.services import audit as audit_svc
    app, actor = _make_app()
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    session = MagicMock()
    session.get.return_value = actor
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(audit_svc.audit, "log", MagicMock())

    text = "My CNIC is 4210101234567 and I live in Karachi East. Phone: 03001234567"
    with patch("app.ai.form_extractor.chat", return_value=None):
        resp = app.test_client().post(
            "/api/v1/ai/extract-form",
            json={"text": text},
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    data = resp.json["data"]
    assert data["form"]["cnic"] == "4210101234567"
    assert data["form"]["district"] == "Karachi East"
    assert data["form"]["phone"] == "03001234567"
    assert isinstance(data["missing_fields"], list)
    assert isinstance(data["confidence"], float)
    assert resp.json["error"] is None


def test_extract_form_regex_widow(monkeypatch):
    from app.services import audit as audit_svc
    app, actor = _make_app()
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    session = MagicMock()
    session.get.return_value = actor
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(audit_svc.audit, "log", MagicMock())

    text = "I am a widow living in Thatta. Monthly income 15000."
    with patch("app.ai.form_extractor.chat", return_value=None):
        resp = app.test_client().post(
            "/api/v1/ai/extract-form",
            json={"text": text},
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    form = resp.json["data"]["form"]
    assert form["is_widow"] is True
    assert form["district"] == "Thatta"
    assert form["monthly_income"] == 15000


# ---------------------------------------------------------------------------
# LLM primary path (mocked)
# ---------------------------------------------------------------------------

def test_extract_form_llm_primary(monkeypatch):
    from app.services import audit as audit_svc
    app, actor = _make_app()
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    session = MagicMock()
    session.get.return_value = actor
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(audit_svc.audit, "log", MagicMock())

    llm_response = (
        '{"full_name": "Fatima Bibi", "father_name": "Mohammad Ali", '
        '"cnic": "4210112345670", "dob": "1985-03-15", "district": "Badin", '
        '"household_size": 5, "monthly_income": 20000, "is_widow": true, '
        '"phone": "03121234567"}'
    )
    with patch("app.ai.form_extractor.chat", return_value=llm_response):
        resp = app.test_client().post(
            "/api/v1/ai/extract-form",
            json={"text": "Fatima Bibi ka CNIC 4210112345670 hai", "lang": "ur"},
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    form = resp.json["data"]["form"]
    assert form["full_name"] == "Fatima Bibi"
    assert form["cnic"] == "4210112345670"
    assert form["district"] == "Badin"
    assert form["is_widow"] is True
    assert resp.json["data"]["missing_fields"] == []


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def test_extract_form_audit_logged(monkeypatch):
    from app.services import audit as audit_svc
    app, actor = _make_app()
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _t: {"sub": actor.id})
    session = MagicMock()
    session.get.return_value = actor
    monkeypatch.setattr(db, "session", session)
    mock_log = MagicMock()
    monkeypatch.setattr(audit_svc.audit, "log", mock_log)

    with patch("app.ai.form_extractor.chat", return_value=None):
        resp = app.test_client().post(
            "/api/v1/ai/extract-form",
            json={"text": "CNIC 4210101234567 Karachi West"},
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    assert mock_log.called
    call_kwargs = mock_log.call_args.kwargs
    assert call_kwargs["action"] == "ai.extract_form"
