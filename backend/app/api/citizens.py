"""Citizen profiles and helper-citizen link endpoints."""

from __future__ import annotations

from datetime import timezone

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from app.auth import require_auth
from app.models.citizen import Citizen
from app.models.helper_citizen_link import HelperCitizenLink
from app.schemas.citizen import CitizenCreateRequest
from app.services.citizen_service import (
    CitizenError,
    create_citizen,
    get_citizen,
    link_helper_to_citizen,
    list_helper_citizens,
)


citizens_bp = Blueprint("citizens", __name__)


def _timestamp(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _citizen_payload(citizen: Citizen) -> dict:
    return {
        "id": str(citizen.id),
        "tenant_id": str(citizen.tenant_id),
        "user_id": str(citizen.user_id) if citizen.user_id else None,
        "full_name": citizen.full_name,
        "father_name": citizen.father_name,
        "cnic": citizen.cnic,
        "dob": citizen.dob.isoformat() if citizen.dob else None,
        "district": citizen.district,
        "phone": citizen.phone,
        "language": citizen.language,
        "created_at": _timestamp(citizen.created_at),
    }


def _link_payload(link: HelperCitizenLink) -> dict:
    return {
        "id": str(link.id),
        "citizen_id": str(link.citizen_id),
        "status": link.status,
        "created_at": _timestamp(link.created_at),
    }


def _validation_error() -> CitizenError:
    return CitizenError("VALIDATION_ERROR", "Request body is invalid.", 400)


@citizens_bp.errorhandler(CitizenError)
def handle_citizen_error(error: CitizenError):
    return jsonify({
        "data": None,
        "error": {"code": error.code, "message": error.message, "details": {}},
    }), error.status_code


@citizens_bp.post("/citizens")
@require_auth
def post_citizen():
    try:
        body = CitizenCreateRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise _validation_error() from exc
    citizen, link = create_citizen(g.current_user, body.model_dump())
    return jsonify({
        "data": {"citizen": _citizen_payload(citizen), "helper_link": _link_payload(link) if link else None},
        "error": None,
    }), 201


@citizens_bp.get("/citizens/<uuid:citizen_id>")
@require_auth
def get_citizen_route(citizen_id):
    citizen = get_citizen(g.current_user, str(citizen_id))
    return jsonify({"data": _citizen_payload(citizen), "error": None})


@citizens_bp.get("/helper/citizens")
@require_auth
def get_helper_citizens():
    rows = list_helper_citizens(g.current_user)
    return jsonify({
        "data": [{**row, "created_at": _timestamp(row["created_at"])} for row in rows],
        "error": None,
    })


@citizens_bp.post("/helper/citizens/<uuid:citizen_id>/link")
@require_auth
def post_helper_citizen_link(citizen_id):
    link = link_helper_to_citizen(g.current_user, str(citizen_id))
    return jsonify({"data": _link_payload(link), "error": None}), 201
