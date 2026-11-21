from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app import auth as auth_module
from app.api import twin as twin_api
from app.api.twin import twin_bp
from app.auth import register_auth_error_handler
from app.extensions import db
from app.models.enums import CaseStatus, CaseType, DecisionOutcome, RuleStatus
from app.services import twin_service
from app.services.twin_service import TwinError


def _rule(tenant_id):
    return SimpleNamespace(
        id=str(uuid4()), tenant_id=tenant_id, rule_key="relief_eligibility",
        status=RuleStatus.draft, definition={"rule_key": "relief_eligibility"},
    )


def _case(tenant_id, *, eligible, status=CaseStatus.in_review):
    return SimpleNamespace(
        id=str(uuid4()), tenant_id=tenant_id, case_type=CaseType.relief_claim,
        status=status, form_data={"eligible": eligible}, missing_fields=[],
        created_at=datetime.now(timezone.utc),
    )


def test_simulation_replays_outcomes_and_does_not_write(monkeypatch):
    tenant_id = str(uuid4())
    draft = _rule(tenant_id)
    cases = [_case(tenant_id, eligible=False), _case(tenant_id, eligible=True)]
    latest_decisions = [
        SimpleNamespace(outcome=DecisionOutcome.approved),
        SimpleNamespace(outcome=DecisionOutcome.human_review),
    ]

    rule_query, case_query = MagicMock(), MagicMock()
    case_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = cases
    decisions_queries = [MagicMock(), MagicMock()]
    for query, decision in zip(decisions_queries, latest_decisions):
        query.filter_by.return_value.order_by.return_value.first.return_value = decision
    document_queries = [MagicMock(), MagicMock()]
    for query in document_queries:
        query.filter_by.return_value.all.return_value = [
            SimpleNamespace(kind="cnic_photo", quality_score=1.0)
        ]

    session = MagicMock()
    session.query.side_effect = [
        rule_query, case_query,
        decisions_queries[0], document_queries[0],
        decisions_queries[1], document_queries[1],
    ]
    rule_query.filter_by.return_value.first.return_value = draft
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(
        twin_service.identity_match,
        "match_identity",
        lambda _form: SimpleNamespace(confidence=0.99),
    )
    monkeypatch.setattr(
        twin_service.decision_engine,
        "_evaluate_conditions",
        lambda form, _definition: (form["eligible"], [], []),
    )
    monkeypatch.setattr(twin_service.decision_engine, "_get_anomaly_flags", lambda *_: [])
    monkeypatch.setattr(
        twin_service.decision_engine,
        "_validated_thresholds",
        lambda _definition: {"auto_approve": 0.98, "ask_more": 0.70},
    )

    result = twin_service.simulate_rule_change(
        tenant_id=tenant_id, draft_rule_id=draft.id, limit=5
    )

    assert result["total"] == 2
    assert result["changed"] == 2
    assert result["results"] == [
        {"case_id": cases[0].id, "old_outcome": "approved", "new_outcome": "human_review"},
        {"case_id": cases[1].id, "old_outcome": "human_review", "new_outcome": "approved"},
    ]
    assert result["summary"] == {
        "more_approvals": 1,
        "fewer_approvals": 1,
        "more_human_reviews": 1,
        "fewer_human_reviews": 1,
    }
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_simulation_returns_not_found_for_rule_outside_tenant(monkeypatch):
    query = MagicMock()
    query.filter_by.return_value.first.return_value = None
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(db, "session", session)

    with pytest.raises(TwinError) as exc:
        twin_service.simulate_rule_change(
            tenant_id=str(uuid4()), draft_rule_id=str(uuid4())
        )

    assert exc.value.code == "NOT_FOUND"
    assert session.add.call_count == 0
    assert session.commit.call_count == 0


def test_missing_form_fields_simulate_as_needs_more_proof(monkeypatch):
    case = _case(str(uuid4()), eligible=True)
    case.missing_fields = ["monthly_income"]
    monkeypatch.setattr(
        twin_service.identity_match,
        "match_identity",
        MagicMock(side_effect=AssertionError("must not run identity matching")),
    )

    assert twin_service._evaluate_case(case, {}) == "needs_more_proof"


def test_evaluation_errors_fail_safe_to_human_review(monkeypatch):
    tenant_id = str(uuid4())
    draft = _rule(tenant_id)
    case = _case(tenant_id, eligible=True)
    rule_query, case_query, decision_query = MagicMock(), MagicMock(), MagicMock()
    rule_query.filter_by.return_value.first.return_value = draft
    case_query.filter.return_value.order_by.return_value.all.return_value = [case]
    decision_query.filter_by.return_value.order_by.return_value.first.return_value = None
    session = MagicMock()
    session.query.side_effect = [rule_query, case_query, decision_query]
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(
        twin_service, "_evaluate_case", MagicMock(side_effect=RuntimeError("failed"))
    )

    result = twin_service.simulate_rule_change(tenant_id=tenant_id, draft_rule_id=draft.id)

    assert result["results"][0]["new_outcome"] == "human_review"
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_twin_endpoint_requires_admin_and_valid_request(monkeypatch):
    from flask import Flask

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(twin_bp, url_prefix="/api/v1/twin")
    user = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role="admin", is_active=True)
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": user.id})
    session = MagicMock()
    session.get.return_value = user
    monkeypatch.setattr(db, "session", session)
    simulate = MagicMock(return_value={"total": 0, "changed": 0, "results": [], "summary": {}})
    monkeypatch.setattr(twin_api, "simulate_rule_change", simulate)
    draft_id = str(uuid4())

    response = flask_app.test_client().post(
        "/api/v1/twin/simulate",
        json={"draft_rule_id": draft_id, "limit": 10},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.json["error"] is None
    simulate.assert_called_once_with(tenant_id=user.tenant_id, draft_rule_id=draft_id, limit=10)


def test_twin_endpoint_rejects_non_admin(monkeypatch):
    from flask import Flask

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(twin_bp, url_prefix="/api/v1/twin")
    user = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role="officer", is_active=True)
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": user.id})
    session = MagicMock()
    session.get.return_value = user
    monkeypatch.setattr(db, "session", session)

    response = flask_app.test_client().post(
        "/api/v1/twin/simulate",
        json={"draft_rule_id": str(uuid4())},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403
    assert response.json["error"]["code"] == "FORBIDDEN_ROLE"


def test_twin_endpoint_rejects_non_positive_limit(monkeypatch):
    from flask import Flask

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(twin_bp, url_prefix="/api/v1/twin")
    user = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role="admin", is_active=True)
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": user.id})
    session = MagicMock()
    session.get.return_value = user
    monkeypatch.setattr(db, "session", session)
    simulate = MagicMock()
    monkeypatch.setattr(twin_api, "simulate_rule_change", simulate)

    response = flask_app.test_client().post(
        "/api/v1/twin/simulate",
        json={"draft_rule_id": str(uuid4()), "limit": 0},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 400
    assert response.json["error"]["code"] == "VALIDATION_ERROR"
    simulate.assert_not_called()
