"""Database operations for versioned eligibility rules.

Rule names and lifecycle behavior follow PROPOSAL.md §§5, 7.6, and 8.4.
Rules are immutable versions: creating a rule always inserts the next version,
and activating a version archives the previous active version in one transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def get_active_rule(tenant_id: str, rule_key: str) -> Any | None:
    """Return the active version for a tenant and key, if one exists."""
    from app.extensions import db
    from app.models.rule import Rule

    return (
        db.session.query(Rule)
        .filter_by(tenant_id=tenant_id, rule_key=rule_key, status="active")
        .first()
    )


def create_rule_draft(
    tenant_id: str,
    rule_key: str,
    definition: dict[str, Any],
    note: str | None,
    created_by: str,
) -> Any:
    """Insert a new draft version, without modifying any existing version."""
    from app.extensions import db
    from app.models.rule import Rule
    from app.services.audit import audit

    latest = (
        db.session.query(Rule)
        .filter_by(tenant_id=tenant_id, rule_key=rule_key)
        .order_by(Rule.version.desc())
        .first()
    )
    version = (latest.version if latest is not None else 0) + 1
    rule = Rule(
        tenant_id=tenant_id,
        rule_key=rule_key,
        version=version,
        status="draft",
        definition=definition,
        note=note,
        created_by=created_by,
    )

    db.session.add(rule)
    db.session.flush()
    audit.log(
        actor_type="user",
        actor_id=created_by,
        action="rule.create",
        entity_type="rule",
        entity_id=str(rule.id),
        payload={"rule_key": rule_key, "version": version},
        tenant_id=tenant_id,
    )
    db.session.commit()
    return rule


def activate_rule(rule_id: str, admin_user_id: str) -> Any | None:
    """Atomically archive the active version and activate ``rule_id``.

    Returns ``None`` when the requested rule does not exist. The caller can
    map that result to the API's 404 response.
    """
    from app.extensions import db
    from app.models.rule import Rule
    from app.services.audit import audit

    activated_rule = None
    with db.session.begin():
        rule = db.session.query(Rule).filter_by(id=rule_id).first()
        if rule is None:
            return None

        db.session.query(Rule).filter(
            Rule.tenant_id == rule.tenant_id,
            Rule.rule_key == rule.rule_key,
            Rule.status == "active",
            Rule.id != rule.id,
        ).update({"status": "archived"}, synchronize_session=False)

        rule.status = "active"
        rule.activated_at = datetime.now(timezone.utc)
        audit.log(
            actor_type="user",
            actor_id=admin_user_id,
            action="rule.activate",
            entity_type="rule",
            entity_id=str(rule.id),
            payload={"rule_key": rule.rule_key, "version": rule.version},
            tenant_id=rule.tenant_id,
        )
        activated_rule = rule

    return activated_rule
