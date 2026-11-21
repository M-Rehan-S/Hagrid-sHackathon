from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import decision_engine


class _Decision:
    def __init__(self, **values):
        self.id = "decision-1"
        for key, value in values.items():
            setattr(self, key, value)


class _CaseEvent:
    def __init__(self, **values):
        self.__dict__.update(values)


class _MockPayment:
    def __init__(self, **values):
        self.__dict__.update(values)


class _Column:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return (self.name, "==", other)

    def __ne__(self, other):
        return (self.name, "!=", other)

    def __ge__(self, other):
        return (self.name, ">=", other)

    def notin_(self, values):
        return (self.name, "notin", tuple(values))


class _QueryCase:
    id = _Column("cases.id")
    tenant_id = _Column("cases.tenant_id")
    case_type = _Column("cases.case_type")
    citizen_id = _Column("cases.citizen_id")
    status = _Column("cases.status")


class _QueryCitizen:
    id = _Column("citizens.id")
    cnic = _Column("citizens.cnic")


class _QueryCaseEvent:
    actor_id = _Column("case_events.actor_id")
    event_type = _Column("case_events.event_type")
    case_id = _Column("case_events.case_id")
    created_at = _Column("case_events.created_at")


def _install_models_and_db(monkeypatch):
    db = SimpleNamespace(session=MagicMock())
    ext = types.ModuleType("app.extensions")
    ext.db = db
    monkeypatch.setitem(sys.modules, "app.extensions", ext)

    models = types.ModuleType("app.models")
    models.__path__ = []
    monkeypatch.setitem(sys.modules, "app.models", models)
    for module_name, class_name, model in [
        ("case_event", "CaseEvent", _CaseEvent),
        ("decision", "Decision", _Decision),
        ("mock_payment", "MockPayment", _MockPayment),
    ]:
        module = types.ModuleType(f"app.models.{module_name}")
        setattr(module, class_name, model)
        monkeypatch.setitem(sys.modules, f"app.models.{module_name}", module)

    audit_log = MagicMock()
    audit_module = types.ModuleType("app.services.audit")
    audit_module.audit = SimpleNamespace(log=audit_log)
    monkeypatch.setitem(sys.modules, "app.services.audit", audit_module)
    return db, audit_log


def _condition(field="is_widow", op="eq", value=True, **extra):
    return {
        "id": "condition-1",
        "field": field,
        "op": op,
        "value": value,
        "reason_en": "The claim is for widows.",
        "reason_ur": "یہ دعویٰ بیواؤں کے لیے ہے۔",
        **extra,
    }


def _rule(*, conditions=None, anomaly=None, thresholds=None):
    return SimpleNamespace(
        id="rule-1",
        version=1,
        rule_key="relief_eligibility",
        definition={
            "match": "all",
            "conditions": conditions if conditions is not None else [_condition()],
            "required_documents": ["cnic_photo"],
            "amount": 25000,
            "thresholds": thresholds or {"auto_approve": 0.98, "ask_more": 0.70},
            "anomaly": anomaly or {
                "duplicate_open_claim": {"enabled": True},
                "helper_burst": {
                    "enabled": True,
                    "max_per_window": 10,
                    "window_minutes": 10,
                    "max_per_day": 60,
                },
                "deceased_match": {"enabled": True},
            },
        },
    )


def _case(*, missing_fields=None, form_data=None):
    return SimpleNamespace(
        id="case-1",
        tenant_id="tenant-1",
        citizen_id="citizen-1",
        created_by="citizen-user-1",
        case_type="relief_claim",
        status="submitted",
        route=None,
        confidence=None,
        rule_version_id=None,
        missing_fields=missing_fields or [],
        form_data=form_data or {
            "full_name": "Fatima Bibi",
            "cnic": "4210112345671",
            "is_widow": True,
        },
    )


def _identity(*, confidence=1.0, is_deceased=False, status="exact"):
    return SimpleNamespace(
        confidence=confidence,
        is_deceased=is_deceased,
        status=status,
        candidates=[],
        reasons=[],
    )


def _prepare(
    monkeypatch, *, case=None, rule=None, identity=None, documents=None,
    flags=None, use_real_anomaly_evaluator=False,
):
    db, audit_log = _install_models_and_db(monkeypatch)
    case = case or _case()
    rule = rule or _rule()
    identity = identity or _identity()
    documents = documents if documents is not None else [
        SimpleNamespace(kind="cnic_photo", quality_score=1.0)
    ]
    monkeypatch.setattr(decision_engine, "_get_case", lambda case_id: case)
    monkeypatch.setattr(decision_engine, "_get_documents", lambda case_id: documents)
    if not use_real_anomaly_evaluator:
        monkeypatch.setattr(decision_engine, "_get_anomaly_flags", lambda *args: flags or [])
    monkeypatch.setattr(
        "app.services.rule_service.get_active_rule", lambda tenant_id, rule_key: rule
    )
    monkeypatch.setattr(
        "app.services.identity_match.match_identity", lambda form: identity
    )
    return db, audit_log, case, rule, identity


def test_auto_approves_at_threshold_persists_trace_audit_and_mock_payment(monkeypatch):
    db, audit_log, case, rule, _ = _prepare(monkeypatch)

    result = decision_engine.decide("case-1")

    assert result.outcome == "approved"
    assert result.route == "auto_approve"
    assert result.confidence == 1.0
    assert case.status == "approved"
    assert case.rule_version_id == "rule-1"
    decision = next(arg for arg in db.session.add.call_args_list if isinstance(arg.args[0], _Decision)).args[0]
    assert decision.trace["rule"] == {
        "rule_key": "relief_eligibility", "rule_version_id": "rule-1", "version": 1
    }
    assert decision.trace["eligibility"]["eligible"] is True
    assert decision.trace["confidences"]["final"] == 1.0
    payment = next(arg.args[0] for arg in db.session.add.call_args_list if isinstance(arg.args[0], _MockPayment))
    assert payment.case_id == case.id
    assert payment.amount == rule.definition["amount"]
    assert payment.reference.startswith("MOCK-")
    db.session.commit.assert_called_once_with()
    audit_log.assert_called_once()
    assert audit_log.call_args.kwargs["action"] == "ai.decision"
    assert audit_log.call_args.kwargs["tenant_id"] == "tenant-1"


@pytest.mark.parametrize(
    ("confidence", "expected_route", "expected_outcome"),
    [
        (0.98, "auto_approve", "approved"),
        (0.70, "ask_more", "needs_more_proof"),
        (0.85, "ask_more", "needs_more_proof"),
        (0.69, "human_review", "human_review"),
    ],
)
def test_confidence_threshold_routes(monkeypatch, confidence, expected_route, expected_outcome):
    _db, _audit, case, _rule_obj, _identity_obj = _prepare(
        monkeypatch, identity=_identity(confidence=confidence)
    )

    result = decision_engine.decide("case-1")

    assert result.route == expected_route
    assert result.outcome == expected_outcome
    expected_status = {
        "auto_approve": "approved",
        "ask_more": "needs_info",
        "human_review": "in_review",
    }[expected_route]
    assert case.status == expected_status


def test_eligibility_failure_goes_to_human_review_never_rejected(monkeypatch):
    _db, _audit, case, _rule_obj, _identity_obj = _prepare(
        monkeypatch,
        case=_case(form_data={"is_widow": False, "cnic": "4210112345671"}),
    )

    result = decision_engine.decide("case-1")

    assert result.outcome == "human_review"
    assert result.route == "human_review"
    assert case.status == "in_review"
    assert "not meet" in result.reason_en


def test_missing_required_document_requests_more_proof(monkeypatch):
    _db, _audit, case, _rule_obj, _identity_obj = _prepare(monkeypatch, documents=[])

    result = decision_engine.decide("case-1")

    assert result.outcome == "needs_more_proof"
    assert result.route == "ask_more"
    assert "cnic_photo" in result.reason_en
    assert case.status == "needs_info"


def test_missing_form_fields_updates_case_without_decision(monkeypatch):
    db, audit_log, case, _rule_obj, _identity_obj = _prepare(
        monkeypatch, case=_case(missing_fields=["monthly_income", "district"])
    )

    result = decision_engine.decide("case-1")

    assert result == ["monthly_income", "district"]
    assert case.status == "needs_info"
    db.session.add.assert_not_called()
    audit_log.assert_not_called()
    db.session.commit.assert_called_once_with()


@pytest.mark.parametrize("flag", ["duplicate_open_claim", "helper_burst", "deceased_match"])
def test_each_anomaly_flag_forces_human_review(monkeypatch, flag):
    _db, _audit, case, _rule_obj, _identity_obj = _prepare(
        monkeypatch, flags=[flag]
    )

    result = decision_engine.decide("case-1")

    assert result.route == "human_review"
    assert result.outcome == "human_review"
    assert result.trace["anomaly_flags"] == [flag]
    assert case.status == "in_review"


def test_deceased_identity_sets_flag_from_rule_enabled_configuration(monkeypatch):
    anomaly = {
        "duplicate_open_claim": {"enabled": False},
        "helper_burst": {"enabled": False},
        "deceased_match": {"enabled": True},
    }
    _db, _audit, _case_obj, _rule_obj, _identity_obj = _prepare(
        monkeypatch,
        identity=_identity(is_deceased=True),
        rule=_rule(anomaly=anomaly),
        use_real_anomaly_evaluator=True,
    )
    result = decision_engine.decide("case-1")

    assert result.trace["anomaly_flags"] == ["deceased_match"]
    assert result.outcome == "human_review"


def test_duplicate_open_claim_matches_cnic_and_excludes_current_case(monkeypatch):
    db = SimpleNamespace(session=MagicMock())
    query = db.session.query.return_value
    query.join.return_value.filter.return_value.count.return_value = 1
    ext = types.ModuleType("app.extensions")
    ext.db = db
    monkeypatch.setitem(sys.modules, "app.extensions", ext)
    models = types.ModuleType("app.models")
    models.__path__ = []
    monkeypatch.setitem(sys.modules, "app.models", models)
    case_model = types.ModuleType("app.models.case")
    case_model.Case = _QueryCase
    citizen_model = types.ModuleType("app.models.citizen")
    citizen_model.Citizen = _QueryCitizen
    monkeypatch.setitem(sys.modules, "app.models.case", case_model)
    monkeypatch.setitem(sys.modules, "app.models.citizen", citizen_model)
    current = SimpleNamespace(id="current", tenant_id="tenant-1")

    assert decision_engine._has_duplicate_open_claim(current, "4210112345671") is True

    query.join.assert_called_once_with(
        _QueryCitizen, _QueryCase.citizen_id == _QueryCitizen.id
    )
    query.join.return_value.filter.assert_called_once_with(
        ("cases.tenant_id", "==", "tenant-1"),
        ("cases.case_type", "==", "relief_claim"),
        ("cases.id", "!=", "current"),
        ("citizens.cnic", "==", "4210112345671"),
        ("cases.status", "notin", ("rejected", "closed")),
    )


@pytest.mark.parametrize(
    ("recent_count", "daily_count", "expected"),
    [(9, 59, False), (10, 59, True), (9, 60, True)],
)
def test_helper_burst_uses_strict_greater_than_rule_thresholds(
    monkeypatch, recent_count, daily_count, expected
):
    db = SimpleNamespace(session=MagicMock())
    user_query, event_query = MagicMock(), MagicMock()
    db.session.query.side_effect = [user_query, event_query]
    user_query.filter_by.return_value.first.return_value = SimpleNamespace(id="helper-1")
    base_event_query = event_query.filter.return_value
    recent_query, daily_query = MagicMock(), MagicMock()
    base_event_query.filter.side_effect = [recent_query, daily_query]
    recent_query.count.return_value = recent_count
    daily_query.count.return_value = daily_count
    ext = types.ModuleType("app.extensions")
    ext.db = db
    monkeypatch.setitem(sys.modules, "app.extensions", ext)
    models = types.ModuleType("app.models")
    models.__path__ = []
    monkeypatch.setitem(sys.modules, "app.models", models)
    event_model = types.ModuleType("app.models.case_event")
    event_model.CaseEvent = _QueryCaseEvent
    user_model = types.ModuleType("app.models.user")
    user_model.User = type("User", (), {})
    monkeypatch.setitem(sys.modules, "app.models.case_event", event_model)
    monkeypatch.setitem(sys.modules, "app.models.user", user_model)
    current = SimpleNamespace(id="current", created_by="helper-1")
    thresholds = {"max_per_window": 10, "window_minutes": 10, "max_per_day": 60}

    # Current submission is included: limits fire only once the count exceeds N.
    assert decision_engine._has_helper_burst(current, thresholds) is expected
    assert user_query.filter_by.call_args.kwargs == {"id": "helper-1", "role": "helper"}
    assert event_query.filter.call_args.args == (
        ("case_events.actor_id", "==", "helper-1"),
        ("case_events.event_type", "==", "submitted"),
        ("case_events.case_id", "!=", "current"),
    )


def test_identity_or_rule_failure_routes_to_human_review(monkeypatch):
    _db, _audit, case, _rule_obj, _identity_obj = _prepare(monkeypatch)
    monkeypatch.setattr(
        "app.services.identity_match.match_identity",
        MagicMock(side_effect=RuntimeError("registry unavailable")),
    )

    result = decision_engine.decide("case-1")

    assert result.route == "human_review"
    assert result.outcome == "human_review"
    assert result.trace["failure"]["type"] == "RuntimeError"
    assert "registry unavailable" not in str(result.trace)
    assert case.status == "in_review"


@pytest.mark.parametrize(
    ("actual", "op", "expected", "answer"),
    [
        (3, "eq", 3, True), (3, "ne", 4, True), (2, "lt", 3, True),
        (3, "lte", 3, True), (4, "gt", 3, True), (3, "gte", 3, True),
        ("a", "in", ["a", "b"], True), ("c", "not_in", ["a", "b"], True),
        (None, "gte", 0, False),
    ],
)
def test_rule_condition_operators(actual, op, expected, answer):
    assert decision_engine._compare(actual, op, expected) is answer


def test_invalid_rule_operator_fails_to_human_review(monkeypatch):
    _db, _audit, case, _rule_obj, _identity_obj = _prepare(
        monkeypatch, rule=_rule(conditions=[_condition(op="contains")])
    )

    result = decision_engine.decide("case-1")

    assert result.outcome == "human_review"
    assert result.trace["failure"]["type"] == "ValueError"
    assert case.status == "in_review"


def test_unknown_case_raises_lookup_error(monkeypatch):
    _install_models_and_db(monkeypatch)
    monkeypatch.setattr(decision_engine, "_get_case", lambda case_id: None)

    with pytest.raises(LookupError):
        decision_engine.decide("missing-case")
