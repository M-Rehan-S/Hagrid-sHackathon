"""Tenant-scoped administrative API key lifecycle."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from app.extensions import db
from app.models.api_key import APIKey
from app.services.audit import audit


def _payload(key: APIKey) -> dict:
    return {
        "id": str(key.id),
        "label": key.label,
        "key_prefix": key.key_prefix,
        "created_at": key.created_at.isoformat().replace("+00:00", "Z") if key.created_at else None,
        "revoked_at": key.revoked_at.isoformat().replace("+00:00", "Z") if key.revoked_at else None,
    }


def create_api_key(actor, label: str) -> dict:
    full_key = f"lmk_{secrets.token_urlsafe(32)}"
    key = APIKey(
        tenant_id=str(actor.tenant_id),
        label=label,
        key_prefix=full_key[:8],
        key_hash=hashlib.sha256(full_key.encode("utf-8")).hexdigest(),
        created_by=str(actor.id),
    )
    db.session.add(key)
    db.session.flush()
    audit.log(
        actor_type="user",
        actor_id=str(actor.id),
        action="apikey.create",
        entity_type="api_key",
        entity_id=str(key.id),
        payload={"label": key.label, "key_prefix": key.key_prefix},
        tenant_id=str(actor.tenant_id),
    )
    db.session.commit()
    return {**_payload(key), "api_key": full_key}


def list_api_keys(actor) -> list[dict]:
    rows = (
        db.session.query(APIKey)
        .filter_by(tenant_id=str(actor.tenant_id))
        .order_by(APIKey.created_at.desc())
        .all()
    )
    return [_payload(row) for row in rows]


def revoke_api_key(actor, key_id: str) -> dict | None:
    key = db.session.query(APIKey).filter_by(
        id=key_id, tenant_id=str(actor.tenant_id)
    ).first()
    if key is None:
        return None
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        audit.log(
            actor_type="user",
            actor_id=str(actor.id),
            action="apikey.revoke",
            entity_type="api_key",
            entity_id=str(key.id),
            payload={"label": key.label, "key_prefix": key.key_prefix},
            tenant_id=str(actor.tenant_id),
        )
        db.session.commit()
    return _payload(key)
