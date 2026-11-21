from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from flask import Flask

from app import auth as auth_module
from app.api import mock_services as mock_api
from app.api.mock_services import mock_services_bp
from app.auth import register_auth_error_handler
from app.extensions import db
from app.models.enums import CaseStatus
from app.services import mock_services
from app.services.mock_services import MockServiceError


def _app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(mock_services_bp, url_prefix="/api/v1/mock")
    return flask_app


def _user(role="citizen"):
    return SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role=role, is_active=True)


def _authorize(monkeypatch, user):
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": user.id})
    session = MagicMock()
    session.get.return_value = user
    monkeypatch.setattr(db, "session", session)
    return session


def test_identity_lookup_returns_match_and_audits_pii_read(monkeypatch):
    actor = _user()
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    match = SimpleNamespace(matched_record_id="record-1")
    monkeypatch.setattr(mock_services, "match_identity", lambda form: match)
    log = MagicMock()
    monkeypatch.setattr(mock_services.audit, "log", log)

    result = mock_services.lookup_identity(actor, {"cnic": "4210112345671"})

    assert result is match
    assert log.call_args.kwargs["action"] == "data.read_pii"
    assert log.call_args.kwargs["payload"] == {"query_fields": ["cnic"]}
    session.commit.assert_called_once_with()


def test_mock_payment_requires_approved_case_and_exact_rule_amount(monkeypatch):
    actor = _user("admin")
    case_query, rule_query = MagicMock(), MagicMock()
    case_query.filter_by.return_value.first.return_value = SimpleNamespace(
        id=str(uuid4()), tenant_id=actor.tenant_id, status=CaseStatus.in_review,
    )
    session = MagicMock()
    session.query.side_effect = [case_query]
    monkeypatch.setattr(db, "session", session)

    with pytest.raises(MockServiceError) as exc:
        mock_services.create_mock_payment(actor, case_id=str(uuid4()), amount=Decimal("25000.00"))

    assert exc.value.code == "CONFLICT"
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_mock_payment_is_created_once_with_rule_amount_and_audit(monkeypatch):
    actor = _user("admin")
    case_id = str(uuid4())
    case_item = SimpleNamespace(
        id=case_id, tenant_id=actor.tenant_id, status=CaseStatus.approved,
        rule_version_id=str(uuid4()),
    )
    case_query, rule_query, payment_query = MagicMock(), MagicMock(), MagicMock()
    case_query.filter_by.return_value.first.return_value = case_item
    rule_query.filter_by.return_value.first.return_value = SimpleNamespace(
        definition={"amount": 25000}
    )
    payment_query.filter_by.return_value.first.return_value = None
    session = MagicMock()
    session.query.side_effect = [case_query, rule_query, payment_query]
    session.flush.side_effect = lambda: setattr(session.add.call_args.args[0], "id", "payment-id")
    monkeypatch.setattr(db, "session", session)
    log = MagicMock()
    monkeypatch.setattr(mock_services.audit, "log", log)

    payment, created = mock_services.create_mock_payment(
        actor, case_id=case_id, amount=Decimal("25000.00")
    )

    assert created is True
    assert payment.case_id == case_id
    assert payment.amount == Decimal("25000.00")
    assert payment.reference.startswith("MOCK-")
    assert log.call_args.kwargs["action"] == "mock.payment.create"
    assert log.call_args.kwargs["entity_id"] == "payment-id"
    session.commit.assert_called_once_with()


def test_existing_mock_payment_is_returned_without_duplicate_write(monkeypatch):
    actor = _user("officer")
    case_id = str(uuid4())
    case_item = SimpleNamespace(
        id=case_id, tenant_id=actor.tenant_id, status=CaseStatus.approved,
        rule_version_id=str(uuid4()),
    )
    existing = SimpleNamespace(id=str(uuid4()), case_id=case_id)
    case_query, rule_query, payment_query = MagicMock(), MagicMock(), MagicMock()
    case_query.filter_by.return_value.first.return_value = case_item
    rule_query.filter_by.return_value.first.return_value = SimpleNamespace(definition={"amount": 25000})
    payment_query.filter_by.return_value.first.return_value = existing
    session = MagicMock()
    session.query.side_effect = [case_query, rule_query, payment_query]
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(mock_services, "_require_case_access", lambda *_: None)
    log = MagicMock()
    monkeypatch.setattr(mock_services.audit, "log", log)

    payment, created = mock_services.create_mock_payment(
        actor, case_id=case_id, amount=Decimal("25000.00")
    )

    assert payment is existing
    assert created is False
    session.add.assert_not_called()
    session.commit.assert_not_called()
    log.assert_not_called()


def test_admin_cannot_read_payment_status(monkeypatch):
    actor = _user("admin")
    payment = SimpleNamespace(id=str(uuid4()), case_id=str(uuid4()))
    case_item = SimpleNamespace(id=payment.case_id, tenant_id=actor.tenant_id)
    payment_query, case_query = MagicMock(), MagicMock()
    payment_query.join.return_value.filter.return_value.first.return_value = payment
    case_query.filter_by.return_value.first.return_value = case_item
    session = MagicMock()
    session.query.side_effect = [payment_query, case_query]
    monkeypatch.setattr(db, "session", session)

    with pytest.raises(MockServiceError) as exc:
        mock_services.get_mock_payment(actor, payment.id)

    assert exc.value.code == "FORBIDDEN_ROLE"


def test_mock_complaint_checks_case_access_and_returns_fake_reference(monkeypatch):
    actor = _user("helper")
    case_item = SimpleNamespace(id=str(uuid4()), tenant_id=actor.tenant_id)
    query = MagicMock()
    query.filter_by.return_value.first.return_value = case_item
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(db, "session", session)
    access_check = MagicMock()
    monkeypatch.setattr(mock_services, "_require_case_access", access_check)

    reference = mock_services.submit_mock_complaint(
        actor, case_id=case_item.id, complaint_text="Please review this case."
    )

    assert reference.startswith("CMP-")
    access_check.assert_called_once_with(actor, case_item)
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_identity_lookup_endpoint_is_limited_to_citizen_and_helper(monkeypatch):
    flask_app = _app()
    user = _user("citizen")
    _authorize(monkeypatch, user)
    match = SimpleNamespace(model_dump=lambda: {"status": "exact", "candidates": []})
    lookup = MagicMock(return_value=match)
    monkeypatch.setattr(mock_api, "lookup_identity", lookup)

    response = flask_app.test_client().post(
        "/api/v1/mock/identity/lookup",
        json={"cnic": "4210112345671"},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.json["data"]["status"] == "exact"
    lookup.assert_called_once()


def test_complaint_endpoint_validates_body_and_returns_reference(monkeypatch):
    flask_app = _app()
    user = _user("helper")
    _authorize(monkeypatch, user)
    submit = MagicMock(return_value="CMP-ABC123")
    monkeypatch.setattr(mock_api, "submit_mock_complaint", submit)

    response = flask_app.test_client().post(
        "/api/v1/mock/complaints",
        json={"case_id": str(uuid4()), "text": "Need an update."},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 201
    assert response.json["data"]["complaint_reference"] == "CMP-ABC123"


def test_payment_endpoint_rejects_non_approved_role(monkeypatch):
    flask_app = _app()
    user = _user("citizen")
    _authorize(monkeypatch, user)

    response = flask_app.test_client().post(
        "/api/v1/mock/payments",
        json={"case_id": str(uuid4()), "amount": "25000.00"},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403
    assert response.json["error"]["code"] == "FORBIDDEN_ROLE"
