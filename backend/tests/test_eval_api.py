from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from flask import Flask

from app import auth as auth_module
from app.api import eval as eval_api
from app.api.eval import eval_bp
from app.auth import register_auth_error_handler
from app.extensions import db


def _client(monkeypatch, role):
    actor = SimpleNamespace(
        id=str(uuid4()), tenant_id=str(uuid4()), role=role, is_active=True
    )
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(eval_bp, url_prefix="/api/v1/eval")
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": actor.id})
    session = MagicMock()
    session.get.return_value = actor
    monkeypatch.setattr(db, "session", session)
    return flask_app.test_client(), actor


def test_eval_summary_route_returns_data_for_officer(monkeypatch):
    client, actor = _client(monkeypatch, "officer")
    summary = {"evaluation_runs": [], "live": {"auto_approved_count": 0}}
    service = MagicMock(return_value=summary)
    monkeypatch.setattr(eval_api, "evaluation_summary", service)

    response = client.get("/api/v1/eval/summary", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    assert response.json == {"data": summary, "error": None}
    service.assert_called_once_with(actor)


def test_eval_summary_route_denies_citizens(monkeypatch):
    client, _actor = _client(monkeypatch, "citizen")
    service = MagicMock()
    monkeypatch.setattr(eval_api, "evaluation_summary", service)

    response = client.get("/api/v1/eval/summary", headers={"Authorization": "Bearer token"})

    assert response.status_code == 403
    assert response.json["error"]["code"] == "FORBIDDEN_ROLE"
    service.assert_not_called()
