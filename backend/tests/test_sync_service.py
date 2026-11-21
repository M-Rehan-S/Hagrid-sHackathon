from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.enums import CaseStatus
from app.models.idempotency_key import IdempotencyKey
from app.services import sync_service
from app.services.sync_service import SyncError


def _user(role="citizen"):
    return SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role=role)


def _session_with_existing(existing=None):
    session = MagicMock()
    query = MagicMock()
    query.filter_by.return_value.first.return_value = existing
    session.query.return_value = query
    return session


def test_sync_batch_create_operation_persists_key_and_result_atomically(monkeypatch):
    actor = _user()
    session = _session_with_existing()
    monkeypatch.setattr(db, "session", session)
    create = MagicMock(return_value=SimpleNamespace(id="case-123", status=CaseStatus.draft))
    monkeypatch.setattr(sync_service, "create_case", create)
    log = MagicMock()
    monkeypatch.setattr(sync_service.audit, "log", log)
    op_id = str(uuid4())

    result = sync_service.sync_batch(actor, [{
        "client_op_id": op_id,
        "type": "create_case",
        "payload": {"citizen_id": str(uuid4()), "case_type": "relief_claim"},
    }])

    assert result == [{
        "client_op_id": op_id, "status": "applied",
        "result": {"case_id": "case-123", "status": "draft"}, "error": None,
    }]
    create.assert_called_once()
    assert create.call_args.kwargs["commit"] is False
    assert any(isinstance(call.args[0], IdempotencyKey) for call in session.add.call_args_list)
    log.assert_called_once()
    assert log.call_args.kwargs["action"] == "sync.batch"
    session.commit.assert_called_once_with()


def test_replaying_same_operation_returns_stored_result_without_applying(monkeypatch):
    actor = _user()
    op_id = str(uuid4())
    existing = SimpleNamespace(
        key=op_id, user_id=actor.id, response={"case_id": "original-case", "status": "draft"}
    )
    session = _session_with_existing(existing)
    monkeypatch.setattr(db, "session", session)
    apply = MagicMock()
    monkeypatch.setattr(sync_service, "_apply", apply)

    result = sync_service.sync_batch(actor, [{
        "client_op_id": op_id, "type": "create_case", "payload": {},
    }])

    assert result[0]["status"] == "duplicate"
    assert result[0]["result"] == existing.response
    apply.assert_not_called()
    session.add.assert_not_called()


def test_operation_key_cannot_be_reused_by_another_user(monkeypatch):
    actor = _user()
    existing = SimpleNamespace(key=str(uuid4()), user_id=str(uuid4()), response={})
    session = _session_with_existing(existing)
    monkeypatch.setattr(db, "session", session)
    op_id = existing.key

    result = sync_service.sync_batch(actor, [{
        "client_op_id": op_id, "type": "create_case", "payload": {},
    }])

    assert result[0]["status"] == "error"
    assert result[0]["error"]["code"] == "CONFLICT"


def test_sync_keeps_processing_after_one_operation_fails(monkeypatch):
    actor = _user()
    session = _session_with_existing()
    monkeypatch.setattr(db, "session", session)
    case = SimpleNamespace(id="case-2", status=CaseStatus.draft)
    create = MagicMock(side_effect=[ValueError("bad op"), case])
    monkeypatch.setattr(sync_service, "create_case", create)
    monkeypatch.setattr(sync_service.audit, "log", MagicMock())
    ops = [
        {"client_op_id": str(uuid4()), "type": "create_case", "payload": {
            "citizen_id": str(uuid4()), "case_type": "relief_claim",
        }},
        {"client_op_id": str(uuid4()), "type": "create_case", "payload": {
            "citizen_id": str(uuid4()), "case_type": "relief_claim",
        }},
    ]

    results = sync_service.sync_batch(actor, ops)

    assert results[0]["status"] == "error"
    assert results[0]["error"]["code"] == "INTERNAL_ERROR"
    assert results[1]["status"] == "applied"
    assert create.call_count == 2
    session.commit.assert_called_once_with()
    session.rollback.assert_called_once_with()


def test_sync_validates_batch_size_and_role():
    with pytest.raises(SyncError):
        sync_service.sync_batch(_user(), [])
    with pytest.raises(SyncError) as exc:
        sync_service.sync_batch(_user("admin"), [{"client_op_id": str(uuid4())}])
    assert exc.value.code == "FORBIDDEN_ROLE"


def test_invalid_operation_returns_per_operation_error(monkeypatch):
    monkeypatch.setattr(db, "session", _session_with_existing())

    result = sync_service.sync_batch(_user(), [{
        "client_op_id": str(uuid4()), "type": "delete_case", "payload": {},
    }])

    assert result[0]["status"] == "error"
    assert result[0]["error"]["code"] == "VALIDATION_ERROR"
