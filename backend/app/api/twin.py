"""Digital Twin endpoint for in-memory draft rule replay."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from app.auth import require_role
from app.schemas.twin import TwinSimulationRequest
from app.services.twin_service import TwinError, simulate_rule_change


twin_bp = Blueprint("twin", __name__)


@twin_bp.errorhandler(TwinError)
def handle_twin_error(error: TwinError):
    return jsonify({
        "data": None,
        "error": {"code": error.code, "message": error.message, "details": {}},
    }), error.status_code


@twin_bp.post("/simulate")
@require_role("admin")
def post_simulate():
    try:
        body = TwinSimulationRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise TwinError("VALIDATION_ERROR", "Simulation request is invalid.", 400) from exc

    result = simulate_rule_change(
        tenant_id=str(g.current_user.tenant_id),
        draft_rule_id=str(body.draft_rule_id),
        limit=body.limit,
    )
    return jsonify({"data": result, "error": None})
