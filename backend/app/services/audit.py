"""Append-only, hash-chained audit writer required by proposal §8.6."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select, text

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

        chain_payload = {
            "ts": timestamp.isoformat().replace("+00:00", "Z"),
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
        digest = hashlib.sha256((previous_hash + canonical).encode("utf-8")).hexdigest()

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
