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
