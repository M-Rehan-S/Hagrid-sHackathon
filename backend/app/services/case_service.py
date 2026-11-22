"""Tenant-aware case lifecycle operations from PROPOSAL.md §7.4."""

from __future__ import annotations

import re
import math
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import case as sql_case, desc, or_

from app.extensions import db
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.citizen import Citizen
from app.models.consent import Consent
from app.models.decision import Decision
from app.models.document import Document
from app.models.enums import (
    CaseStatus,
    CaseType,
    ConsentScope,
    ConsentStatus,
    DecisionActor,
    DecisionOutcome,
    UserRole,
)
from app.models.helper_citizen_link import HelperCitizenLink
from app.models.mock_payment import MockPayment
from app.models.rule import Rule
from app.models.user import User
from app.services.audit import audit
from app.services.consent_service import ConsentError, check_citizen_access
from app.services.rule_service import get_active_rule
from app.services.n8n_notifier import notify_case_decision


class CaseError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


_ALLOWED_FORM_FIELDS = {
    "full_name", "father_name", "cnic", "dob", "district", "household_size",
    "monthly_income", "is_widow", "phone",
}
_ALLOWED_TRANSITIONS = {
    "draft": {"needs_info", "submitted"},
    "needs_info": {"submitted"},
    "submitted": {"approved", "in_review", "needs_info"},
    "in_review": {"approved", "rejected", "needs_info"},
    "approved": {"closed"},
    "rejected": {"closed"},
    "closed": set(),
}


def _role(user: User) -> str:
    return str(getattr(user.role, "value", user.role))


def _case_or_404(case_id: str, tenant_id: str) -> Case:
    item = db.session.query(Case).filter_by(id=case_id, tenant_id=tenant_id).first()
    if item is None:
        raise CaseError("NOT_FOUND", "Case was not found.", 404)
    return item


def _citizen_for_case(case: Case) -> Citizen:
    citizen = db.session.query(Citizen).filter_by(
        id=case.citizen_id, tenant_id=case.tenant_id
    ).first()
    if citizen is None:
        raise CaseError("NOT_FOUND", "Case was not found.", 404)
    return citizen


def _require_case_access(
    actor: User, item: Case, *, write: bool = False, commit_access_audit: bool = True
) -> Citizen:
    role = _role(actor)
    citizen = _citizen_for_case(item)
    if role == UserRole.citizen.value:
        if str(citizen.user_id) != str(actor.id):
            raise CaseError("NOT_FOUND", "Case was not found.", 404)
        try:
            return check_citizen_access(
                actor, str(citizen.id), ConsentScope.claim_data, commit=commit_access_audit
            )
        except ConsentError as exc:
            raise CaseError(exc.code, exc.message, exc.status_code) from exc
    if role == UserRole.helper.value:
        try:
            check_citizen_access(
                actor, str(citizen.id), ConsentScope.claim_data, commit=commit_access_audit
            )
        except ConsentError as exc:
            raise CaseError(exc.code, exc.message, exc.status_code) from exc
        return citizen
    if role == UserRole.officer.value and not write:
        try:
            check_citizen_access(
                actor, str(citizen.id), ConsentScope.claim_data, commit=commit_access_audit
            )
        except ConsentError as exc:
            raise CaseError(exc.code, exc.message, exc.status_code) from exc
        return citizen
    raise CaseError("FORBIDDEN_ROLE", "Your role cannot access this case.", 403)


def _active_officer_consent(citizen_id: str) -> bool:
    latest = (
        db.session.query(Consent)
        .filter_by(citizen_id=citizen_id, grantee_role=UserRole.officer, scope=ConsentScope.claim_data)
        .order_by(desc(Consent.granted_at), desc(Consent.id))
        .first()
    )
    if latest is None:
        return False
    status = getattr(latest.status, "value", latest.status)
    return status == ConsentStatus.granted.value


def _write_event(item: Case, actor_id: str | None, event_type: str, note: str | None = None) -> None:
    db.session.add(CaseEvent(
        case_id=item.id,
        actor_id=actor_id,
        event_type=event_type,
        note=note,
    ))


def _audit(actor: User, action: str, item: Case, payload: dict[str, Any] | None = None) -> None:
    audit.log(
        actor_type="user",
        actor_id=str(actor.id),
        action=action,
        entity_type="case",
        entity_id=str(item.id),
        payload=payload or {},
        tenant_id=str(actor.tenant_id),
    )


def _required_fields(tenant_id: str) -> set[str]:
    rule = get_active_rule(tenant_id, "relief_eligibility")
    if rule is None:
        raise CaseError("CONFLICT", "No active relief eligibility rule is configured.", 409)
    required = {
        str(condition["field"])
        for condition in rule.definition.get("conditions", [])
        if condition.get("field") in _ALLOWED_FORM_FIELDS
    }
    required.add("full_name")
    return required


def _missing_fields(form: dict[str, Any], tenant_id: str) -> list[str]:
    required = _required_fields(tenant_id)
    missing = {field for field in required if form.get(field) in (None, "")}
    # Identity matching must use a name plus at least one corroborating field.
    if not any(form.get(field) not in (None, "") for field in ("cnic", "dob", "father_name")):
        missing.add("identity_corroborator")
    return sorted(missing)


def _validate_form(form: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    normalized = dict(form)
    invalid: set[str] = set()
    unknown = set(normalized) - _ALLOWED_FORM_FIELDS - {"invalid_fields"}
    if unknown:
        raise CaseError("VALIDATION_ERROR", "Form contains unsupported fields.", 400)

    if normalized.get("cnic") not in (None, ""):
        cnic = str(normalized["cnic"]).replace("-", "")
        normalized["cnic"] = cnic
        if not re.fullmatch(r"\d{13}", cnic):
            invalid.add("cnic")
    if normalized.get("phone") not in (None, "") and not re.fullmatch(r"03\d{9}", str(normalized["phone"])):
        invalid.add("phone")
    if normalized.get("dob") not in (None, ""):
        try:
            normalized["dob"] = date.fromisoformat(str(normalized["dob"])).isoformat()
        except ValueError:
            invalid.add("dob")
    for field in ("full_name", "father_name", "district", "phone"):
        value = normalized.get(field)
        if value is not None and not isinstance(value, str):
            invalid.add(field)
    for field in ("monthly_income", "household_size"):
        value = normalized.get(field)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                invalid.add(field)
            else:
                try:
                    numeric_value = float(value)
                except (OverflowError, ValueError):
                    invalid.add(field)
                    continue
                if (
                    not math.isfinite(numeric_value)
                    or numeric_value < 0
                    or (field == "household_size" and (not numeric_value.is_integer() or numeric_value < 1))
                ):
                    invalid.add(field)
    if normalized.get("is_widow") is not None and not isinstance(normalized["is_widow"], bool):
        invalid.add("is_widow")
    if normalized.get("full_name") is not None and not str(normalized["full_name"]).strip():
        invalid.add("full_name")

    normalized["invalid_fields"] = sorted(invalid)
    return normalized, sorted(invalid)


def create_case(
    actor: User, citizen_id: str, case_type: CaseType, *, commit: bool = True
) -> Case:
    role = _role(actor)
    if role not in (UserRole.citizen.value, UserRole.helper.value):
        raise CaseError("FORBIDDEN_ROLE", "Only citizens and helpers can create cases.", 403)
    citizen = db.session.query(Citizen).filter_by(
        id=citizen_id, tenant_id=actor.tenant_id
    ).first()
    if citizen is None:
        raise CaseError("NOT_FOUND", "Citizen was not found.", 404)
    if role == UserRole.citizen.value:
        if str(citizen.user_id) != str(actor.id):
            raise CaseError("NOT_FOUND", "Citizen was not found.", 404)
    else:
        try:
            check_citizen_access(actor, citizen_id, ConsentScope.claim_data, commit=commit)
        except ConsentError as exc:
            raise CaseError(exc.code, exc.message, exc.status_code) from exc

    item = Case(
        tenant_id=str(actor.tenant_id),
        case_type=case_type,
        citizen_id=citizen_id,
        created_by=str(actor.id),
        status=CaseStatus.draft,
        form_data={},
        missing_fields=_missing_fields({}, str(actor.tenant_id)) if case_type == CaseType.relief_claim else [],
    )
    db.session.add(item)
    db.session.flush()
    _write_event(item, str(actor.id), "created")
    _audit(actor, "case.create", item, {"case_type": case_type.value})
    if commit:
        db.session.commit()
    return item


def list_cases(actor: User, filters: dict[str, str | None]) -> list[Case]:
    role = _role(actor)
    query = db.session.query(Case).filter_by(tenant_id=str(actor.tenant_id))
    if role == UserRole.citizen.value:
        query = query.join(Citizen, Case.citizen_id == Citizen.id).filter(Citizen.user_id == actor.id)
    elif role == UserRole.helper.value:
        query = (
            query.join(HelperCitizenLink, Case.citizen_id == HelperCitizenLink.citizen_id)
            .filter(HelperCitizenLink.helper_user_id == actor.id, HelperCitizenLink.status == "active")
        )
    elif role != UserRole.officer.value:
        raise CaseError("FORBIDDEN_ROLE", "Your role cannot view cases.", 403)

    for field, value in filters.items():
        if value:
            query = query.filter(getattr(Case, field) == value)
    if role == UserRole.officer.value:
        query = query.order_by(
            sql_case((Case.route == "human_review", 0), else_=1),
            Case.priority.asc(),
            Case.confidence.asc().nulls_last(),
        )
    else:
        query = query.order_by(desc(Case.updated_at))

    rows = query.all()
    visible: list[Case] = []
    for item in rows:
        try:
            check_citizen_access(actor, str(item.citizen_id), ConsentScope.claim_data)
        except ConsentError:
            continue
        visible.append(item)
    return visible


def get_case(actor: User, case_id: str) -> dict[str, Any]:
    item = _case_or_404(case_id, str(actor.tenant_id))
    _require_case_access(actor, item)
    decisions = db.session.query(Decision).filter_by(case_id=item.id).order_by(Decision.created_at.asc()).all()
    events = db.session.query(CaseEvent).filter_by(case_id=item.id).order_by(CaseEvent.created_at.asc()).all()
    return {"case": item, "decisions": decisions, "events": events}


def update_form(
    actor: User,
    case_id: str,
    form_data_partial: dict[str, Any],
    last_step: str | None,
    *,
    commit: bool = True,
) -> Case:
    item = _case_or_404(case_id, str(actor.tenant_id))
    _require_case_access(actor, item, write=True, commit_access_audit=commit)
    if item.status not in (CaseStatus.draft, CaseStatus.needs_info):
        raise CaseError("CONFLICT", "This case can no longer be edited.", 409)
    if item.case_type != CaseType.relief_claim:
        raise CaseError("CONFLICT", "Only relief claim forms are supported here.", 409)
    if set(form_data_partial) - _ALLOWED_FORM_FIELDS:
        raise CaseError("VALIDATION_ERROR", "Form contains unsupported fields.", 400)
    merged = {**(item.form_data or {}), **form_data_partial}
    normalized, invalid = _validate_form(merged)
    missing = _missing_fields(normalized, str(actor.tenant_id))
    item.form_data = normalized
    item.missing_fields = sorted(set(missing) | set(invalid))
    item.last_step = last_step
    item.updated_at = datetime.now(timezone.utc)
    _write_event(item, str(actor.id), "note", f"Form updated at step: {last_step or 'unspecified'}.")
    _audit(actor, "case.update_form", item, {"last_step": last_step, "missing_fields": item.missing_fields})
    if commit:
        db.session.commit()
    return item


def upload_document(
    actor: User,
    case_id: str,
    *,
    kind: str,
    content: bytes,
    content_type: str,
) -> Document:
    item = _case_or_404(case_id, str(actor.tenant_id))
    _require_case_access(actor, item, write=True)
    if item.status not in (CaseStatus.draft, CaseStatus.needs_info):
        raise CaseError("CONFLICT", "Documents cannot be added after case submission.", 409)
    if kind not in {"cnic_photo", "supporting_doc"}:
        raise CaseError("VALIDATION_ERROR", "Unsupported document kind.", 400)
    if not content:
        raise CaseError("VALIDATION_ERROR", "Uploaded file is empty.", 400)

    from app.services.document_storage import DocumentStorageError, upload_case_document

    try:
        storage_path = upload_case_document(
            tenant_id=str(item.tenant_id),
            case_id=str(item.id),
            content=content,
            content_type=content_type,
        )
    except DocumentStorageError as exc:
        raise CaseError("INTERNAL_ERROR", "Document storage is unavailable.", 500) from exc

    document = Document(
        case_id=str(item.id),
        kind=kind,
        storage_path=storage_path,
        uploaded_by=str(actor.id),
    )
    db.session.add(document)
    item.updated_at = datetime.now(timezone.utc)
    _write_event(item, str(actor.id), "note", f"Uploaded {kind}.")
    _audit(actor, "document.upload", item, {"document_kind": kind})
    db.session.commit()
    return document


def submit_case(actor: User, case_id: str):
    item = _case_or_404(case_id, str(actor.tenant_id))
    citizen = _require_case_access(actor, item, write=True)
    if item.case_type != CaseType.relief_claim:
        raise CaseError("CONFLICT", "Only relief claims can be submitted to the decision engine.", 409)
    if item.status not in (CaseStatus.draft, CaseStatus.needs_info):
        raise CaseError("CONFLICT", "This case cannot be submitted from its current status.", 409)

    item.missing_fields = _missing_fields(item.form_data or {}, str(actor.tenant_id))
    if item.missing_fields:
        item.status = CaseStatus.needs_info
        _write_event(item, str(actor.id), "proof_requested", "Required claim information is missing.")
        _audit(actor, "case.submit", item, {"missing_fields": item.missing_fields})
        db.session.commit()
        return {"missing_fields": item.missing_fields, "case": item}

    if not _active_officer_consent(str(citizen.id)):
        raise CaseError("CONSENT_REQUIRED", "Citizen consent for officer review is required before submission.", 403)

    item.status = CaseStatus.submitted
    item.updated_at = datetime.now(timezone.utc)
    _write_event(item, str(actor.id), "submitted")
    _audit(actor, "case.submit", item)
    db.session.flush()
    from app.services.decision_engine import decide

    result = decide(str(item.id))
    if not isinstance(result, list):
        notify_case_decision(item, result)
    return {"decision": result, "case": item}


def assign_case(actor: User, case_id: str, officer_id: str) -> Case:
    if _role(actor) not in (UserRole.admin.value, UserRole.officer.value):
        raise CaseError("FORBIDDEN_ROLE", "Only officers and admins can assign cases.", 403)
    item = _case_or_404(case_id, str(actor.tenant_id))
    officer = db.session.query(User).filter_by(
        id=officer_id, tenant_id=actor.tenant_id, role=UserRole.officer, is_active=True
    ).first()
    if officer is None:
        raise CaseError("NOT_FOUND", "Officer was not found.", 404)
    item.assigned_to = str(officer.id)
    item.updated_at = datetime.now(timezone.utc)
    _write_event(item, str(actor.id), "assigned", f"Assigned to officer {officer.id}.")
    _audit(actor, "case.assign", item, {"officer_id": str(officer.id)})
    db.session.commit()
    return item


def escalate_case(actor: User, case_id: str, note: str) -> Case:
    if _role(actor) != UserRole.officer.value:
        raise CaseError("FORBIDDEN_ROLE", "Only officers can escalate cases.", 403)
    item = _case_or_404(case_id, str(actor.tenant_id))
    _require_case_access(actor, item)
    if item.status not in (CaseStatus.submitted, CaseStatus.in_review):
        raise CaseError("CONFLICT", "Only active cases can be escalated.", 409)
    item.priority = 1
    item.updated_at = datetime.now(timezone.utc)
    _write_event(item, str(actor.id), "escalated", note)
    _audit(actor, "case.escalate", item, {"note": note})
    db.session.commit()
    return item


def decide_case_as_officer(actor: User, case_id: str, outcome: DecisionOutcome, note: str) -> Case:
    if _role(actor) != UserRole.officer.value:
        raise CaseError("FORBIDDEN_ROLE", "Only officers can decide cases.", 403)
    item = _case_or_404(case_id, str(actor.tenant_id))
    _require_case_access(actor, item)
    if item.status not in (CaseStatus.submitted, CaseStatus.in_review):
        raise CaseError("CONFLICT", "Only submitted or in-review cases can receive an officer decision.", 409)
    if outcome not in (DecisionOutcome.approved, DecisionOutcome.rejected, DecisionOutcome.needs_more_proof):
        raise CaseError("VALIDATION_ERROR", "Unsupported officer decision outcome.", 400)
    status = {
        DecisionOutcome.approved: CaseStatus.approved,
        DecisionOutcome.rejected: CaseStatus.rejected,
        DecisionOutcome.needs_more_proof: CaseStatus.needs_info,
    }[outcome]
    decision = Decision(
        case_id=str(item.id), actor_type=DecisionActor.officer, actor_id=str(actor.id),
        route=None, outcome=outcome, confidence=None, rule_version_id=item.rule_version_id,
        model_version=None,
        reason_en={
            DecisionOutcome.approved: "An officer approved this claim after review.",
            DecisionOutcome.rejected: "An officer declined this claim after review.",
            DecisionOutcome.needs_more_proof: "An officer needs more information to continue reviewing this claim.",
        }[outcome],
        reason_ur={
            DecisionOutcome.approved: "افسر نے جائزے کے بعد اس دعوے کی منظوری دی۔",
            DecisionOutcome.rejected: "افسر نے جائزے کے بعد اس دعوے کو منظور نہیں کیا۔",
            DecisionOutcome.needs_more_proof: "اس دعوے کے جائزے کو جاری رکھنے کے لیے افسر کو مزید معلومات درکار ہیں۔",
        }[outcome],
        trace={"note": note},
    )
    item.status = status
    item.updated_at = datetime.now(timezone.utc)
    db.session.add(decision)
    _write_event(item, str(actor.id), "decision", note)
    _audit(actor, "officer.decision", item, {"outcome": outcome.value})
    if outcome == DecisionOutcome.approved:
        rule = db.session.query(Rule).filter_by(id=item.rule_version_id, tenant_id=item.tenant_id).first()
        if rule is None or "amount" not in rule.definition:
            raise CaseError("CONFLICT", "The case rule has no mock payment amount.", 409)
        db.session.add(MockPayment(
            case_id=str(item.id), amount=rule.definition["amount"],
            reference=f"MOCK-OFFICER-{item.id}",
        ))
    db.session.commit()
    if outcome == DecisionOutcome.approved:
        notify_case_decision(item, decision, officer_approval=True)
    elif outcome == DecisionOutcome.rejected:
        notify_case_decision(item, decision)
    return item


def close_case(actor: User, case_id: str) -> Case:
    if _role(actor) not in (UserRole.officer.value, UserRole.admin.value):
        raise CaseError("FORBIDDEN_ROLE", "Only officers and admins can close cases.", 403)
    item = _case_or_404(case_id, str(actor.tenant_id))
    if _role(actor) == UserRole.officer.value:
        _require_case_access(actor, item)
    if CaseStatus.closed.value not in _ALLOWED_TRANSITIONS.get(str(getattr(item.status, "value", item.status)), set()):
        raise CaseError("CONFLICT", "Only approved or rejected cases can be closed.", 409)
    item.status = CaseStatus.closed
    item.closed_at = datetime.now(timezone.utc)
    item.updated_at = item.closed_at
    _write_event(item, str(actor.id), "closed")
    _audit(actor, "case.close", item)
    db.session.commit()
    return item
