from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.enums import DecisionActor, DecisionOutcome, RouteType
from app.services.eval_service import EvalError, evaluation_summary


def _user(role="admin"):
    return SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), role=role)


def _query(rows):
    query = MagicMock()
    query.filter_by.return_value = query
    query.join.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = rows
    return query


def test_eval_summary_selects_latest_runs_and_computes_tenant_counters(monkeypatch):
    from app.models.case import Case
    from app.models.case_event import CaseEvent
    from app.models.decision import Decision
    from app.models.eval_run import EvalRun

    actor = _user("officer")
    now = datetime.now(timezone.utc)
    case1, case2, case3 = [str(uuid4()) for _ in range(3)]
    runs = [
        SimpleNamespace(id="new", name="classifier", metrics={"precision": 0.9}, created_at=now),
        SimpleNamespace(id="old", name="classifier", metrics={"precision": 0.8}, created_at=now - timedelta(days=1)),
        SimpleNamespace(id="router", name="router", metrics={"recall": 0.7}, created_at=now),
    ]
    cases = [
        SimpleNamespace(id=case1, route=RouteType.auto_approve),
        SimpleNamespace(id=case2, route=RouteType.human_review),
        SimpleNamespace(id=case3, route=None),
    ]
    decisions = [
        SimpleNamespace(case_id=case1, actor_type=DecisionActor.ai, outcome=DecisionOutcome.approved,
                        route=RouteType.auto_approve, created_at=now),
        SimpleNamespace(case_id=case2, actor_type=DecisionActor.ai, outcome=DecisionOutcome.human_review,
                        route=RouteType.human_review, created_at=now),
        SimpleNamespace(case_id=case1, actor_type=DecisionActor.officer, outcome=DecisionOutcome.approved,
                        route=None, created_at=now),
    ]
    events = [
        SimpleNamespace(case_id=case1, event_type="submitted", created_at=now - timedelta(seconds=10)),
        SimpleNamespace(case_id=case1, event_type="submitted", created_at=now - timedelta(seconds=5)),
        SimpleNamespace(case_id=case2, event_type="submitted", created_at=now - timedelta(seconds=20)),
    ]
    session = MagicMock()
    session.query.side_effect = lambda model: _query({
        EvalRun: runs, Case: cases, Decision: decisions, CaseEvent: events,
    }[model])
    monkeypatch.setattr(db, "session", session)

    result = evaluation_summary(actor)

    assert [row["id"] for row in result["evaluation_runs"]] == ["new", "router"]
    assert result["live"]["cases_by_route"] == {
        "auto_approve": 1, "ask_more": 0, "human_review": 1, "unrouted": 1,
    }
    assert result["live"]["auto_approved_count"] == 1
    assert result["live"]["human_handoffs"] == 1
    assert result["live"]["avg_decision_latency_ms"] == 12500.0


def test_eval_summary_returns_null_latency_without_ai_decisions(monkeypatch):
    from app.models.case import Case
    from app.models.case_event import CaseEvent
    from app.models.decision import Decision
    from app.models.eval_run import EvalRun

    session = MagicMock()
    session.query.side_effect = lambda model: _query({
        EvalRun: [], Case: [], Decision: [], CaseEvent: [],
    }[model])
    monkeypatch.setattr(db, "session", session)

    result = evaluation_summary(_user())

    assert result["live"]["avg_decision_latency_ms"] is None
    assert result["evaluation_runs"] == []


def test_eval_summary_denies_citizen_role(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(db, "session", session)

    with pytest.raises(EvalError) as exc:
        evaluation_summary(_user("citizen"))

    assert exc.value.code == "FORBIDDEN_ROLE"
    session.query.assert_not_called()
