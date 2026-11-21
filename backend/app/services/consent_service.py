"""Consent grants, revocation, and citizen data access checks."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc

from app.extensions import db
from app.models.citizen import Citizen
from app.models.consent import Consent
from app.models.enums import ConsentScope, ConsentStatus, UserRole
from app.models.helper_citizen_link import HelperCitizenLink
from app.models.user import User
from app.services.audit import audit


class ConsentError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _role(user: User) -> str:
    return str(getattr(user.role, "value", user.role))


def _get_citizen(citizen_id: str, tenant_id: str) -> Citizen:
    citizen = db.session.query(Citizen).filter_by(id=citizen_id, tenant_id=tenant_id).first()
    if citizen is None:
        raise ConsentError("NOT_FOUND", "Citizen was not found.", 404)
    return citizen


def _require_owner(actor: User, citizen_id: str) -> Citizen:
    if _role(actor) != UserRole.citizen.value:
        raise ConsentError("FORBIDDEN_ROLE", "Only the citizen can manage consent.", 403)
    citizen = _get_citizen(citizen_id, str(actor.tenant_id))
    if str(citizen.user_id) != str(actor.id):
        raise ConsentError("NOT_FOUND", "Citizen was not found.", 404)
    return citizen


def _audit(actor: User, action: str, consent: Consent) -> None:
    audit.log(
        actor_type="user",
        actor_id=str(actor.id),
        action=action,
        entity_type="consent",
        entity_id=str(consent.id),
        payload={"citizen_id": str(consent.citizen_id), "scope": str(getattr(consent.scope, "value", consent.scope))},
        tenant_id=str(actor.tenant_id),
    )


def list_consents(actor: User, citizen_id: str) -> list[Consent]:
    role = _role(actor)
    citizen = _get_citizen(citizen_id, str(actor.tenant_id))
    if role == UserRole.citizen.value:
        if str(citizen.user_id) != str(actor.id):
            raise ConsentError("NOT_FOUND", "Citizen was not found.", 404)
    elif role != UserRole.auditor.value:
        raise ConsentError("FORBIDDEN_ROLE", "Your role cannot view consent records.", 403)

    return (
        db.session.query(Consent)
        .filter_by(citizen_id=citizen_id)
        .order_by(desc(Consent.granted_at), desc(Consent.id))
        .all()
    )


def grant_consent(
    actor: User,
    *,
    citizen_id: str,
    grantee_user_id: str | None,
    grantee_role: UserRole | None,
    scope: ConsentScope,
) -> Consent:
    _require_owner(actor, citizen_id)
    if (grantee_user_id is None) == (grantee_role is None):
        raise ConsentError("VALIDATION_ERROR", "Choose exactly one consent grantee.", 400)

    if grantee_user_id is not None:
        grantee = db.session.query(User).filter_by(
            id=grantee_user_id, tenant_id=actor.tenant_id, is_active=True
        ).first()
        if grantee is None:
            raise ConsentError("NOT_FOUND", "Consent recipient was not found.", 404)

    consent = Consent(
        citizen_id=citizen_id,
        grantee_user_id=grantee_user_id,
        grantee_role=grantee_role,
        scope=scope,
        status=ConsentStatus.granted,
    )
    db.session.add(consent)
    db.session.flush()
    _audit(actor, "consent.grant", consent)
    db.session.commit()
    return consent


def withdraw_consent(actor: User, consent_id: str) -> Consent:
    consent = db.session.query(Consent).filter_by(id=consent_id).first()
    if consent is None:
        raise ConsentError("NOT_FOUND", "Consent was not found.", 404)
    _require_owner(actor, str(consent.citizen_id))
    if consent.status == ConsentStatus.withdrawn:
        raise ConsentError("CONFLICT", "Consent has already been withdrawn.", 409)

    consent.status = ConsentStatus.withdrawn
    consent.withdrawn_at = datetime.now(timezone.utc)
    _audit(actor, "consent.withdraw", consent)
    db.session.commit()
    return consent


def _matching_latest_consent(
    actor: User, citizen_id: str, scope: ConsentScope
) -> Consent | None:
    records = (
        db.session.query(Consent)
        .filter_by(citizen_id=citizen_id, scope=scope)
        .order_by(desc(Consent.granted_at), desc(Consent.id))
        .all()
    )
    role = _role(actor)
    matches = []
    for consent in records:
        if role == UserRole.officer.value:
            matches.append(consent.grantee_role == UserRole.officer)
        elif role == UserRole.helper.value:
            matches.append(
                str(consent.grantee_user_id) == str(actor.id)
                or consent.grantee_role == UserRole.helper
            )
    return next((row for row, matched in zip(records, matches) if matched), None)


def _log_access(actor: User, citizen_id: str, action: str, scope: ConsentScope) -> None:
    audit.log(
        actor_type="user",
        actor_id=str(actor.id),
        action=action,
        entity_type="citizen",
        entity_id=citizen_id,
        payload={"scope": scope.value},
        tenant_id=str(actor.tenant_id),
    )


def check_citizen_access(actor: User, citizen_id: str, scope: ConsentScope) -> Citizen:
    """Enforce ownership/link/consent and audit allowed or withdrawn access."""
    citizen = _get_citizen(citizen_id, str(actor.tenant_id))
    role = _role(actor)

    if role == UserRole.citizen.value and str(citizen.user_id) == str(actor.id):
        _log_access(actor, citizen_id, "data.read_pii", scope)
        db.session.commit()
        return citizen

    if role == UserRole.helper.value:
        link = db.session.query(HelperCitizenLink).filter_by(
            helper_user_id=actor.id, citizen_id=citizen_id, status="active"
        ).first()
        if link is None:
            raise ConsentError("CONSENT_REQUIRED", "Active helper link and consent are required.", 403)
    elif role != UserRole.officer.value:
        raise ConsentError("FORBIDDEN_ROLE", "Your role cannot access this citizen's data.", 403)

    consent = _matching_latest_consent(actor, citizen_id, scope)
    if consent is None:
        raise ConsentError("CONSENT_REQUIRED", "Consent is required for this data.", 403)
    status = getattr(consent.status, "value", consent.status)
    if status == ConsentStatus.withdrawn.value:
        _log_access(actor, citizen_id, "consent.access_denied", scope)
        db.session.commit()
        raise ConsentError("CONSENT_WITHDRAWN", "Citizen has withdrawn consent.", 403)
    if status != ConsentStatus.granted.value:
        raise ConsentError("CONSENT_REQUIRED", "Consent is required for this data.", 403)

    _log_access(actor, citizen_id, "data.read_pii", scope)
    db.session.commit()
    return citizen


def require_consent(scope: ConsentScope):
    """Decorator for citizen-data routes whose URL includes ``citizen_id``."""
    from functools import wraps

    from flask import g, request

    from app.auth import require_auth

    scope = ConsentScope(scope)

    def decorate(view):
        @wraps(view)
        @require_auth
        def wrapped(*args: Any, **kwargs: Any):
            citizen_id = kwargs.get("citizen_id") or request.args.get("citizen_id")
            if not citizen_id:
                raise ConsentError("VALIDATION_ERROR", "citizen_id is required.", 400)
            g.consent_citizen = check_citizen_access(g.current_user, citizen_id, scope)
            return view(*args, **kwargs)

        return wrapped

    return decorate
