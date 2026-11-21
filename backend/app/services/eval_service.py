"""Read evaluation snapshots and tenant-scoped live decision counters."""

from __future__ import annotations

from bisect import bisect_right
from datetime import timezone

from sqlalchemy import desc

from app.extensions import db
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.decision import Decision
from app.models.enums import DecisionActor, DecisionOutcome, RouteType, UserRole
from app.models.eval_run import EvalRun
from app.models.user import User


class EvalError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _value(value):
    return getattr(value, "value", value)


def _iso(value):
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def evaluation_summary(actor: User) -> dict:
    role = str(getattr(actor.role, "value", actor.role))
    if role not in (UserRole.officer.value, UserRole.admin.value, UserRole.auditor.value):
        raise EvalError("FORBIDDEN_ROLE", "Your role cannot view evaluation summaries.", 403)

    runs = (
        db.session.query(EvalRun)
        .order_by(EvalRun.name.asc(), desc(EvalRun.created_at), desc(EvalRun.id))
        .all()
    )
    latest_by_name = {}
    for run in runs:
        if run.name not in latest_by_name:
            latest_by_name[run.name] = {
                "id": str(run.id), "name": run.name,
                "metrics": run.metrics, "created_at": _iso(run.created_at),
            }

    tenant_id = str(actor.tenant_id)
    cases = db.session.query(Case).filter_by(tenant_id=tenant_id).all()
    case_ids = {str(case.id) for case in cases}
    cases_by_route = {
        RouteType.auto_approve.value: 0,
        RouteType.ask_more.value: 0,
        RouteType.human_review.value: 0,
        "unrouted": 0,
    }
    for case in cases:
        route = _value(case.route)
        cases_by_route[route if route in cases_by_route else "unrouted"] += 1

    decisions = (
        db.session.query(Decision)
        .join(Case, Decision.case_id == Case.id)
        .filter(Case.tenant_id == tenant_id)
        .all()
    )
    ai_decisions = [row for row in decisions if _value(row.actor_type) == DecisionActor.ai.value]
    auto_approved_case_ids = {
        str(row.case_id) for row in ai_decisions
        if _value(row.outcome) == DecisionOutcome.approved.value
    }
    handoff_case_ids = {
        str(row.case_id) for row in ai_decisions
        if _value(row.route) == RouteType.human_review.value
        or _value(row.outcome) == DecisionOutcome.human_review.value
    }

    submitted_events = (
        db.session.query(CaseEvent)
        .join(Case, CaseEvent.case_id == Case.id)
        .filter(Case.tenant_id == tenant_id, CaseEvent.event_type == "submitted")
        .all()
    )
    submitted_by_case = {}
    for event in submitted_events:
        submitted_by_case.setdefault(str(event.case_id), []).append(event.created_at)
    for times in submitted_by_case.values():
        times.sort()

    latencies_ms = []
    for decision in ai_decisions:
        submissions = submitted_by_case.get(str(decision.case_id), [])
        if not submissions:
            continue
        position = bisect_right(submissions, decision.created_at) - 1
        if position < 0:
            continue
        latency = (decision.created_at - submissions[position]).total_seconds() * 1000
        if latency >= 0:
            latencies_ms.append(latency)

    return {
        "evaluation_runs": list(latest_by_name.values()),
        "live": {
            "cases_by_route": cases_by_route,
            "auto_approved_count": len(auto_approved_case_ids),
            "human_handoffs": len(handoff_case_ids),
            "avg_decision_latency_ms": (
                round(sum(latencies_ms) / len(latencies_ms), 2) if latencies_ms else None
            ),
        },
    }
