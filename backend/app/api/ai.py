"""Authenticated AI-assisted endpoints."""

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from app.auth import require_auth
from app.schemas.public_api import PublicScamCheckRequest
from app.services.scam_service import ScamCheckError, check_scam


ai_bp = Blueprint("ai", __name__)


@ai_bp.errorhandler(ScamCheckError)
def handle_scam_check_error(error: ScamCheckError):
    return jsonify({
        "data": None,
        "error": {"code": error.code, "message": error.message, "details": {}},
    }), error.status_code


@ai_bp.post("/scam-check")
@require_auth
def post_scam_check():
    try:
        body = PublicScamCheckRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        return jsonify({
            "data": None,
            "error": {"code": "VALIDATION_ERROR", "message": "Request body is invalid.", "details": {}},
        }), 400
    result = check_scam(g.current_user, body.text)
    return jsonify({"data": result, "error": None})
