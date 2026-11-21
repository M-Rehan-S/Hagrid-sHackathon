from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.enums import UserRole
from app.services import citizen_service
from app.services.citizen_service import CitizenError


def _user(role="helper"):
    return SimpleNamespace(
        id=str(uuid4()), tenant_id=str(uuid4()), role=UserRole(role), language="ur"
    )


def test_helper_created_citizen_is_tenant_scoped_linked_and_has_no_consent(monkeypatch):
    actor = _user("helper")
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    log = MagicMock()
    monkeypatch.setattr(citizen_service.audit, "log", log)
    added = []
    session.add.side_effect = added.append
    def flush():
        for row in added:
            if getattr(row, "id", None) is None:
                row.id = str(uuid4())
    session.flush.side_effect = flush

    citizen, link = citizen_service.create_citizen(actor, {
        "full_name": "  Mrs. Fatima Bibi ", "cnic": "42101-1234567-1",
        "dob": date(1978, 4, 12), "phone": "03001234567",
    })

    assert citizen.tenant_id == actor.tenant_id
    assert citizen.user_id is None
    assert citizen.created_by == actor.id
    assert citizen.full_name == "Mrs. Fatima Bibi"
    assert citizen.cnic == "4210112345671"
    assert citizen.name_normalized == "fatima"
    assert link.helper_user_id == actor.id
    assert link.citizen_id == citizen.id
    assert len(added) == 2
    assert log.call_args.kwargs["action"] == "citizen.create"
    assert log.call_args.kwargs["payload"]["helper_linked"] is True
    session.commit.assert_called_once_with()


def test_citizen_self_profile_is_bound_to_authenticated_user(monkeypatch):
    actor = _user("citizen")
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(citizen_service.audit, "log", MagicMock())
    session.flush.side_effect = lambda: setattr(session.add.call_args.args[0], "id", str(uuid4()))

    citizen, link = citizen_service.create_citizen(actor, {"full_name": "Fatima Bibi"})

    assert citizen.user_id == actor.id
    assert citizen.created_by == actor.id
    assert link is None
    assert session.add.call_count == 1


@pytest.mark.parametrize("fields", [
    {"full_name": "Fatima", "cnic": "123"},
    {"full_name": "Fatima", "phone": "03123"},
    {"full_name": "   "},
])
def test_create_citizen_rejects_invalid_identity_fields(monkeypatch, fields):
    monkeypatch.setattr(db, "session", MagicMock())

    with pytest.raises(CitizenError) as exc:
        citizen_service.create_citizen(_user(), fields)

    assert exc.value.code == "VALIDATION_ERROR"


def test_link_helper_rejects_cross_tenant_citizen(monkeypatch):
    actor = _user()
    query = MagicMock()
    query.filter_by.return_value.first.return_value = None
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(db, "session", session)

    with pytest.raises(CitizenError) as exc:
        citizen_service.link_helper_to_citizen(actor, str(uuid4()))

    assert exc.value.code == "NOT_FOUND"
    session.add.assert_not_called()


def test_get_citizen_uses_identity_consent_check(monkeypatch):
    actor = _user()
    citizen = SimpleNamespace(id=str(uuid4()))
    check = MagicMock(return_value=citizen)
    monkeypatch.setattr(citizen_service, "check_citizen_access", check)

    assert citizen_service.get_citizen(actor, citizen.id) is citizen
    assert check.call_args.args[2].value == "identity"


def test_update_citizen_changes_only_own_profile_and_refreshes_name_keys(monkeypatch):
    actor = _user("citizen")
    citizen = SimpleNamespace(
        id=str(uuid4()), tenant_id=actor.tenant_id, user_id=actor.id,
        full_name="Old Name", name_normalized="old name", name_phonetic="OLD NM",
    )
    query = MagicMock()
    query.filter_by.return_value.first.return_value = citizen
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(db, "session", session)
    log = MagicMock()
    monkeypatch.setattr(citizen_service.audit, "log", log)

    updated = citizen_service.update_citizen(actor, citizen.id, {"full_name": "Mrs. Fatima Bibi"})

    assert updated.full_name == "Mrs. Fatima Bibi"
    assert updated.name_normalized == "fatima"
    assert updated.name_phonetic
    assert log.call_args.kwargs["action"] == "citizen.update"
    assert log.call_args.kwargs["payload"] == {"updated_fields": ["full_name"]}
    session.commit.assert_called_once_with()


def test_update_citizen_rejects_helper_and_missing_fields(monkeypatch):
    with pytest.raises(CitizenError) as role_error:
        citizen_service.update_citizen(_user("helper"), str(uuid4()), {"phone": "03001234567"})
    assert role_error.value.code == "FORBIDDEN_ROLE"

    with pytest.raises(CitizenError) as fields_error:
        citizen_service.update_citizen(_user("citizen"), str(uuid4()), {})
    assert fields_error.value.code == "VALIDATION_ERROR"


def test_export_citizen_data_includes_owned_records_and_signed_document_url(monkeypatch):
    from datetime import datetime, timezone

    from app.models.case import Case
    from app.models.case_event import CaseEvent
    from app.models.citizen import Citizen
    from app.models.consent import Consent
    from app.models.decision import Decision
    from app.models.document import Document
    from app.models.helper_citizen_link import HelperCitizenLink
    from app.models.mock_payment import MockPayment

    actor = _user("citizen")
    now = datetime.now(timezone.utc)
    citizen = SimpleNamespace(
        id=str(uuid4()), tenant_id=actor.tenant_id, user_id=actor.id,
        full_name="Fatima Bibi", father_name=None, cnic="4210112345671",
        dob=date(1978, 4, 12), district="Karachi East", phone=None, language="ur",
        created_at=now,
    )
    case = SimpleNamespace(
        id=str(uuid4()), case_type="relief_claim", status="approved", route="auto_approve",
        confidence=0.99, priority=2, form_data={"full_name": "Fatima Bibi"}, missing_fields=[],
        rule_version_id=str(uuid4()), created_at=now, updated_at=now, closed_at=None,
    )
    document = SimpleNamespace(
        id=str(uuid4()), kind="cnic_photo", storage_path="private/path", ocr_text=None,
        quality_score=0.9, uploaded_by=actor.id, created_at=now,
    )
    rows_by_model = {
        Citizen: [citizen], Case: [case], Decision: [], CaseEvent: [], Document: [document],
        MockPayment: [], Consent: [], HelperCitizenLink: [],
    }
    session = MagicMock()

    def query(model):
        result = MagicMock()
        result.filter_by.return_value = result
        result.order_by.return_value = result
        result.join.return_value = result
        result.filter.return_value = result
        result.first.return_value = (rows_by_model.get(model) or [None])[0]
        result.all.return_value = rows_by_model.get(model, [])
        return result

    session.query.side_effect = query
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(
        "app.services.document_storage.create_document_download_url",
        lambda path: f"https://storage.example/{path}?signed=token",
    )
    log = MagicMock()
    monkeypatch.setattr(citizen_service.audit, "log", log)

    exported = citizen_service.export_citizen_data(actor, citizen.id)

    assert exported["citizen"]["id"] == citizen.id
    assert len(exported["cases"]) == 1
    assert exported["cases"][0]["documents"][0]["download_url"].endswith("signed=token")
    assert "storage_path" not in exported["cases"][0]["documents"][0]
    assert log.call_args.kwargs["action"] == "data.export"
    session.commit.assert_called_once_with()
