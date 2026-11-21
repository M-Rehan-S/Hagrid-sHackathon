from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from flask import Flask

from app import auth as auth_module
from app.api import rules as rules_api
from app.api.rules import rules_bp
from app.auth import register_auth_error_handler
from app.extensions import db


def _app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(rules_bp, url_prefix="/api/v1/rules")
    return flask_app


def _definition():
    return {
        "rule_key": "relief_eligibility",
        "match": "all",
        "conditions": [
            {"id": "income", "field": "monthly_income", "op": "lte", "value": 30000,
             "reason_en": "Income limit.", "reason_ur": "آمدنی کی حد۔"}
        ],
        "required_documents": ["cnic_photo"],
        "amount": 25000,
        "thresholds": {"auto_approve": 0.98, "ask_more": 0.70},
        "cost": {"wrong_approval": 50, "manual_review": 1},
        "anomaly": {
            "duplicate_open_claim": {"enabled": True},
            "helper_burst": {
                "enabled": True, "max_per_window": 10,
                "window_minutes": 10, "max_per_day": 60,
            },
            "deceased_match": {"enabled": True},
        },
    }


def _authorize(monkeypatch, role="admin"):
    user = SimpleNamespace(
        id=str(uuid4()), tenant_id=str(uuid4()), role=role, is_active=True
    )
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": user.id})
    session = MagicMock()
    session.get.return_value = user
    monkeypatch.setattr(db, "session", session)
    return user


def test_create_rule_validates_payload_and_creates_versioned_draft(monkeypatch):
    flask_app = _app()
    user = _authorize(monkeypatch)
    created = SimpleNamespace(
        id=str(uuid4()), tenant_id=user.tenant_id, rule_key="relief_eligibility",
        version=3, status="draft", definition=_definition(), note="Updated limit",
        created_by=user.id, created_at=datetime.now(timezone.utc), activated_at=None,
    )
    create = MagicMock(return_value=created)
    monkeypatch.setattr(rules_api, "create_rule_draft", create)

    response = flask_app.test_client().post(
        "/api/v1/rules",
        json={"rule_key": "relief_eligibility", "definition": _definition(), "note": "Updated limit"},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 201
    assert response.json["data"]["version"] == 3
    assert response.json["data"]["status"] == "draft"
    create.assert_called_once()
    assert create.call_args.args[:2] == (user.tenant_id, "relief_eligibility")
    assert create.call_args.args[4] == user.id


def test_create_rule_rejects_invalid_operator_and_cost_threshold(monkeypatch):
    flask_app = _app()
    _authorize(monkeypatch)
    create = MagicMock()
    monkeypatch.setattr(rules_api, "create_rule_draft", create)
    bad_definition = _definition()
    bad_definition["conditions"][0]["op"] = "contains"

    response = flask_app.test_client().post(
        "/api/v1/rules",
        json={"rule_key": "relief_eligibility", "definition": bad_definition},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 400
    assert response.json["error"]["code"] == "VALIDATION_ERROR"
    create.assert_not_called()

    bad_definition["conditions"][0]["op"] = "lte"
    bad_definition["thresholds"]["auto_approve"] = 0.95
    response = flask_app.test_client().post(
        "/api/v1/rules",
        json={"rule_key": "relief_eligibility", "definition": bad_definition},
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code == 400
    assert response.json["error"]["code"] == "VALIDATION_ERROR"


def test_create_rule_requires_admin_role(monkeypatch):
    flask_app = _app()
    _authorize(monkeypatch, role="officer")

    response = flask_app.test_client().post(
        "/api/v1/rules",
        json={"rule_key": "relief_eligibility", "definition": _definition()},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403
    assert response.json["error"]["code"] == "FORBIDDEN_ROLE"


def test_activation_passes_current_tenant_to_service(monkeypatch):
    flask_app = _app()
    user = _authorize(monkeypatch)
    activated = SimpleNamespace(
        id=str(uuid4()), tenant_id=user.tenant_id, rule_key="relief_eligibility",
        version=2, status="active", definition=_definition(), note="v2",
        created_by=user.id, created_at=datetime.now(timezone.utc), activated_at=datetime.now(timezone.utc),
    )
    activate = MagicMock(return_value=activated)
    monkeypatch.setattr(rules_api, "activate_rule", activate)

    response = flask_app.test_client().post(
        f"/api/v1/rules/{activated.id}/activate",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.json["data"]["status"] == "active"
    activate.assert_called_once_with(activated.id, user.id, tenant_id=user.tenant_id)


def test_activation_hides_rule_outside_tenant(monkeypatch):
    flask_app = _app()
    _authorize(monkeypatch)
    activate = MagicMock(return_value=None)
    monkeypatch.setattr(rules_api, "activate_rule", activate)

    response = flask_app.test_client().post(
        f"/api/v1/rules/{uuid4()}/activate",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 404
    assert response.json["error"]["code"] == "NOT_FOUND"


def test_rule_list_is_tenant_scoped_and_can_filter_key(monkeypatch):
    flask_app = _app()
    user = _authorize(monkeypatch, role="officer")
    row = SimpleNamespace(
        id=str(uuid4()), tenant_id=user.tenant_id, rule_key="relief_eligibility",
        version=1, status="active", definition=_definition(), note=None,
        created_by=None, created_at=datetime.now(timezone.utc), activated_at=None,
    )
    session = db.session
    query = MagicMock()
    query.filter_by.return_value = query
    query.order_by.return_value.all.return_value = [row]
    session.query.return_value = query

    response = flask_app.test_client().get(
        "/api/v1/rules?rule_key=relief_eligibility",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert len(response.json["data"]) == 1
    assert query.filter_by.call_args_list[0].kwargs == {"tenant_id": user.tenant_id}
    assert query.filter_by.call_args_list[1].kwargs == {"rule_key": "relief_eligibility"}
