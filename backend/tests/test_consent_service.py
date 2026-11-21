from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from flask import Flask

from app.api.consents import consents_bp
from app import auth as auth_module
from app.auth import register_auth_error_handler
from app.extensions import db
from app.models.enums import ConsentScope, ConsentStatus, UserRole
from app.services import consent_service
from app.services.consent_service import ConsentError


@pytest.fixture
def actor():
    return SimpleNamespace(
        id=str(uuid4()), tenant_id=str(uuid4()), role=UserRole.citizen, is_active=True
    )


@pytest.fixture
def citizen(actor):
    return SimpleNamespace(
        id=str(uuid4()), tenant_id=actor.tenant_id, user_id=actor.id
    )


def test_grant_consent_persists_audit_and_commit(actor, citizen, monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    citizen_query, recipient_query = MagicMock(), MagicMock()
    citizen_query.filter_by.return_value.first.return_value = citizen
    recipient_query.filter_by.return_value.first.return_value = SimpleNamespace(id=str(uuid4()))
    session.query.side_effect = [citizen_query, recipient_query]
    log = MagicMock()
    monkeypatch.setattr(consent_service.audit, "log", log)

    consent = consent_service.grant_consent(
        actor,
        citizen_id=citizen.id,
        grantee_user_id=str(uuid4()),
        grantee_role=None,
        scope=ConsentScope.identity,
    )

    assert consent.status == ConsentStatus.granted
    assert consent.scope == ConsentScope.identity
    session.add.assert_called_once_with(consent)
    session.flush.assert_called_once_with()
    session.commit.assert_called_once_with()
    assert log.call_args.kwargs["action"] == "consent.grant"


def test_grant_consent_rejects_non_owner_without_writing(actor, citizen, monkeypatch):
    citizen.user_id = str(uuid4())
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    query = MagicMock()
    query.filter_by.return_value.first.return_value = citizen
    session.query.return_value = query

    with pytest.raises(ConsentError) as exc:
        consent_service.grant_consent(
            actor,
            citizen_id=citizen.id,
            grantee_user_id=None,
            grantee_role=UserRole.officer,
            scope=ConsentScope.claim_data,
        )

    assert exc.value.code == "NOT_FOUND"
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_grant_consent_requires_exactly_one_grantee(actor, citizen, monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    query = MagicMock()
    query.filter_by.return_value.first.return_value = citizen
    session.query.return_value = query

    with pytest.raises(ConsentError) as exc:
        consent_service.grant_consent(
            actor,
            citizen_id=citizen.id,
            grantee_user_id=None,
            grantee_role=None,
            scope=ConsentScope.identity,
        )

    assert exc.value.code == "VALIDATION_ERROR"


def test_withdrawal_is_immediate_audited_and_committed(actor, citizen, monkeypatch):
    consent = SimpleNamespace(
        id=str(uuid4()), citizen_id=citizen.id,
        scope=ConsentScope.claim_data,
        status=ConsentStatus.granted, withdrawn_at=None,
    )
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    consent_query, citizen_query = MagicMock(), MagicMock()
    consent_query.filter_by.return_value.first.return_value = consent
    citizen_query.filter_by.return_value.first.return_value = citizen
    session.query.side_effect = [consent_query, citizen_query]
    log = MagicMock()
    monkeypatch.setattr(consent_service.audit, "log", log)

    result = consent_service.withdraw_consent(actor, consent.id)

    assert result.status == ConsentStatus.withdrawn
    assert result.withdrawn_at is not None
    assert log.call_args.kwargs["action"] == "consent.withdraw"
    session.commit.assert_called_once_with()


def test_withdrawn_consent_cannot_be_withdrawn_twice(actor, citizen, monkeypatch):
    consent = SimpleNamespace(
        id=str(uuid4()), citizen_id=citizen.id, status=ConsentStatus.withdrawn
    )
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    consent_query, citizen_query = MagicMock(), MagicMock()
    consent_query.filter_by.return_value.first.return_value = consent
    citizen_query.filter_by.return_value.first.return_value = citizen
    session.query.side_effect = [consent_query, citizen_query]

    with pytest.raises(ConsentError) as exc:
        consent_service.withdraw_consent(actor, consent.id)

    assert exc.value.code == "CONFLICT"
    session.commit.assert_not_called()


def test_helper_access_requires_link_and_granted_consent(actor, citizen, monkeypatch):
    actor.role = UserRole.helper
    granted = SimpleNamespace(
        grantee_user_id=actor.id,
        grantee_role=None,
        status=ConsentStatus.granted,
    )
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    citizen_query, link_query, consent_query = MagicMock(), MagicMock(), MagicMock()
    citizen_query.filter_by.return_value.first.return_value = citizen
    link_query.filter_by.return_value.first.return_value = SimpleNamespace(status="active")
    consent_query.filter_by.return_value.order_by.return_value.all.return_value = [granted]
    session.query.side_effect = [citizen_query, link_query, consent_query]
    log = MagicMock()
    monkeypatch.setattr(consent_service.audit, "log", log)

    result = consent_service.check_citizen_access(actor, citizen.id, ConsentScope.identity)

    assert result is citizen
    assert log.call_args.kwargs["action"] == "data.read_pii"
    session.commit.assert_called_once_with()


def test_withdrawn_consent_denies_and_audits_next_access(actor, citizen, monkeypatch):
    actor.role = UserRole.officer
    withdrawn = SimpleNamespace(
        grantee_role=UserRole.officer,
        status=ConsentStatus.withdrawn,
    )
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    citizen_query, consent_query = MagicMock(), MagicMock()
    citizen_query.filter_by.return_value.first.return_value = citizen
    consent_query.filter_by.return_value.order_by.return_value.all.return_value = [withdrawn]
    session.query.side_effect = [citizen_query, consent_query]
    log = MagicMock()
    monkeypatch.setattr(consent_service.audit, "log", log)

    with pytest.raises(ConsentError) as exc:
        consent_service.check_citizen_access(actor, citizen.id, ConsentScope.claim_data)

    assert exc.value.code == "CONSENT_WITHDRAWN"
    assert log.call_args.kwargs["action"] == "consent.access_denied"
    session.commit.assert_called_once_with()


def test_consent_endpoint_returns_proposal_error_envelope_for_invalid_body(monkeypatch):
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(consents_bp, url_prefix="/api/v1/consents")
    user = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role=UserRole.citizen, is_active=True)
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": user.id})
    monkeypatch.setattr(db.session, "get", lambda *_args: user)

    response = flask_app.test_client().post(
        "/api/v1/consents",
        json={"citizen_id": str(uuid4()), "scope": "identity"},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 400
    assert response.json["error"]["code"] == "VALIDATION_ERROR"
