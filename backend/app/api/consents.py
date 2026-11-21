"""Consent grant and withdrawal endpoints."""

from __future__ import annotations

from datetime import timezone

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from app.auth import require_auth
from app.models.consent import Consent
from app.schemas.consent import ConsentGrantRequest
from app.services.consent_service import (
    ConsentError,
    grant_consent,
    list_consents,
    withdraw_consent,
)


consents_bp = Blueprint("consents", __name__)


def _datetime(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _payload(consent: Consent) -> dict:
    return {
        "id": str(consent.id),
        "citizen_id": str(consent.citizen_id),
        "grantee_user_id": str(consent.grantee_user_id) if consent.grantee_user_id else None,
        "grantee_role": getattr(consent.grantee_role, "value", consent.grantee_role),
        "scope": getattr(consent.scope, "value", consent.scope),
        "status": getattr(consent.status, "value", consent.status),
        "granted_at": _datetime(consent.granted_at),
        "withdrawn_at": _datetime(consent.withdrawn_at),
    }


def _validation_error(error: ValidationError) -> ConsentError:
    return ConsentError(
        "VALIDATION_ERROR",
        "Consent request is invalid.",
        400,
    )


@consents_bp.errorhandler(ConsentError)
def handle_consent_error(error: ConsentError):
    return jsonify({
        "data": None,
        "error": {"code": error.code, "message": error.message, "details": {}},
    }), error.status_code


@consents_bp.get("")
@require_auth
def get_consents():
    citizen_id = request.args.get("citizen_id")
    if not citizen_id:
        raise ConsentError("VALIDATION_ERROR", "citizen_id is required.", 400)
    rows = list_consents(g.current_user, citizen_id)
    return jsonify({"data": [_payload(row) for row in rows], "error": None})


@consents_bp.post("")
@require_auth
def post_consent():
    try:
        body = ConsentGrantRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise _validation_error(exc) from exc

    consent = grant_consent(
        g.current_user,
        citizen_id=str(body.citizen_id),
        grantee_user_id=str(body.grantee_user_id) if body.grantee_user_id else None,
        grantee_role=body.grantee_role,
        scope=body.scope,
    )
    return jsonify({"data": _payload(consent), "error": None}), 201


@consents_bp.post("/<uuid:consent_id>/withdraw")
@require_auth
def post_withdraw_consent(consent_id):
    consent = withdraw_consent(g.current_user, str(consent_id))
    return jsonify({"data": _payload(consent), "error": None})
