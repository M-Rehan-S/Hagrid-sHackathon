"""Ordered, per-operation idempotent offline case synchronization."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from app.extensions import db
from app.models.case import Case
from app.models.enums import CaseType, UserRole
from app.models.idempotency_key import IdempotencyKey
from app.models.user import User
from app.services.audit import audit
from app.services.case_service import CaseError, create_case, update_form


class SyncError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class _OperationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _validate_op_id(value) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _OperationError("VALIDATION_ERROR", "client_op_id must be a UUID.") from exc


def _apply(actor: User, op: dict) -> dict:
    op_type = op.get("type")
    payload = op.get("payload")
    if not isinstance(payload, dict):
        raise _OperationError("VALIDATION_ERROR", "payload must be an object.")

    if op_type == "create_case":
        if set(op) - {"client_op_id", "type", "payload"}:
            raise _OperationError("VALIDATION_ERROR", "Operation contains unsupported fields.")
        if set(payload) - {"citizen_id", "case_type"} or not {"citizen_id", "case_type"}.issubset(payload):
            raise _OperationError("VALIDATION_ERROR", "create_case requires citizen_id and case_type.")
        try:
            citizen_id = str(UUID(str(payload["citizen_id"])))
            case_type = CaseType(payload["case_type"])
        except (TypeError, ValueError, AttributeError) as exc:
            raise _OperationError("VALIDATION_ERROR", "create_case payload is invalid.") from exc
        case = create_case(actor, citizen_id, case_type, commit=False)
        return {"case_id": str(case.id), "status": getattr(case.status, "value", case.status)}

    if op_type == "patch_form":
        if set(op) - {"client_op_id", "type", "case_id", "payload"}:
            raise _OperationError("VALIDATION_ERROR", "Operation contains unsupported fields.")
        if not op.get("case_id") or set(payload) - {"form_data_partial", "last_step"}:
            raise _OperationError("VALIDATION_ERROR", "patch_form requires case_id and a valid payload.")
        try:
            case_id = str(UUID(str(op["case_id"])))
        except (TypeError, ValueError, AttributeError) as exc:
            raise _OperationError("VALIDATION_ERROR", "case_id must be a UUID.") from exc
        partial = payload.get("form_data_partial")
        if not isinstance(partial, dict):
            raise _OperationError("VALIDATION_ERROR", "form_data_partial must be an object.")
        last_step = payload.get("last_step")
        if last_step is not None and (not isinstance(last_step, str) or len(last_step) > 100):
            raise _OperationError("VALIDATION_ERROR", "last_step must be a string of at most 100 characters.")
        case = update_form(actor, case_id, partial, last_step, commit=False)
        return {
            "case_id": str(case.id),
            "status": getattr(case.status, "value", case.status),
            "missing_fields": list(case.missing_fields or []),
        }

    raise _OperationError("VALIDATION_ERROR", "Unsupported sync operation type.")


def _process_op(actor: User, op) -> dict:
    client_op_id = op.get("client_op_id") if isinstance(op, dict) else None
    try:
        key = _validate_op_id(client_op_id)
        if not isinstance(op, dict):
            raise _OperationError("VALIDATION_ERROR", "Each operation must be an object.")
        role = str(getattr(actor.role, "value", actor.role))
        if role not in (UserRole.citizen.value, UserRole.helper.value):
            raise _OperationError("FORBIDDEN_ROLE", "Only citizens and helpers can sync case operations.")

        result = None
        duplicate = False
        with db.session.begin_nested():
            # Serialize attempts for the same operation key across app workers.
            db.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key}
            )
            existing = db.session.query(IdempotencyKey).filter_by(key=key).first()
            if existing is not None:
                if str(existing.user_id) != str(actor.id):
                    raise _OperationError("CONFLICT", "client_op_id was already used by another account.")
                result = existing.response
                duplicate = True
            else:
                result = _apply(actor, op)
                record = IdempotencyKey(key=key, user_id=str(actor.id), response=result)
                db.session.add(record)
                audit.log(
                    actor_type="user", actor_id=str(actor.id), action="sync.batch",
                    entity_type="sync_operation", entity_id=key,
                    payload={"operation_type": op.get("type")}, tenant_id=str(actor.tenant_id),
                )
                db.session.flush()
        db.session.commit()
        return {"client_op_id": client_op_id, "status": "duplicate" if duplicate else "applied", "result": result, "error": None}
    except _OperationError as exc:
        db.session.rollback()
        return {"client_op_id": client_op_id, "status": "error", "result": None,
                "error": {"code": exc.code, "message": exc.message}}
    except CaseError as exc:
        db.session.rollback()
        return {"client_op_id": client_op_id, "status": "error", "result": None,
                "error": {"code": exc.code, "message": exc.message}}
    except Exception:
        db.session.rollback()
        return {"client_op_id": client_op_id, "status": "error", "result": None,
                "error": {"code": "INTERNAL_ERROR", "message": "This sync operation could not be applied."}}


def sync_batch(actor: User, ops: list) -> list[dict]:
    role = str(getattr(actor.role, "value", actor.role))
    if role not in (UserRole.citizen.value, UserRole.helper.value):
        raise SyncError("FORBIDDEN_ROLE", "Only citizens and helpers can sync case operations.", 403)
    if not isinstance(ops, list) or not ops or len(ops) > 100:
        raise SyncError("VALIDATION_ERROR", "ops must contain between 1 and 100 operations.")
    return [_process_op(actor, op) for op in ops]
