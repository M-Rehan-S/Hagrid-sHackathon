"""Deterministic relief claim routing and decision persistence.

Implements the decision flow in PROPOSAL.md §8.5. Model imports are deferred
to keep the service importable while the shared database models are being
integrated by Person A.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4


MODEL_VERSION = "engine-v1"
RULE_KEY = "relief_eligibility"
OPEN_CASE_STATUSES = ("draft", "needs_info", "submitted", "in_review", "approved")
_ALLOWED_OPERATORS = frozenset({"eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in"})

_ANOMALY_REASONS = {
    "duplicate_open_claim": (
        "We found another claim with your ID, so an officer will check.",
        "ہمیں آپ کے شناختی کارڈ پر ایک اور دعویٰ ملا ہے، اس لیے افسر اس کی جانچ کرے گا۔",
    ),
    "helper_burst": (
        "Your helper submitted many claims in a short time, so an officer will check this claim.",
        "آپ کے مددگار نے تھوڑے وقت میں بہت سے دعوے جمع کرائے ہیں، اس لیے افسر اس دعوے کی جانچ کرے گا۔",
    ),
    "deceased_match": (
        "A record may belong to a deceased person, so an officer will check this claim.",
        "ریکارڈ کسی وفات پانے والے شخص کا ہو سکتا ہے، اس لیے افسر اس دعوے کی جانچ کرے گا۔",
    ),
}


def decide(case_id: str):
    """Evaluate and persist a decision for a case.

    If required form fields are missing, update the case to ``needs_info`` and
    return its missing field names without creating a decision. Evaluation
    failures fail safely to ``human_review``. The returned value is the
    persisted Decision model, except for the missing-field path which returns
    ``list[str]`` as specified by §8.5 step 1.
    """
    started = perf_counter()
    case = _get_case(case_id)
    if case is None:
        raise LookupError(f"Case not found: {case_id}")

    missing_fields = list(case.missing_fields or [])
    if missing_fields:
        case.status = "needs_info"
        from app.extensions import db

        db.session.commit()
        return missing_fields

    form = dict(case.form_data or {})
    trace_base: dict[str, Any] = {
        "input_snapshot": {"form_data": form, "documents": []},
        "rule": {"rule_key": RULE_KEY, "rule_version_id": None, "version": None},
        "identity_match": {"status": "none", "confidence": 0.0, "candidates": []},
        "eligibility": {"eligible": False, "failed_conditions": [], "evaluated": []},
        "anomaly_flags": [],
        "confidences": {"identity": 0.0, "documents": 1.0, "completeness": 1.0, "final": 0.0},
        "thresholds": {},
        "route": "human_review",
        "outcome": "human_review",
        "model_version": MODEL_VERSION,
        "llm_used": False,
    }

    rule = None
    try:
        from app.services import identity_match, rule_service

        rule = rule_service.get_active_rule(case.tenant_id, RULE_KEY)
        if rule is None:
            raise RuntimeError("No active relief eligibility rule")
        trace_base["rule"] = {
            "rule_key": rule.rule_key,
            "rule_version_id": str(rule.id),
            "version": rule.version,
        }

        identity = identity_match.match_identity(form)
        documents = _get_documents(case.id)
        trace_base["input_snapshot"]["documents"] = [doc.kind for doc in documents]

        required_documents = list(rule.definition.get("required_documents", []))
        present_kinds = {doc.kind for doc in documents}
        missing_documents = [kind for kind in required_documents if kind not in present_kinds]
        if missing_documents:
            document_conf = 0.0
        else:
            required_scores = [
                float(doc.quality_score) if doc.quality_score is not None else 1.0
                for doc in documents
                if doc.kind in required_documents
            ]
            document_conf = min(required_scores, default=1.0)
        if not 0.0 <= document_conf <= 1.0:
            raise ValueError("Document quality score must be between 0 and 1")

        invalid_fields = list(form.get("invalid_fields", []))
        completeness_conf = 0.6 if invalid_fields else 1.0
        eligible, failed_conditions, evaluated = _evaluate_conditions(
            form, rule.definition
        )
        anomaly_flags = _get_anomaly_flags(case, form, identity, rule.definition)
        thresholds = _validated_thresholds(rule.definition)
        confidence = min(float(identity.confidence), document_conf, completeness_conf)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Decision confidence must be between 0 and 1")

        if anomaly_flags or not eligible:
            route, outcome = "human_review", "human_review"
        elif missing_documents:
            route, outcome = "ask_more", "needs_more_proof"
        elif confidence >= thresholds["auto_approve"]:
            route, outcome = "auto_approve", "approved"
        elif confidence >= thresholds["ask_more"]:
            route, outcome = "ask_more", "needs_more_proof"
        else:
            route, outcome = "human_review", "human_review"

        reason_en, reason_ur = _build_reasons(
            route=route,
            outcome=outcome,
            rule_definition=rule.definition,
            failed_conditions=failed_conditions,
            anomaly_flags=anomaly_flags,
            missing_documents=missing_documents,
            documents=documents,
            identity=identity,
        )
        trace_base.update({
            "identity_match": _identity_trace(identity),
            "eligibility": {
                "eligible": eligible,
                "failed_conditions": failed_conditions,
                "evaluated": evaluated,
            },
            "anomaly_flags": anomaly_flags,
            "confidences": {
                "identity": float(identity.confidence),
                "documents": document_conf,
                "completeness": completeness_conf,
                "final": confidence,
            },
            "thresholds": thresholds,
            "route": route,
            "outcome": outcome,
        })
    except Exception as exc:
        # An unavailable rule, matcher, or failed evaluation cannot approve a
        # claim. Keep the error class in the auditor trace, not its message,
        # which could contain input data.
        route, outcome = "human_review", "human_review"
        confidence = float(trace_base["confidences"]["final"])
        anomaly_flags = list(trace_base["anomaly_flags"])
        reason_en = "We could not safely complete the automatic check, so an officer will review your claim."
        reason_ur = "ہم خودکار جانچ محفوظ طریقے سے مکمل نہیں کر سکے، اس لیے افسر آپ کے دعوے کا جائزہ لے گا۔"
        trace_base["failure"] = {"type": type(exc).__name__}
        trace_base["route"] = route
        trace_base["outcome"] = outcome

    trace_base["latency_ms"] = round((perf_counter() - started) * 1000)
    trace_base["created_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return _persist_decision(
        case=case,
        rule=rule,
        route=route,
        outcome=outcome,
        confidence=confidence,
        reason_en=reason_en,
        reason_ur=reason_ur,
        trace=trace_base,
        rule_definition=rule.definition if rule is not None else {},
    )


def _get_case(case_id: str):
    from app.extensions import db
    from app.models.case import Case

    return db.session.query(Case).filter_by(id=case_id).first()


def _get_documents(case_id: str) -> list[Any]:
    from app.extensions import db
    from app.models.document import Document

    return db.session.query(Document).filter_by(case_id=case_id).all()


def _evaluate_conditions(form: dict[str, Any], definition: dict[str, Any]):
    """Return eligibility, failed condition IDs, and per-condition results."""
    match_mode = definition.get("match", "all")
    if match_mode != "all":
        raise ValueError("Unsupported rule match mode")

    results: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for condition in definition.get("conditions", []):
        condition_id = str(condition["id"])
        field = condition["field"]
        op = condition["op"]
        if op not in _ALLOWED_OPERATORS:
            raise ValueError(f"Unsupported condition operator: {op}")
        actual = form.get(field)
        expected = condition["value"]
        result = _compare(actual, op, expected)
        results.append({"id": condition_id, "result": result})
        if not result:
            failed.append({
                "id": condition_id,
                "reason_en": condition.get("reason_en", ""),
                "reason_ur": condition.get("reason_ur", ""),
            })

    outcomes = [item["result"] for item in results]
    eligible = all(outcomes)
    return eligible, failed, results


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        return actual in expected
    if op == "not_in":
        return actual not in expected
    # Missing values do not satisfy ordered numeric comparisons.
    if actual is None:
        return False
    if op == "lt":
        return actual < expected
    if op == "lte":
        return actual <= expected
    if op == "gt":
        return actual > expected
    if op == "gte":
        return actual >= expected
    raise ValueError(f"Unsupported condition operator: {op}")


def _validated_thresholds(definition: dict[str, Any]) -> dict[str, float]:
    thresholds = definition["thresholds"]
    auto_approve = float(thresholds["auto_approve"])
    ask_more = float(thresholds["ask_more"])
    if not (0.0 <= ask_more <= auto_approve <= 1.0):
        raise ValueError("Rule thresholds must satisfy 0 <= ask_more <= auto_approve <= 1")
    return {"auto_approve": auto_approve, "ask_more": ask_more}


def _get_anomaly_flags(case: Any, form: dict[str, Any], identity: Any, definition: dict[str, Any]) -> list[str]:
    anomaly = definition["anomaly"]
    flags: list[str] = []
    if anomaly["duplicate_open_claim"].get("enabled"):
        cnic = _normalize_cnic(form.get("cnic"))
        if cnic and _has_duplicate_open_claim(case, cnic):
            flags.append("duplicate_open_claim")
    if anomaly["helper_burst"].get("enabled") and _has_helper_burst(
        case, anomaly["helper_burst"]
    ):
        flags.append("helper_burst")
    if anomaly["deceased_match"].get("enabled") and identity.is_deceased:
        flags.append("deceased_match")
    return flags


def _normalize_cnic(value: Any) -> str | None:
    if value is None:
        return None
    normalized = "".join(ch for ch in str(value) if ch.isdigit())
    return normalized or None


def _has_duplicate_open_claim(case: Any, cnic: str) -> bool:
    from app.extensions import db
    from app.models.case import Case
    from app.models.citizen import Citizen

    return (
        db.session.query(Case)
        .join(Citizen, Case.citizen_id == Citizen.id)
        .filter(
            Case.tenant_id == case.tenant_id,
            Case.case_type == "relief_claim",
            Case.id != case.id,
            Citizen.cnic == cnic,
            Case.status.notin_(("rejected", "closed")),
        )
        .count()
        > 0
    )


def _has_helper_burst(case: Any, config: dict[str, Any]) -> bool:
    from app.extensions import db
    from app.models.case_event import CaseEvent
    from app.models.user import User

    helper = db.session.query(User).filter_by(id=case.created_by, role="helper").first()
    if helper is None:
        return False

    max_per_window = int(config["max_per_window"])
    window_minutes = int(config["window_minutes"])
    max_per_day = int(config["max_per_day"])
    if max_per_window < 0 or window_minutes <= 0 or max_per_day < 0:
        raise ValueError("Helper burst thresholds must be non-negative and window_minutes positive")

    now = datetime.now(timezone.utc)
    query = db.session.query(CaseEvent).filter(
        CaseEvent.actor_id == helper.id,
        CaseEvent.event_type == "submitted",
        CaseEvent.case_id != case.id,
    )
    recent_count = query.filter(
        CaseEvent.created_at >= now - timedelta(minutes=window_minutes)
    ).count() + 1
    daily_count = query.filter(
        CaseEvent.created_at >= now - timedelta(hours=24)
    ).count() + 1
    return recent_count > max_per_window or daily_count > max_per_day


def _identity_trace(identity: Any) -> dict[str, Any]:
    return {
        "status": identity.status,
        "confidence": float(identity.confidence),
        "candidates": [
            {"record_id": candidate.record_id, "name": candidate.name, "score": candidate.score}
            for candidate in identity.candidates
        ],
    }


def _build_reasons(
    *,
    route: str,
    outcome: str,
    rule_definition: dict[str, Any],
    failed_conditions: list[dict[str, str]],
    anomaly_flags: list[str],
    missing_documents: list[str],
    documents: list[Any],
    identity: Any,
) -> tuple[str, str]:
    if anomaly_flags:
        return _ANOMALY_REASONS[anomaly_flags[0]]
    if failed_conditions:
        return (
            "An officer will review this claim because it does not meet every eligibility condition. "
            + " ".join(item["reason_en"] for item in failed_conditions if item["reason_en"]),
            "افسر اس دعوے کا جائزہ لے گا کیونکہ یہ اہلیت کی تمام شرائط پوری نہیں کرتا۔ "
            + " ".join(item["reason_ur"] for item in failed_conditions if item["reason_ur"]),
        )
    if outcome == "needs_more_proof":
        proof_kinds = list(missing_documents)
        if not proof_kinds:
            proof_kinds = [
                doc.kind for doc in documents
                if doc.quality_score is not None and float(doc.quality_score) < 1.0
            ]
        if proof_kinds:
            proof_list = ", ".join(proof_kinds)
            return (
                f"Please provide a clearer or missing proof: {proof_list}.",
                f"براہِ کرم واضح یا غائب ثبوت فراہم کریں: {proof_list}۔",
            )
        return (
            "Please provide identity proof so we can verify the record.",
            "ریکارڈ کی تصدیق کے لیے براہِ کرم شناختی ثبوت فراہم کریں۔",
        )
    if route == "auto_approve":
        return (
            "Your claim meets the current eligibility checks and has been approved.",
            "آپ کا دعویٰ موجودہ اہلیت کی شرائط پر پورا اترتا ہے اور منظور ہو گیا ہے۔",
        )
    return (
        "We are not sure this is the same person, so an officer will check it.",
        "ہمیں یقین نہیں کہ یہ وہی شخص ہے، اس لیے ایک افسر اس کی جانچ کرے گا۔",
    )


def _persist_decision(
    *,
    case: Any,
    rule: Any,
    route: str,
    outcome: str,
    confidence: float,
    reason_en: str,
    reason_ur: str,
    trace: dict[str, Any],
    rule_definition: dict[str, Any],
):
    from app.extensions import db
    from app.models.case_event import CaseEvent
    from app.models.decision import Decision
    from app.services.audit import audit

    decision = Decision(
        case_id=case.id,
        actor_type="ai",
        actor_id=None,
        route=route,
        outcome=outcome,
        confidence=confidence,
        rule_version_id=rule.id if rule is not None else None,
        model_version=MODEL_VERSION,
        reason_en=reason_en,
        reason_ur=reason_ur,
        trace=trace,
    )
    case.status = {
        "approved": "approved",
        "needs_more_proof": "needs_info",
        "human_review": "in_review",
    }[outcome]
    case.route = route
    case.confidence = confidence
    case.rule_version_id = rule.id if rule is not None else None
    db.session.add(decision)
    db.session.add(CaseEvent(
        case_id=case.id,
        actor_id=None,
        event_type="decision",
        note=reason_en,
    ))
    db.session.flush()

    if outcome == "approved":
        from app.models.mock_payment import MockPayment

        payment = MockPayment(
            case_id=case.id,
            amount=rule_definition["amount"],
            reference=f"MOCK-{uuid4()}",
        )
        db.session.add(payment)

    audit.log(
        actor_type="ai",
        actor_id=None,
        action="ai.decision",
        entity_type="case",
        entity_id=str(case.id),
        payload={
            "decision_id": str(decision.id) if getattr(decision, "id", None) else None,
            "route": route,
            "outcome": outcome,
            "confidence": confidence,
            "rule_version_id": str(rule.id) if rule is not None else None,
        },
        tenant_id=case.tenant_id,
    )
    db.session.commit()
    return decision
