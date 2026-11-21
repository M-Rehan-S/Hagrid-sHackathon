"""Offline batch synchronization endpoint."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.auth import require_auth
from app.services.sync_service import SyncError, sync_batch


sync_bp = Blueprint("sync", __name__)


@sync_bp.errorhandler(SyncError)
def handle_sync_error(error: SyncError):
    return jsonify({
        "data": None,
        "error": {"code": error.code, "message": error.message, "details": {}},
    }), error.status_code


@sync_bp.post("/batch")
@require_auth
def post_sync_batch():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"ops"}:
        raise SyncError("VALIDATION_ERROR", "Request body must contain only ops.")
    results = sync_batch(g.current_user, body["ops"])
    return jsonify({"data": {"results": results}, "error": None})
