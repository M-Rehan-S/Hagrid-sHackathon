from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock

from app.models.audit_log import AuditLog
from app.services.audit import AuditService


def test_audit_log_builds_canonical_hash_and_leaves_commit_to_caller(monkeypatch):
    import app.services.audit as audit_module

    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = "a" * 64
    monkeypatch.setattr(audit_module.db, "session", session)
    payload = {"route": "human_review", "confidence": 0.5}

    entry = AuditService().log(
        actor_type="ai",
        actor_id=None,
        action="ai.decision",
        entity_type="case",
        entity_id="case-1",
        payload=payload,
        tenant_id="tenant-1",
    )

    canonical_payload = {
        "ts": entry.ts.isoformat().replace("+00:00", "Z"),
        "tenant_id": "tenant-1",
        "actor_type": "ai",
        "actor_id": None,
        "action": "ai.decision",
        "entity_type": "case",
        "entity_id": "case-1",
        "payload": payload,
    }
    canonical = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    expected_hash = hashlib.sha256(("a" * 64 + canonical).encode("utf-8")).hexdigest()

    assert isinstance(entry, AuditLog)
    assert entry.prev_hash == "a" * 64
    assert entry.hash == expected_hash
    session.execute.assert_called()
    session.add.assert_called_once_with(entry)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()
