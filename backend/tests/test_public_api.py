from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from flask import Flask

from app.api import public as public_api_module
from app.api.public import health_bp, public_bp
from app.auth import register_auth_error_handler
from app.extensions import db
from app.services import public_api


def _client(monkeypatch, *, limit=60):
    flask_app = Flask(__name__)
    flask_app.config.update(
        TESTING=True,
        RATE_LIMIT_PUBLIC_COUNT=limit,
        RATE_LIMIT_PUBLIC_WINDOW_SECONDS=60,
    )
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(public_bp, url_prefix="/api/v1/public")
    flask_app.register_blueprint(health_bp)
    key = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()))
    monkeypatch.setattr(public_api, "authenticate_api_key", lambda _raw: key)
    return flask_app.test_client(), key


def test_public_scam_check_route_validates_and_uses_api_key(monkeypatch):
    client, key = _client(monkeypatch)
    result = {
        "label": "scam", "confidence": 0.91, "category": "fake_relief",
        "reasons": ["Requests a PIN"], "advice_en": "Do not share your PIN.",
        "advice_ur": "اپنا پن شیئر نہ کریں۔",
    }
    checker = MagicMock(return_value=result)
    monkeypatch.setattr(public_api_module, "public_scam_check", checker)

    response = client.post(
        "/api/v1/public/scam-check", headers={"X-API-Key": "valid-key"},
        json={"text": "Please share your bank PIN"},
    )

    assert response.status_code == 200
    assert response.json == {"data": result, "error": None}
    checker.assert_called_once_with(key, "Please share your bank PIN")


def test_public_scam_check_returns_validation_error_for_blank_text(monkeypatch):
    client, _key = _client(monkeypatch)
    response = client.post(
        "/api/v1/public/scam-check", headers={"X-API-Key": "valid-key"}, json={"text": " "}
    )
    assert response.status_code == 400
    assert response.json["error"]["code"] == "VALIDATION_ERROR"


def test_public_case_status_returns_only_status_and_timestamp(monkeypatch):
    client, key = _client(monkeypatch)
    case_id = str(uuid4())
    status = MagicMock(return_value={"status": "in_review", "updated_at": "2026-01-01T00:00:00Z"})
    monkeypatch.setattr(public_api_module, "public_case_status", status)

    response = client.get(
        f"/api/v1/public/cases/{case_id}/status", headers={"X-API-Key": "valid-key"}
    )

    assert response.status_code == 200
    assert set(response.json["data"]) == {"status", "updated_at"}
    status.assert_called_once_with(key, case_id)


def test_public_routes_enforce_rate_limit_per_key(monkeypatch):
    client, key = _client(monkeypatch, limit=1)
    monkeypatch.setattr(
        public_api_module, "public_case_status",
        lambda *_: {"status": "draft", "updated_at": None},
    )
    with public_api._rate_lock:
        public_api._request_times.pop(key.id, None)
    path = f"/api/v1/public/cases/{uuid4()}/status"

    first = client.get(path, headers={"X-API-Key": "valid-key"})
    second = client.get(path, headers={"X-API-Key": "valid-key"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json["error"]["code"] == "RATE_LIMITED"


def test_health_route_reports_database_status(monkeypatch):
    client, _key = _client(monkeypatch)
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = 1
    monkeypatch.setattr(db, "session", session)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok", "db": "ok"}
