"""Admin API key management endpoints."""

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from app.auth import require_role
from app.schemas.api_key import APIKeyCreateRequest
from app.services.api_key_service import create_api_key, list_api_keys, revoke_api_key


api_keys_bp = Blueprint("api_keys", __name__)


@api_keys_bp.errorhandler(ValidationError)
def handle_validation_error(_error):
    return jsonify({
        "data": None,
        "error": {"code": "VALIDATION_ERROR", "message": "Request body is invalid.", "details": {}},
    }), 400


@api_keys_bp.post("")
@require_role("admin")
def post_api_key():
    body = APIKeyCreateRequest.model_validate(request.get_json(silent=True) or {})
    return jsonify({"data": create_api_key(g.current_user, body.label), "error": None}), 201


@api_keys_bp.get("")
@require_role("admin")
def get_api_keys():
    return jsonify({"data": list_api_keys(g.current_user), "error": None})


@api_keys_bp.post("/<uuid:key_id>/revoke")
@require_role("admin")
def post_revoke_api_key(key_id):
    result = revoke_api_key(g.current_user, str(key_id))
    if result is None:
        return jsonify({
            "data": None,
            "error": {"code": "NOT_FOUND", "message": "API key was not found.", "details": {}},
        }), 404
    return jsonify({"data": result, "error": None})
