from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from flask import Flask

from app import auth as auth_module
from app.api import cases as cases_api
from app.api.cases import cases_bp, _decision_data
from app.auth import register_auth_error_handler
from app.extensions import db


def _app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(cases_bp, url_prefix="/api/v1/cases")
    return flask_app


def test_post_case_validates_body_and_returns_created_case(monkeypatch):
    flask_app = _app()
    user = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role="citizen", is_active=True)
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": user.id})
    monkeypatch.setattr(db.session, "get", lambda *_args: user)
    case = SimpleNamespace(
        id=str(uuid4()), tenant_id=user.tenant_id, case_type="relief_claim",
        citizen_id=str(uuid4()), created_by=user.id, assigned_to=None,
        status="draft", route=None, confidence=None, priority=2, form_data={},
        missing_fields=["full_name"], rule_version_id=None, last_step=None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc), closed_at=None,
    )
    create = MagicMock(return_value=case)
    monkeypatch.setattr(cases_api, "create_case", create)

    response = flask_app.test_client().post(
        "/api/v1/cases",
        json={"citizen_id": case.citizen_id, "case_type": "relief_claim"},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 201
    assert response.json["error"] is None
    assert response.json["data"]["status"] == "draft"
    create.assert_called_once()


def test_post_case_rejects_unsupported_fields(monkeypatch):
    flask_app = _app()
    user = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role="citizen", is_active=True)
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": user.id})
    monkeypatch.setattr(db.session, "get", lambda *_args: user)

    response = flask_app.test_client().post(
        "/api/v1/cases",
        json={"citizen_id": str(uuid4()), "case_type": "relief_claim", "tenant_id": str(uuid4())},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 400
    assert response.json["error"]["code"] == "VALIDATION_ERROR"


def test_decision_trace_is_not_serialized_to_citizen_or_helper():
    decision = SimpleNamespace(
        id=str(uuid4()), case_id=str(uuid4()), actor_type="ai", actor_id=None,
        route="human_review", outcome="human_review", confidence=0.5,
        rule_version_id=str(uuid4()), model_version="engine-v1",
        reason_en="Officer review required.", reason_ur="افسر کا جائزہ درکار ہے۔",
        trace={"input_snapshot": {"form_data": {"cnic": "sensitive"}}},
        created_at=datetime.now(timezone.utc),
    )

    public_data = _decision_data(decision)
    officer_data = _decision_data(decision, include_trace=True)

    assert "trace" not in public_data
    assert officer_data["trace"] == decision.trace
