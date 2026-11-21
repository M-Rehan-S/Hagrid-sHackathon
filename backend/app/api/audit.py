"""Tenant-scoped audit log inspection and hash-chain verification."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request
from sqlalchemy import desc

from app.auth import require_role
from app.extensions import db
from app.models.audit_log import AuditLog
from app.services.audit import verify_audit_chain


audit_bp = Blueprint("audit", __name__)


class AuditAPIError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@audit_bp.errorhandler(AuditAPIError)
def handle_audit_error(error: AuditAPIError):
    return jsonify({
        "data": None,
        "error": {"code": error.code, "message": error.message, "details": {}},
    }), error.status_code


def _parse_timestamp(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditAPIError("VALIDATION_ERROR", f"{name} must be an ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise AuditAPIError("VALIDATION_ERROR", f"{name} must include a UTC offset.")
    return parsed.astimezone(timezone.utc)


def _pagination() -> tuple[int, int]:
    try:
        page = int(request.args.get("page", "1"))
        page_size = int(request.args.get("page_size", "25"))
    except ValueError as exc:
        raise AuditAPIError("VALIDATION_ERROR", "page and page_size must be integers.") from exc
    if page < 1 or page_size < 1 or page_size > 100:
        raise AuditAPIError("VALIDATION_ERROR", "page must be positive and page_size must be 1 to 100.")
    return page, page_size


def _serialize(entry: AuditLog) -> dict:
    ts = entry.ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "id": entry.id,
        "ts": ts,
        "tenant_id": str(entry.tenant_id) if entry.tenant_id is not None else None,
        "actor_type": entry.actor_type,
        "actor_id": entry.actor_id,
        "action": entry.action,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "payload": entry.payload,
        "prev_hash": entry.prev_hash,
        "hash": entry.hash,
    }


def _list_logs(*, actor_id: str | None = None):
    page, page_size = _pagination()
    query = db.session.query(AuditLog).filter_by(tenant_id=str(g.current_user.tenant_id))
    if actor_id is not None:
        query = query.filter(AuditLog.actor_id == actor_id)

    for argument, column in (
        ("actor_id", AuditLog.actor_id),
        ("action", AuditLog.action),
        ("entity_type", AuditLog.entity_type),
        ("entity_id", AuditLog.entity_id),
    ):
        value = request.args.get(argument)
        if value:
            query = query.filter(column == value)

    start = _parse_timestamp(request.args.get("from"), "from")
    end = _parse_timestamp(request.args.get("to"), "to")
    if start and end and start > end:
        raise AuditAPIError("VALIDATION_ERROR", "from must not be later than to.")
    if start:
        query = query.filter(AuditLog.ts >= start)
    if end:
        query = query.filter(AuditLog.ts <= end)

    total = query.count()
    entries = (
        query.order_by(desc(AuditLog.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return jsonify({
        "data": {
            "items": [_serialize(entry) for entry in entries],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        "error": None,
    })


@audit_bp.get("")
@require_role("admin", "auditor")
def get_audit_logs():
    return _list_logs()


@audit_bp.get("/verify")
@require_role("admin", "auditor")
def verify_audit_logs():
    return jsonify({"data": verify_audit_chain(), "error": None})


@audit_bp.get("/mine")
@require_role("citizen")
def get_my_audit_logs():
    return _list_logs(actor_id=str(g.current_user.id))
