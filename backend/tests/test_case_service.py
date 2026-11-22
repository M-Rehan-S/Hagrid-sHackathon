from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.enums import CaseStatus, CaseType, ConsentScope, DecisionOutcome, UserRole
from app.services import case_service
from app.services.case_service import CaseError


def _user(role="citizen"):
    return SimpleNamespace(
        id=str(uuid4()), tenant_id=str(uuid4()), role=UserRole(role), is_active=True
    )


def _case(actor, *, status=CaseStatus.draft):
    return SimpleNamespace(
        id=str(uuid4()), tenant_id=actor.tenant_id, citizen_id=str(uuid4()),
        created_by=actor.id, case_type=CaseType.relief_claim, status=status,
        form_data={}, missing_fields=[], last_step=None, priority=2,
        assigned_to=None, rule_version_id=str(uuid4()), updated_at=None,
        closed_at=None, route=None, confidence=None,
    )


def test_required_fields_derive_from_active_rule_and_identity_inputs(monkeypatch):
    monkeypatch.setattr(
        case_service,
        "get_active_rule",
        lambda *_args: SimpleNamespace(definition={"conditions": [
            {"field": "monthly_income"}, {"field": "district"}, {"field": "is_widow"}
        ]}),
    )

    missing = case_service._missing_fields(
        {"full_name": "Fatima Bibi", "dob": "1978-04-12", "district": "Karachi East"},
        str(uuid4()),
    )

    assert missing == ["is_widow", "monthly_income"]


def test_required_fields_request_identity_corroboration_when_name_is_alone(monkeypatch):
    monkeypatch.setattr(case_service, "get_active_rule", lambda *_: SimpleNamespace(definition={"conditions": []}))

    assert case_service._missing_fields({"full_name": "Fatima Bibi"}, str(uuid4())) == ["identity_corroborator"]


def test_list_cases_runs_consent_and_pii_audit_check_for_citizen_cases(monkeypatch):
    actor = _user("citizen")
    item = _case(actor)
    query = MagicMock()
    query.filter_by.return_value = query
    query.join.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = [item]
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(db, "session", session)
    access_check = MagicMock()
    monkeypatch.setattr(case_service, "check_citizen_access", access_check)

    result = case_service.list_cases(actor, {})

    assert result == [item]
    access_check.assert_called_once_with(
        actor, item.citizen_id, ConsentScope.claim_data
    )


def test_form_validation_normalizes_cnic_and_reports_bad_fields():
    normalized, invalid = case_service._validate_form({
        "full_name": "Fatima Bibi",
        "cnic": "42101-1234567-1",
        "phone": "123",
        "dob": "not-a-date",
        "monthly_income": -1,
        "household_size": 1.5,
    })

    assert normalized["cnic"] == "4210112345671"
    assert invalid == ["dob", "household_size", "monthly_income", "phone"]


def test_patch_form_merges_saves_missing_fields_and_audits(monkeypatch):
    actor = _user()
    item = _case(actor)
    item.form_data = {"full_name": "Old Name", "district": "Karachi East"}
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(case_service, "_case_or_404", lambda *_: item)
    monkeypatch.setattr(case_service, "_require_case_access", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(case_service, "_missing_fields", lambda *_: ["is_widow"])
    log = MagicMock()
    monkeypatch.setattr(case_service.audit, "log", log)

    updated = case_service.update_form(
        actor, item.id, {"full_name": "New Name", "monthly_income": 0}, "income"
    )

    assert updated.form_data["full_name"] == "New Name"
    assert updated.form_data["monthly_income"] == 0
    assert updated.missing_fields == ["is_widow"]
    assert updated.last_step == "income"
    assert log.call_args.kwargs["action"] == "case.update_form"
    session.commit.assert_called_once_with()


def test_patch_form_rejects_client_controlled_invalid_fields(monkeypatch):
    actor = _user()
    item = _case(actor)
    monkeypatch.setattr(case_service, "_case_or_404", lambda *_: item)
    monkeypatch.setattr(case_service, "_require_case_access", lambda *_args, **_kwargs: None)

    with pytest.raises(CaseError) as exc:
        case_service.update_form(actor, item.id, {"invalid_fields": []}, None)

    assert exc.value.code == "VALIDATION_ERROR"


def test_submit_with_missing_fields_sets_needs_info_without_deciding(monkeypatch):
    actor = _user()
    item = _case(actor)
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(case_service, "_case_or_404", lambda *_: item)
    monkeypatch.setattr(case_service, "_require_case_access", lambda *_args, **_kwargs: SimpleNamespace(id=item.citizen_id))
    monkeypatch.setattr(case_service, "_missing_fields", lambda *_: ["monthly_income"])
    log = MagicMock()
    monkeypatch.setattr(case_service.audit, "log", log)

    result = case_service.submit_case(actor, item.id)

    assert item.status == CaseStatus.needs_info
    assert result["missing_fields"] == ["monthly_income"]
    assert "decision" not in result
    assert log.call_args.kwargs["action"] == "case.submit"
    session.commit.assert_called_once_with()


def test_submit_requires_officer_consent_before_decision(monkeypatch):
    actor = _user()
    item = _case(actor)
    citizen = SimpleNamespace(id=item.citizen_id)
    monkeypatch.setattr(case_service, "_case_or_404", lambda *_: item)
    monkeypatch.setattr(case_service, "_require_case_access", lambda *_args, **_kwargs: citizen)
    monkeypatch.setattr(case_service, "_missing_fields", lambda *_: [])
    monkeypatch.setattr(case_service, "_active_officer_consent", lambda *_: False)

    with pytest.raises(CaseError) as exc:
        case_service.submit_case(actor, item.id)

    assert exc.value.code == "CONSENT_REQUIRED"


def test_officer_approval_creates_decision_payment_event_and_audit(monkeypatch):
    actor = _user("officer")
    item = _case(actor, status=CaseStatus.in_review)
    item.rule_version_id = "rule-v1"
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(case_service, "_case_or_404", lambda *_: item)
    monkeypatch.setattr(case_service, "_require_case_access", lambda *_args, **_kwargs: None)
    rule_query = MagicMock()
    rule_query.filter_by.return_value.first.return_value = SimpleNamespace(
        id="rule-v1", tenant_id=actor.tenant_id, definition={"amount": 25000}
    )
    session.query.return_value = rule_query
    log = MagicMock()
    monkeypatch.setattr(case_service.audit, "log", log)
    def assert_notifier_runs_after_commit(*_args, **_kwargs):
        assert session.commit.call_count == 1
    notification = MagicMock(side_effect=assert_notifier_runs_after_commit)
    monkeypatch.setattr(case_service, "notify_case_decision", notification)

    updated = case_service.decide_case_as_officer(
        actor, item.id, DecisionOutcome.approved, "Approved after review."
    )

    assert updated.status == CaseStatus.approved
    assert session.add.call_count == 3  # decision, event, mock payment
    assert log.call_args.kwargs["action"] == "officer.decision"
    session.commit.assert_called_once_with()
    decision = session.add.call_args_list[0].args[0]
    assert decision.reason_en.startswith("An officer approved")
    assert "افسر نے" in decision.reason_ur
    assert decision.trace == {"note": "Approved after review."}
    notification.assert_called_once_with(item, decision, officer_approval=True)


def test_submit_notifies_only_after_decision_commit(monkeypatch):
    actor = _user("citizen")
    item = _case(actor, status=CaseStatus.draft)
    decision = SimpleNamespace(route="auto_approve")
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(case_service, "_case_or_404", lambda *_: item)
    monkeypatch.setattr(case_service, "_require_case_access", lambda *_args, **_kwargs: SimpleNamespace(id=item.citizen_id))
    monkeypatch.setattr(case_service, "_missing_fields", lambda *_: [])
    monkeypatch.setattr(case_service, "_active_officer_consent", lambda *_: True)
    monkeypatch.setattr(case_service.audit, "log", MagicMock())

    def persist_decision(_case_id):
        session.commit()
        return decision

    monkeypatch.setattr("app.services.decision_engine.decide", persist_decision)
    def assert_notifier_runs_after_commit(*_args, **_kwargs):
        assert session.commit.call_count == 1
    notification = MagicMock(side_effect=assert_notifier_runs_after_commit)
    monkeypatch.setattr(case_service, "notify_case_decision", notification)

    result = case_service.submit_case(actor, item.id)

    assert result["decision"] is decision
    session.commit.assert_called_once_with()
    notification.assert_called_once_with(item, decision)


def test_create_case_scopes_citizen_creates_event_and_audits(monkeypatch):
    actor = _user("citizen")
    citizen = SimpleNamespace(id=str(uuid4()), tenant_id=actor.tenant_id, user_id=actor.id)
    query = MagicMock()
    query.filter_by.return_value.first.return_value = citizen
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(case_service, "_missing_fields", lambda *_: ["full_name"])
    log = MagicMock()
    monkeypatch.setattr(case_service.audit, "log", log)

    item = case_service.create_case(actor, citizen.id, CaseType.relief_claim)

    assert item.status == CaseStatus.draft
    assert item.tenant_id == actor.tenant_id
    assert item.missing_fields == ["full_name"]
    assert session.add.call_count == 2  # case and created event
    assert log.call_args.kwargs["action"] == "case.create"
    session.commit.assert_called_once_with()


def test_upload_document_uses_private_storage_path_and_audits(monkeypatch):
    actor = _user()
    item = _case(actor)
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(case_service, "_case_or_404", lambda *_: item)
    monkeypatch.setattr(case_service, "_require_case_access", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "app.services.document_storage.upload_case_document",
        lambda **_kwargs: f"{item.tenant_id}/{item.id}/random-key",
    )
    log = MagicMock()
    monkeypatch.setattr(case_service.audit, "log", log)

    document = case_service.upload_document(
        actor,
        item.id,
        kind="cnic_photo",
        content=b"fake-image-content",
        content_type="image/jpeg",
    )

    assert document.storage_path == f"{item.tenant_id}/{item.id}/random-key"
    assert document.uploaded_by == actor.id
    assert log.call_args.kwargs["action"] == "document.upload"
    session.commit.assert_called_once_with()
