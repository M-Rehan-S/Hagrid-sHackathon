"""Evaluation and live operational summary endpoint."""

from flask import Blueprint, g, jsonify

from app.auth import require_role
from app.services.eval_service import EvalError, evaluation_summary


eval_bp = Blueprint("eval", __name__)


@eval_bp.errorhandler(EvalError)
def handle_eval_error(error: EvalError):
    return jsonify({
        "data": None,
        "error": {"code": error.code, "message": error.message, "details": {}},
    }), error.status_code


@eval_bp.get("/summary")
@require_role("officer", "admin", "auditor")
def get_eval_summary():
    return jsonify({"data": evaluation_summary(g.current_user), "error": None})
