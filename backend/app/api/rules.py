"""Versioned eligibility rule management API."""

from __future__ import annotations

from datetime import timezone

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from app.auth import require_auth, require_role
from app.extensions import db
from app.models.rule import Rule
from app.schemas.rule import RuleCreateRequest
from app.services.rule_service import activate_rule, create_rule_draft


rules_bp = Blueprint("rules", __name__)


class RuleAPIError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@rules_bp.errorhandler(RuleAPIError)
def handle_rule_error(error: RuleAPIError):
    return jsonify({
        "data": None,
        "error": {"code": error.code, "message": error.message, "details": {}},
    }), error.status_code


def _serialize(rule: Rule) -> dict:
    return {
        "id": str(rule.id),
        "tenant_id": str(rule.tenant_id),
        "rule_key": rule.rule_key,
        "version": rule.version,
        "status": getattr(rule.status, "value", rule.status),
        "definition": rule.definition,
        "note": rule.note,
        "created_by": str(rule.created_by) if rule.created_by else None,
        "created_at": rule.created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if rule.created_at else None,
        "activated_at": rule.activated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if rule.activated_at else None,
    }


@rules_bp.get("")
@require_role("admin", "auditor", "officer")
def get_rules():
    query = db.session.query(Rule).filter_by(tenant_id=str(g.current_user.tenant_id))
    rule_key = request.args.get("rule_key")
    if rule_key:
        query = query.filter_by(rule_key=rule_key)
    rows = query.order_by(Rule.rule_key.asc(), Rule.version.desc()).all()
    return jsonify({"data": [_serialize(row) for row in rows], "error": None})


@rules_bp.post("")
@require_role("admin")
def post_rule():
    try:
        body = RuleCreateRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RuleAPIError("VALIDATION_ERROR", "Rule definition is invalid.", 400) from exc

    rule = create_rule_draft(
        str(g.current_user.tenant_id),
        body.rule_key,
        body.definition.model_dump(mode="json"),
        body.note,
        str(g.current_user.id),
    )
    return jsonify({"data": _serialize(rule), "error": None}), 201


@rules_bp.post("/<uuid:rule_id>/activate")
@require_role("admin")
def post_activate_rule(rule_id):
    rule = activate_rule(
        str(rule_id), str(g.current_user.id), tenant_id=str(g.current_user.tenant_id)
    )
    if rule is None:
        raise RuleAPIError("NOT_FOUND", "Rule version was not found.", 404)
    return jsonify({"data": _serialize(rule), "error": None})
