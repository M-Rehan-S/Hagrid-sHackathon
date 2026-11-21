"""Tenant-scoped citizen profiles and helper links."""

from __future__ import annotations

import re

from app.extensions import db
from app.models.citizen import Citizen
from app.models.enums import ConsentScope, UserRole
from app.models.helper_citizen_link import HelperCitizenLink
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


def _validate_identity_fields(values: dict) -> dict:
    normalized = dict(values)
    name = str(normalized.get("full_name") or "").strip()
    if not name:
        raise CitizenError("VALIDATION_ERROR", "full_name is required.", 400)
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
