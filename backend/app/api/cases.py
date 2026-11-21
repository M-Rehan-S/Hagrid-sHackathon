"""Relief case lifecycle endpoints."""

from __future__ import annotations

from datetime import timezone
from decimal import Decimal
from typing import Any

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from app.auth import require_auth, require_role
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.decision import Decision
from app.schemas.case import (
    CaseAssignRequest,
    CaseCreateRequest,
    CaseFormPatchRequest,
    CaseNoteRequest,
    OfficerDecisionRequest,
)
from app.services.case_service import (
    CaseError,
    assign_case,
    close_case,
    create_case,
    decide_case_as_officer,
    escalate_case,
    get_case,
    list_cases,
    submit_case,
    update_form,
    upload_document,
)


cases_bp = Blueprint("cases", __name__)


@cases_bp.errorhandler(CaseError)
def handle_case_error(error: CaseError):
    return jsonify({
        "data": None,
        "error": {"code": error.code, "message": error.message, "details": {}},
    }), error.status_code


def _iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _number(value):
    return float(value) if isinstance(value, Decimal) else value


def _role(user) -> str:
    return str(getattr(user.role, "value", user.role))


def _case_data(item: Case) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "case_type": getattr(item.case_type, "value", item.case_type),
        "citizen_id": str(item.citizen_id),
        "created_by": str(item.created_by),
        "assigned_to": str(item.assigned_to) if item.assigned_to else None,
        "status": getattr(item.status, "value", item.status),
        "route": getattr(item.route, "value", item.route),
        "confidence": _number(item.confidence),
        "priority": item.priority,
        "form_data": item.form_data,
        "missing_fields": list(item.missing_fields or []),
        "rule_version_id": str(item.rule_version_id) if item.rule_version_id else None,
        "last_step": item.last_step,
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
        "closed_at": _iso(item.closed_at),
    }


def _decision_data(item: Decision, *, include_trace: bool = False) -> dict[str, Any]:
    result = {
        "id": str(item.id),
        "case_id": str(item.case_id),
        "actor_type": getattr(item.actor_type, "value", item.actor_type),
        "actor_id": str(item.actor_id) if item.actor_id else None,
        "route": getattr(item.route, "value", item.route),
        "outcome": getattr(item.outcome, "value", item.outcome),
        "confidence": _number(item.confidence),
        "rule_version_id": str(item.rule_version_id) if item.rule_version_id else None,
        "model_version": item.model_version,
        "reason_en": item.reason_en,
        "reason_ur": item.reason_ur,
        "created_at": _iso(item.created_at),
    }
    if include_trace:
        result["trace"] = item.trace
    return result


def _event_data(item: CaseEvent) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "case_id": str(item.case_id),
        "actor_id": str(item.actor_id) if item.actor_id else None,
        "event_type": item.event_type,
        "note": item.note,
        "created_at": _iso(item.created_at),
    }


def _validate(model, body):
    try:
        return model.model_validate(body or {})
    except ValidationError as exc:
        raise CaseError("VALIDATION_ERROR", "Request body is invalid.", 400) from exc


@cases_bp.post("")
@require_role("citizen", "helper")
def post_case():
    body = _validate(CaseCreateRequest, request.get_json(silent=True))
    item = create_case(g.current_user, str(body.citizen_id), body.case_type)
    return jsonify({"data": _case_data(item), "error": None}), 201


@cases_bp.get("")
@require_auth
def get_cases():
    filters = {}
    for key, allowed in (
        ("status", {"draft", "needs_info", "submitted", "in_review", "approved", "rejected", "closed"}),
        ("route", {"auto_approve", "ask_more", "human_review"}),
    ):
        value = request.args.get(key)
        if value and value not in allowed:
            raise CaseError("VALIDATION_ERROR", f"Invalid {key} filter.", 400)
        filters[key] = value
    assigned_to = request.args.get("assigned_to")
    if assigned_to:
        filters["assigned_to"] = assigned_to
    rows = list_cases(g.current_user, filters)
    return jsonify({"data": [_case_data(row) for row in rows], "error": None})


@cases_bp.get("/<uuid:case_id>")
@require_auth
def get_case_route(case_id):
    result = get_case(g.current_user, str(case_id))
    return jsonify({
        "data": {
            **_case_data(result["case"]),
            "decisions": [
                _decision_data(row, include_trace=_role(g.current_user) == "officer")
                for row in result["decisions"]
            ],
            "events": [_event_data(row) for row in result["events"]],
        },
        "error": None,
    })


@cases_bp.patch("/<uuid:case_id>/form")
@require_role("citizen", "helper")
def patch_case_form(case_id):
    body = _validate(CaseFormPatchRequest, request.get_json(silent=True))
    item = update_form(
        g.current_user, str(case_id), body.form_data_partial, body.last_step
    )
    return jsonify({"data": {"case": _case_data(item), "missing_fields": item.missing_fields}, "error": None})


@cases_bp.post("/<uuid:case_id>/submit")
@require_role("citizen", "helper")
def post_case_submit(case_id):
    result = submit_case(g.current_user, str(case_id))
    if "missing_fields" in result:
        return jsonify({
            "data": {"case": _case_data(result["case"]), "missing_fields": result["missing_fields"]},
            "error": None,
        }), 200
    return jsonify({
        "data": {
            "case": _case_data(result["case"]),
            "decision": _decision_data(result["decision"]),
        },
        "error": None,
    })


@cases_bp.post("/<uuid:case_id>/documents")
@require_role("citizen", "helper")
def post_case_document(case_id):
    uploaded = request.files.get("file")
    kind = request.form.get("kind", "")
    if uploaded is None:
        raise CaseError("VALIDATION_ERROR", "file is required.", 400)
    document = upload_document(
        g.current_user,
        str(case_id),
        kind=kind,
        content=uploaded.read(),
        content_type=uploaded.mimetype,
    )
    return jsonify({
        "data": {
            "id": str(document.id),
            "case_id": str(document.case_id),
            "kind": document.kind,
            "created_at": _iso(document.created_at),
        },
        "error": None,
    }), 201


@cases_bp.post("/<uuid:case_id>/assign")
@require_role("admin", "officer")
def post_case_assign(case_id):
    body = _validate(CaseAssignRequest, request.get_json(silent=True))
    item = assign_case(g.current_user, str(case_id), str(body.officer_id))
    return jsonify({
        "data": {
            "id": str(item.id),
            "assigned_to": str(item.assigned_to),
            "status": getattr(item.status, "value", item.status),
        },
        "error": None,
    })


@cases_bp.post("/<uuid:case_id>/escalate")
@require_role("officer")
def post_case_escalate(case_id):
    body = _validate(CaseNoteRequest, request.get_json(silent=True))
    item = escalate_case(g.current_user, str(case_id), body.note)
    return jsonify({"data": _case_data(item), "error": None})


@cases_bp.post("/<uuid:case_id>/decision")
@require_role("officer")
def post_officer_decision(case_id):
    body = _validate(OfficerDecisionRequest, request.get_json(silent=True))
    from app.models.enums import DecisionOutcome

    item = decide_case_as_officer(
        g.current_user, str(case_id), DecisionOutcome(body.outcome), body.note
    )
    return jsonify({"data": _case_data(item), "error": None})


@cases_bp.post("/<uuid:case_id>/close")
@require_role("officer", "admin")
def post_case_close(case_id):
    item = close_case(g.current_user, str(case_id))
    return jsonify({
        "data": {
            "id": str(item.id),
            "status": getattr(item.status, "value", item.status),
            "closed_at": _iso(item.closed_at),
        },
        "error": None,
    })
