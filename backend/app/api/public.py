"""API-key protected public endpoints."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from app.schemas.public_api import PublicScamCheckRequest
from app.services.public_api import (
    PublicAPIError,
    enforce_public_rate_limit,
    public_case_status,
    public_scam_check,
    require_public_api_key,
)


public_bp = Blueprint("public", __name__)
health_bp = Blueprint("health", __name__)


@public_bp.errorhandler(PublicAPIError)
def handle_public_api_error(error: PublicAPIError):
    return jsonify({
        "data": None,
        "error": {"code": error.code, "message": error.message, "details": {}},
    }), error.status_code


@public_bp.errorhandler(ValidationError)
def handle_public_validation_error(_error: ValidationError):
    return jsonify({
        "data": None,
        "error": {"code": "VALIDATION_ERROR", "message": "Request body is invalid.", "details": {}},
    }), 400


@public_bp.post("/scam-check")
@require_public_api_key
def post_public_scam_check():
    enforce_public_rate_limit()
    try:
        body = PublicScamCheckRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        raise
    result = public_scam_check(g.public_api_key, body.text.strip())
    return jsonify({"data": result, "error": None})


@public_bp.get("/cases/<uuid:case_id>/status")
@require_public_api_key
def get_public_case_status(case_id):
    enforce_public_rate_limit()
    result = public_case_status(g.public_api_key, str(case_id))
    return jsonify({"data": result, "error": None})


@health_bp.get("/health")
def get_health():
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    from app.extensions import db

    try:
        db.session.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError:
        return jsonify({"status": "unavailable", "db": "unavailable"}), 503
    return jsonify({"status": "ok", "db": "ok"})
