"""Append-only, hash-chained audit writer required by proposal §8.6."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import asc, desc, select, text

from app.extensions import db
from app.models.audit_log import AuditLog


_GENESIS_HASH = "0" * 64
_AUDIT_ADVISORY_LOCK = 731942601


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, UUID)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return str(value.value)
    raise TypeError(f"Cannot serialize {type(value).__name__} in an audit payload")


def calculate_audit_hash(
    previous_hash: str,
    *,
    ts: datetime,
    tenant_id: str | None,
    actor_type: str,
    actor_id: str | None,
    action: str,
    entity_type: str | None,
    entity_id: str | None,
    payload: dict[str, Any],
) -> str:
    """Reproduce the canonical digest used by the writer for verification."""
    timestamp = ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    chain_payload = {
        "ts": timestamp,
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
        "actor_type": actor_type,
        "actor_id": str(actor_id) if actor_id is not None else None,
        "action": action,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id is not None else None,
        "payload": payload,
    }
    canonical = json.dumps(
        chain_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )
    return hashlib.sha256((previous_hash + canonical).encode("utf-8")).hexdigest()


def verify_audit_chain() -> dict[str, Any]:
    """Verify every immutable audit row in ID order; stop at the first break."""
    entries = db.session.scalars(select(AuditLog).order_by(asc(AuditLog.id))).all()
    previous_hash = _GENESIS_HASH
    for entry in entries:
        if not hmac.compare_digest(
            str(entry.prev_hash).encode("utf-8"), previous_hash.encode("utf-8")
        ):
            return {"valid": False, "broken_at": entry.id}
        expected = calculate_audit_hash(
            entry.prev_hash,
            ts=entry.ts,
            tenant_id=entry.tenant_id,
            actor_type=entry.actor_type,
            actor_id=entry.actor_id,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            payload=entry.payload,
        )
        if not hmac.compare_digest(expected.encode("utf-8"), str(entry.hash).encode("utf-8")):
            return {"valid": False, "broken_at": entry.id}
        previous_hash = entry.hash
    return {"valid": True}


class AuditService:
    def log(
        self,
        *,
        actor_type: str,
        actor_id: str | None,
        action: str,
        entity_type: str | None,
        entity_id: str | None,
        payload: dict[str, Any],
        tenant_id: str | None,
    ) -> AuditLog:
        """Append one audit row in the caller's transaction; never commit here."""
        db.session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": _AUDIT_ADVISORY_LOCK},
        )
        previous = db.session.execute(
            select(AuditLog.hash).order_by(desc(AuditLog.id)).limit(1)
        ).scalar_one_or_none()
        previous_hash = previous or _GENESIS_HASH
        timestamp = datetime.now(timezone.utc)

        digest = calculate_audit_hash(
            previous_hash,
            ts=timestamp,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )

        entry = AuditLog(
            ts=timestamp,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=str(actor_id) if actor_id is not None else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            payload=payload,
            prev_hash=previous_hash,
            hash=digest,
        )
        db.session.add(entry)
        db.session.flush()
        return entry


audit = AuditService()
