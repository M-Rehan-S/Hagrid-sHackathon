from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from flask import Flask

from app import auth as auth_module
from app.api.api_keys import api_keys_bp
from app.api.public import public_bp
from app.auth import register_auth_error_handler
from app.extensions import db
from app.services import api_key_service


def _app():
    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True, RATE_LIMIT_PUBLIC_COUNT=60, RATE_LIMIT_PUBLIC_WINDOW_SECONDS=60)
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(api_keys_bp, url_prefix="/api/v1/api-keys")
    flask_app.register_blueprint(public_bp, url_prefix="/api/v1/public")
    return flask_app


def test_api_key_create_returns_secret_once_and_never_audits_it(monkeypatch):
    actor = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role="admin")
    session = MagicMock()
    def set_created_fields():
        key = session.add.call_args.args[0]
        key.id = str(uuid4())
        key.created_at = datetime.now(timezone.utc)
    session.flush.side_effect = set_created_fields
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(auth_module, "_load_current_user", lambda: actor)
    audit_log = MagicMock()
    monkeypatch.setattr(api_key_service.audit, "log", audit_log)
    client = _app().test_client()

    response = client.post("/api/v1/api-keys", json={"label": "demo integration"})

    assert response.status_code == 201
    data = response.json["data"]
    assert data["api_key"].startswith("lmk_")
    assert data["key_prefix"] == data["api_key"][:8]
    assert data["label"] == "demo integration"
    assert data["created_at"]
    assert "key_hash" not in data
    stored = session.add.call_args.args[0]
    assert stored.key_hash != data["api_key"]
    assert len(stored.key_hash) == 64
    assert audit_log.call_args.kwargs["action"] == "apikey.create"
    assert data["api_key"] not in str(audit_log.call_args.kwargs["payload"])
    session.commit.assert_called_once_with()


def test_non_admin_cannot_manage_api_keys(monkeypatch):
    actor = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role="citizen")
    monkeypatch.setattr(auth_module, "_load_current_user", lambda: actor)
    client = _app().test_client()

    response = client.get(
        "/api/v1/api-keys",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403
    assert response.json["error"]["code"] == "FORBIDDEN_ROLE"


def test_api_key_list_never_returns_full_key_or_hash(monkeypatch):
    actor = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role="admin")
    key = SimpleNamespace(
        id=str(uuid4()), label="external", key_prefix="lmk_abcd", key_hash="f" * 64,
        created_at=datetime.now(timezone.utc), revoked_at=None,
    )
    query = MagicMock()
    query.filter_by.return_value = query
    query.order_by.return_value = query
    query.all.return_value = [key]
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(auth_module, "_load_current_user", lambda: actor)
    client = _app().test_client()

    response = client.get("/api/v1/api-keys", headers={"Authorization": "Bearer valid-token"})

    assert response.status_code == 200
    data = response.json["data"][0]
    assert set(data) == {"id", "label", "key_prefix", "created_at", "revoked_at"}
    assert key.key_hash not in response.get_data(as_text=True)
    assert "api_key" not in response.get_data(as_text=True)
    query.filter_by.assert_called_once_with(tenant_id=actor.tenant_id)


def test_revoked_key_is_rejected_by_public_scam_check(monkeypatch):
    revoked_key = "lmk_revoked-secret"
    query = MagicMock()
    query.filter_by.return_value = query
    query.all.return_value = []  # active-key lookup excludes revoked_at rows
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(db, "session", session)
    client = _app().test_client()

    response = client.post(
        "/api/v1/public/scam-check",
        headers={"X-API-Key": revoked_key},
        json={"text": "message"},
    )

    assert response.status_code == 401
    assert response.json["error"]["code"] == "UNAUTHENTICATED"
    query.filter_by.assert_called_once_with(key_prefix=revoked_key[:8], revoked_at=None)


def test_revoke_is_tenant_scoped_and_audited_without_secret(monkeypatch):
    actor = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role="admin")
    key = SimpleNamespace(
        id=str(uuid4()), tenant_id=actor.tenant_id, label="external", key_prefix="lmk_abcd",
        key_hash="secret-hash", created_at=datetime.now(timezone.utc), revoked_at=None,
    )
    query = MagicMock()
    query.filter_by.return_value.first.return_value = key
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(db, "session", session)
    audit_log = MagicMock()
    monkeypatch.setattr(api_key_service.audit, "log", audit_log)

    result = api_key_service.revoke_api_key(actor, key.id)

    assert result["revoked_at"] is not None
    query.filter_by.assert_called_once_with(id=key.id, tenant_id=actor.tenant_id)
    assert audit_log.call_args.kwargs["action"] == "apikey.revoke"
    assert "secret-hash" not in str(audit_log.call_args.kwargs["payload"])
    session.commit.assert_called_once_with()


def test_revoke_returns_not_found_for_another_tenant(monkeypatch):
    actor = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()))
    query = MagicMock()
    query.filter_by.return_value.first.return_value = None
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(db, "session", session)

    assert api_key_service.revoke_api_key(actor, str(uuid4())) is None
    query.filter_by.assert_called_once()
    assert query.filter_by.call_args.kwargs["tenant_id"] == actor.tenant_id
    session.commit.assert_not_called()
