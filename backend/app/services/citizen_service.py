"""Tenant-scoped citizen profiles and helper links."""

from __future__ import annotations

import re

from app.extensions import db
from app.models.citizen import Citizen
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.consent import Consent
from app.models.decision import Decision
from app.models.document import Document
from app.models.enums import ConsentScope, UserRole
from app.models.helper_citizen_link import HelperCitizenLink
from app.models.mock_payment import MockPayment
from app.models.user import User
from app.services.audit import audit
from app.services.consent_service import ConsentError, check_citizen_access
from app.services.identity_match import name_phonetic_key, normalize_name


class CitizenError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _role(actor: User) -> str:
    return str(getattr(actor.role, "value", actor.role))


def _validate_identity_fields(values: dict, *, require_name: bool = True) -> dict:
    normalized = dict(values)
    name = str(normalized.get("full_name") or "").strip()
    if require_name and not name:
        raise CitizenError("VALIDATION_ERROR", "full_name is required.", 400)
    if "full_name" in normalized:
        if not name:
            raise CitizenError("VALIDATION_ERROR", "full_name cannot be empty.", 400)
        normalized["full_name"] = name
    for field in ("father_name", "district", "phone"):
        if normalized.get(field) is not None:
            normalized[field] = str(normalized[field]).strip() or None
    if normalized.get("cnic"):
        cnic = str(normalized["cnic"]).replace("-", "").strip()
        if not re.fullmatch(r"\d{13}", cnic):
            raise CitizenError("VALIDATION_ERROR", "cnic must contain exactly 13 digits.", 400)
        normalized["cnic"] = cnic
    if normalized.get("phone") and not re.fullmatch(r"03\d{9}", normalized["phone"]):
        raise CitizenError("VALIDATION_ERROR", "phone must contain 11 digits and start with 03.", 400)
    return normalized


def create_citizen(actor: User, fields: dict) -> tuple[Citizen, HelperCitizenLink | None]:
    role = _role(actor)
    if role not in (UserRole.citizen.value, UserRole.helper.value):
        raise CitizenError("FORBIDDEN_ROLE", "Only citizens and helpers can create citizen profiles.", 403)
    values = _validate_identity_fields(fields)
    normalized_name = normalize_name(values["full_name"])
    citizen = Citizen(
        tenant_id=str(actor.tenant_id),
        user_id=str(actor.id) if role == UserRole.citizen.value else None,
        created_by=str(actor.id),
        full_name=values["full_name"],
        father_name=values.get("father_name"),
        cnic=values.get("cnic"),
        dob=values.get("dob"),
        district=values.get("district"),
        phone=values.get("phone"),
        language=str(getattr(actor, "language", "ur") or "ur"),
        name_normalized=normalized_name,
        name_phonetic=name_phonetic_key(normalized_name),
    )
    db.session.add(citizen)
    db.session.flush()

    link = None
    if role == UserRole.helper.value:
        link = HelperCitizenLink(
            helper_user_id=str(actor.id), citizen_id=str(citizen.id), status="active"
        )
        db.session.add(link)
        db.session.flush()

    audit.log(
        actor_type="user", actor_id=str(actor.id), action="citizen.create",
        entity_type="citizen", entity_id=str(citizen.id),
        payload={"created_by_role": role, "helper_linked": link is not None},
        tenant_id=str(actor.tenant_id),
    )
    db.session.commit()
    return citizen, link


def get_citizen(actor: User, citizen_id: str) -> Citizen:
    try:
        return check_citizen_access(actor, citizen_id, ConsentScope.identity)
    except ConsentError as exc:
        raise CitizenError(exc.code, exc.message, exc.status_code) from exc


def list_helper_citizens(actor: User) -> list[dict]:
    if _role(actor) != UserRole.helper.value:
        raise CitizenError("FORBIDDEN_ROLE", "Only helpers can list their citizen links.", 403)
    links = (
        db.session.query(HelperCitizenLink)
        .filter_by(helper_user_id=str(actor.id))
        .order_by(HelperCitizenLink.created_at.desc(), HelperCitizenLink.id.desc())
        .all()
    )
    result = []
    for link in links:
        citizen = db.session.query(Citizen).filter_by(
            id=link.citizen_id, tenant_id=str(actor.tenant_id)
        ).first()
        if citizen is None:
            continue
        item = {"citizen_id": str(citizen.id), "status": link.status, "created_at": link.created_at}
        try:
            check_citizen_access(actor, str(citizen.id), ConsentScope.identity)
        except ConsentError as exc:
            if exc.code == "CONSENT_WITHDRAWN":
                continue
            # The link may be pending consent. Return link metadata only.
            if exc.code not in ("CONSENT_REQUIRED",):
                continue
        else:
            item["full_name"] = citizen.full_name
        result.append(item)
    return result


def link_helper_to_citizen(actor: User, citizen_id: str) -> HelperCitizenLink:
    if _role(actor) != UserRole.helper.value:
        raise CitizenError("FORBIDDEN_ROLE", "Only helpers can create citizen links.", 403)
    citizen = db.session.query(Citizen).filter_by(
        id=citizen_id, tenant_id=str(actor.tenant_id)
    ).first()
    if citizen is None:
        raise CitizenError("NOT_FOUND", "Citizen was not found.", 404)
    link = db.session.query(HelperCitizenLink).filter_by(
        helper_user_id=str(actor.id), citizen_id=str(citizen.id)
    ).first()
    if link is None:
        link = HelperCitizenLink(
            helper_user_id=str(actor.id), citizen_id=str(citizen.id), status="active"
        )
        db.session.add(link)
        db.session.flush()
    elif link.status != "active":
        link.status = "active"
    audit.log(
        actor_type="user", actor_id=str(actor.id), action="helper.link",
        entity_type="citizen", entity_id=str(citizen.id),
        payload={"link_id": str(link.id), "status": "active"},
        tenant_id=str(actor.tenant_id),
    )
    db.session.commit()
    return link


def update_citizen(actor: User, citizen_id: str, fields: dict) -> Citizen:
    if _role(actor) != UserRole.citizen.value:
        raise CitizenError("FORBIDDEN_ROLE", "Only citizens can update their own profile.", 403)
    if not fields:
        raise CitizenError("VALIDATION_ERROR", "At least one profile field is required.", 400)
    citizen = db.session.query(Citizen).filter_by(
        id=citizen_id, tenant_id=str(actor.tenant_id), user_id=str(actor.id)
    ).first()
    if citizen is None:
        raise CitizenError("NOT_FOUND", "Citizen was not found.", 404)
    values = _validate_identity_fields(fields, require_name=False)
    for field, value in values.items():
        setattr(citizen, field, value)
    if "full_name" in values:
        normalized_name = normalize_name(citizen.full_name)
        citizen.name_normalized = normalized_name
        citizen.name_phonetic = name_phonetic_key(normalized_name)
    audit.log(
        actor_type="user", actor_id=str(actor.id), action="citizen.update",
        entity_type="citizen", entity_id=str(citizen.id),
        payload={"updated_fields": sorted(values)}, tenant_id=str(actor.tenant_id),
    )
    db.session.commit()
    return citizen


def _plain(value):
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _document_data(document: Document) -> dict:
    from app.services.document_storage import create_document_download_url

    try:
        download_url = create_document_download_url(document.storage_path)
    except Exception as exc:
        raise CitizenError("INTERNAL_ERROR", "Document export is temporarily unavailable.", 500) from exc
    return {
        "id": str(document.id),
        "kind": document.kind,
        "ocr_text": document.ocr_text,
        "quality_score": float(document.quality_score) if document.quality_score is not None else None,
        "uploaded_by": str(document.uploaded_by),
        "created_at": _plain(document.created_at),
        "download_url": download_url,
        "download_url_expires_in_seconds": 300,
    }


def export_citizen_data(actor: User, citizen_id: str) -> dict:
    if _role(actor) != UserRole.citizen.value:
        raise CitizenError("FORBIDDEN_ROLE", "Only citizens can export their own profile data.", 403)
    citizen = db.session.query(Citizen).filter_by(
        id=citizen_id, tenant_id=str(actor.tenant_id), user_id=str(actor.id)
    ).first()
    if citizen is None:
        raise CitizenError("NOT_FOUND", "Citizen was not found.", 404)

    cases = db.session.query(Case).filter_by(
        citizen_id=str(citizen.id), tenant_id=str(actor.tenant_id)
    ).order_by(Case.created_at.asc(), Case.id.asc()).all()
    case_exports = []
    for case in cases:
        decisions = db.session.query(Decision).filter_by(case_id=str(case.id)).order_by(
            Decision.created_at.asc(), Decision.id.asc()
        ).all()
        events = db.session.query(CaseEvent).filter_by(case_id=str(case.id)).order_by(
            CaseEvent.created_at.asc(), CaseEvent.id.asc()
        ).all()
        documents = db.session.query(Document).filter_by(case_id=str(case.id)).order_by(
            Document.created_at.asc(), Document.id.asc()
        ).all()
        payments = db.session.query(MockPayment).filter_by(case_id=str(case.id)).order_by(
            MockPayment.created_at.asc(), MockPayment.id.asc()
        ).all()
        case_exports.append({
            "case": {
                "id": str(case.id), "case_type": _plain(case.case_type),
                "status": _plain(case.status), "route": _plain(case.route),
                "confidence": float(case.confidence) if case.confidence is not None else None,
                "priority": case.priority, "form_data": case.form_data,
                "missing_fields": list(case.missing_fields or []),
                "rule_version_id": str(case.rule_version_id) if case.rule_version_id else None,
                "created_at": _plain(case.created_at), "updated_at": _plain(case.updated_at),
                "closed_at": _plain(case.closed_at),
            },
            "decisions": [{
                "id": str(row.id), "actor_type": _plain(row.actor_type),
                "route": _plain(row.route), "outcome": _plain(row.outcome),
                "confidence": float(row.confidence) if row.confidence is not None else None,
                "rule_version_id": str(row.rule_version_id) if row.rule_version_id else None,
                "model_version": row.model_version, "reason_en": row.reason_en,
                "reason_ur": row.reason_ur, "trace": row.trace,
                "created_at": _plain(row.created_at),
            } for row in decisions],
            "events": [{
                "id": str(row.id), "event_type": row.event_type, "note": row.note,
                "created_at": _plain(row.created_at),
            } for row in events],
            "documents": [_document_data(row) for row in documents],
            "mock_payments": [{
                "id": str(row.id), "amount": str(row.amount), "status": row.status,
                "reference": row.reference, "created_at": _plain(row.created_at),
            } for row in payments],
        })

    consents = db.session.query(Consent).filter_by(citizen_id=str(citizen.id)).order_by(
        Consent.granted_at.asc(), Consent.id.asc()
    ).all()
    links = db.session.query(HelperCitizenLink).join(
        Citizen, Citizen.id == HelperCitizenLink.citizen_id
    ).filter(
        HelperCitizenLink.citizen_id == str(citizen.id), Citizen.tenant_id == str(actor.tenant_id)
    ).order_by(HelperCitizenLink.created_at.asc(), HelperCitizenLink.id.asc()).all()

    result = {
        "citizen": {
            "id": str(citizen.id), "tenant_id": str(citizen.tenant_id),
            "user_id": str(citizen.user_id) if citizen.user_id else None,
            "full_name": citizen.full_name, "father_name": citizen.father_name,
            "cnic": citizen.cnic, "dob": _plain(citizen.dob), "district": citizen.district,
            "phone": citizen.phone, "language": citizen.language,
            "created_at": _plain(citizen.created_at),
        },
        "cases": case_exports,
        "consents": [{
            "id": str(row.id), "grantee_user_id": str(row.grantee_user_id) if row.grantee_user_id else None,
            "grantee_role": _plain(row.grantee_role), "scope": _plain(row.scope),
            "status": _plain(row.status), "granted_at": _plain(row.granted_at),
            "withdrawn_at": _plain(row.withdrawn_at),
        } for row in consents],
        "helper_links": [{
            "id": str(row.id), "helper_user_id": str(row.helper_user_id),
            "status": row.status, "created_at": _plain(row.created_at),
        } for row in links],
    }
    audit.log(
        actor_type="user", actor_id=str(actor.id), action="data.export",
        entity_type="citizen", entity_id=str(citizen.id),
        payload={"case_count": len(case_exports)}, tenant_id=str(actor.tenant_id),
    )
    db.session.commit()
    return result
