from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from flask import Flask

from app import auth as auth_module
from app.api import audit as audit_api
from app.api.audit import audit_bp
from app.auth import register_auth_error_handler
from app.extensions import db
from app.models.audit_log import AuditLog
from app.services import audit as audit_service


@pytest.fixture
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(audit_bp, url_prefix="/api/v1/audit-logs")
    return flask_app


def _user(role: str):
    return SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role=role, is_active=True)


def _log_row(user, *, actor_id=None):
    return SimpleNamespace(
        id=12,
        ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        tenant_id=user.tenant_id,
        actor_type="user",
        actor_id=actor_id or user.id,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        payload={"source": "test"},
        prev_hash="0" * 64,
        hash="1" * 64,
    )


def _authorized(monkeypatch, user):
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": user.id})
    session = MagicMock()
    session.get.return_value = user
    monkeypatch.setattr(db, "session", session)
    return session


def test_auditor_can_verify_and_receives_envelope(app, monkeypatch):
    user = _user("auditor")
    _authorized(monkeypatch, user)
    verify = MagicMock(return_value={"valid": True})
    monkeypatch.setattr(audit_api, "verify_audit_chain", verify)

    response = app.test_client().get(
        "/api/v1/audit-logs/verify",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.json == {"data": {"valid": True}, "error": None}
    verify.assert_called_once_with()


def test_citizen_cannot_view_full_audit_logs(app, monkeypatch):
    _authorized(monkeypatch, _user("citizen"))

    response = app.test_client().get(
        "/api/v1/audit-logs",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403
    assert response.json["error"]["code"] == "FORBIDDEN_ROLE"


def test_citizen_mine_is_scoped_to_own_actor_and_tenant(app, monkeypatch):
    user = _user("citizen")
    session = _authorized(monkeypatch, user)
    row = _log_row(user)
    query = MagicMock()
    query.filter_by.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.offset.return_value = query
    query.limit.return_value = query
    query.count.return_value = 1
    query.all.return_value = [row]
    session.query.return_value = query

    response = app.test_client().get(
        "/api/v1/audit-logs/mine",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.json["data"]["items"][0]["actor_id"] == user.id
    assert response.json["data"]["total"] == 1
    query.filter_by.assert_called_once_with(tenant_id=user.tenant_id)
    assert any(
        call.args[0].compare(AuditLog.actor_id == user.id)
        for call in query.filter.call_args_list
    )


@pytest.mark.parametrize("query_string", ["?page=0", "?page_size=101", "?from=2026-01-01T00:00:00"])
def test_audit_pagination_and_timestamps_are_validated(app, monkeypatch, query_string):
    _authorized(monkeypatch, _user("citizen"))

    response = app.test_client().get(
        f"/api/v1/audit-logs/mine{query_string}",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 400
    assert response.json["error"]["code"] == "VALIDATION_ERROR"


def test_verify_audit_chain_accepts_valid_chain(monkeypatch):
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = SimpleNamespace(
        id=1, ts=timestamp, tenant_id=None, actor_type="system", actor_id=None,
        action="seed", entity_type=None, entity_id=None, payload={},
        prev_hash="0" * 64,
    )
    first.hash = audit_service.calculate_audit_hash(
        first.prev_hash, ts=first.ts, tenant_id=first.tenant_id,
        actor_type=first.actor_type, actor_id=first.actor_id, action=first.action,
        entity_type=first.entity_type, entity_id=first.entity_id, payload=first.payload,
    )
    second = SimpleNamespace(
        id=2, ts=timestamp, tenant_id="tenant-1", actor_type="user", actor_id="user-1",
        action="auth.login", entity_type="user", entity_id="user-1", payload={"ok": True},
        prev_hash=first.hash,
    )
    second.hash = audit_service.calculate_audit_hash(
        second.prev_hash, ts=second.ts, tenant_id=second.tenant_id,
        actor_type=second.actor_type, actor_id=second.actor_id, action=second.action,
        entity_type=second.entity_type, entity_id=second.entity_id, payload=second.payload,
    )
    session = MagicMock()
    session.scalars.return_value.all.return_value = [first, second]
    monkeypatch.setattr(db, "session", session)

    assert audit_service.verify_audit_chain() == {"valid": True}


def test_verify_audit_chain_reports_first_tampered_entry(monkeypatch):
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = SimpleNamespace(
        id=9, ts=timestamp, tenant_id=None, actor_type="system", actor_id=None,
        action="seed", entity_type=None, entity_id=None, payload={"altered": True},
        prev_hash="0" * 64, hash="not-the-correct-digest",
    )
    session = MagicMock()
    session.scalars.return_value.all.return_value = [row]
    monkeypatch.setattr(db, "session", session)

    assert audit_service.verify_audit_chain() == {"valid": False, "broken_at": 9}
