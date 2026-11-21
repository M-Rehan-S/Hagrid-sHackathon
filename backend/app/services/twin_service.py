"""Read-only replay of submitted relief cases against a draft rule version."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select

from app.extensions import db
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.decision import Decision
from app.models.document import Document
from app.models.enums import CaseStatus, CaseType, DecisionOutcome, RuleStatus
from app.models.rule import Rule
from app.services import decision_engine, identity_match


class TwinError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _value(value: Any) -> str | None:
    return getattr(value, "value", value)


def _old_outcome(case: Case, latest: Decision | None) -> str | None:
    if latest is not None:
        return str(_value(latest.outcome))
    return {
        CaseStatus.approved.value: DecisionOutcome.approved.value,
        CaseStatus.rejected.value: DecisionOutcome.rejected.value,
        CaseStatus.needs_info.value: DecisionOutcome.needs_more_proof.value,
        CaseStatus.in_review.value: DecisionOutcome.human_review.value,
    }.get(str(_value(case.status)))


def _evaluate_case(case: Case, definition: dict[str, Any]) -> str:
    """Evaluate one row with decision-engine logic but without persistence."""
    if case.missing_fields:
        return DecisionOutcome.needs_more_proof.value

    form = dict(case.form_data or {})
    identity = identity_match.match_identity(form)
    documents = db.session.query(Document).filter_by(case_id=case.id).all()
    required_documents = list(definition.get("required_documents", []))
    present_kinds = {document.kind for document in documents}
    missing_documents = [kind for kind in required_documents if kind not in present_kinds]
    if missing_documents:
        document_confidence = 0.0
    else:
        scores = [
            float(document.quality_score) if document.quality_score is not None else 1.0
            for document in documents if document.kind in required_documents
        ]
        document_confidence = min(scores, default=1.0)
    if not 0.0 <= document_confidence <= 1.0:
        raise ValueError("Document quality score must be between 0 and 1")

    completeness_confidence = 0.6 if form.get("invalid_fields") else 1.0
    eligible, _failed, _evaluated = decision_engine._evaluate_conditions(form, definition)
    anomaly_flags = decision_engine._get_anomaly_flags(case, form, identity, definition)
    thresholds = decision_engine._validated_thresholds(definition)
    confidence = min(float(identity.confidence), document_confidence, completeness_confidence)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("Decision confidence must be between 0 and 1")

    if anomaly_flags or not eligible:
        return DecisionOutcome.human_review.value
    if missing_documents:
        return DecisionOutcome.needs_more_proof.value
    if confidence >= thresholds["auto_approve"]:
        return DecisionOutcome.approved.value
    if confidence >= thresholds["ask_more"]:
        return DecisionOutcome.needs_more_proof.value
    return DecisionOutcome.human_review.value


def simulate_rule_change(
    *, tenant_id: str, draft_rule_id: str, limit: int | None = None
) -> dict[str, Any]:
    draft = db.session.query(Rule).filter_by(
        id=draft_rule_id, tenant_id=tenant_id, status=RuleStatus.draft
    ).first()
    if draft is None:
        raise TwinError("NOT_FOUND", "Draft rule was not found.", 404)
    if draft.rule_key != "relief_eligibility":
        raise TwinError("VALIDATION_ERROR", "Only relief eligibility rules can be simulated.", 400)

    submitted_case_ids = (
        select(CaseEvent.case_id)
        .where(CaseEvent.event_type == "submitted")
        .distinct()
    )
    query = (
        db.session.query(Case)
        .filter(
            Case.tenant_id == tenant_id,
            Case.case_type == CaseType.relief_claim,
            Case.id.in_(submitted_case_ids),
        )
        .order_by(desc(Case.created_at), desc(Case.id))
    )
    if limit is not None:
        query = query.limit(limit)
    cases = query.all()

    results: list[dict[str, Any]] = []
    for case in cases:
        latest = (
            db.session.query(Decision)
            .filter_by(case_id=case.id)
            .order_by(desc(Decision.created_at), desc(Decision.id))
            .first()
        )
        old_outcome = _old_outcome(case, latest)
        try:
            new_outcome = _evaluate_case(case, draft.definition)
        except Exception:
            # Match the decision engine's fail-safe behavior without persisting.
            new_outcome = DecisionOutcome.human_review.value
        results.append({
            "case_id": str(case.id),
            "old_outcome": old_outcome,
            "new_outcome": new_outcome,
        })

    more_approvals = sum(
        row["new_outcome"] == DecisionOutcome.approved.value
        and row["old_outcome"] != DecisionOutcome.approved.value
        for row in results
    )
    fewer_approvals = sum(
        row["old_outcome"] == DecisionOutcome.approved.value
        and row["new_outcome"] != DecisionOutcome.approved.value
        for row in results
    )
    more_human_reviews = sum(
        row["new_outcome"] == DecisionOutcome.human_review.value
        and row["old_outcome"] != DecisionOutcome.human_review.value
        for row in results
    )
    fewer_human_reviews = sum(
        row["old_outcome"] == DecisionOutcome.human_review.value
        and row["new_outcome"] != DecisionOutcome.human_review.value
        for row in results
    )
    return {
        "total": len(results),
        "changed": sum(row["old_outcome"] != row["new_outcome"] for row in results),
        "results": results,
        "summary": {
            "more_approvals": more_approvals,
            "fewer_approvals": fewer_approvals,
            "more_human_reviews": more_human_reviews,
            "fewer_human_reviews": fewer_human_reviews,
        },
    }
