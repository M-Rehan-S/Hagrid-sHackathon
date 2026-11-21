from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from flask import Flask

from app import auth as auth_module
from app.api import sync as sync_api
from app.api.sync import sync_bp
from app.auth import register_auth_error_handler
from app.extensions import db


def _user():
    return SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role="citizen", is_active=True)


def _client(monkeypatch, actor):
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(sync_bp, url_prefix="/api/v1/sync")
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": actor.id})
    session = MagicMock()
    session.get.return_value = actor
    monkeypatch.setattr(db, "session", session)
    return flask_app.test_client()


def test_sync_api_returns_standard_envelope(monkeypatch):
    actor = _user()
    client = _client(monkeypatch, actor)
    batch = [{"client_op_id": str(uuid4()), "type": "patch_form"}]
    sync = MagicMock(return_value=[{"client_op_id": batch[0]["client_op_id"], "status": "applied"}])
    monkeypatch.setattr(sync_api, "sync_batch", sync)

    response = client.post(
        "/api/v1/sync/batch", headers={"Authorization": "Bearer token"}, json={"ops": batch}
    )

    assert response.status_code == 200
    assert response.json["error"] is None
    assert response.json["data"]["results"][0]["status"] == "applied"
    sync.assert_called_once_with(actor, batch)


def test_sync_api_rejects_unknown_top_level_fields(monkeypatch):
    client = _client(monkeypatch, _user())

    response = client.post(
        "/api/v1/sync/batch", headers={"Authorization": "Bearer token"},
        json={"ops": [], "extra": True},
    )

    assert response.status_code == 400
    assert response.json["error"]["code"] == "VALIDATION_ERROR"
