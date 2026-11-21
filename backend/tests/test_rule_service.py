from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import rule_service


class _Column:
    def __init__(self, name: str):
        self.name = name

    def __eq__(self, other):
        return (self.name, "==", other)

    def __ne__(self, other):
        return (self.name, "!=", other)

    def desc(self):
        return (self.name, "desc")


class _Rule:
    id = _Column("id")
    tenant_id = _Column("tenant_id")
    rule_key = _Column("rule_key")
    version = _Column("version")
    status = _Column("status")

    def __init__(self, **values):
        self.id = values.pop("id", "new-rule-id")
        for key, value in values.items():
            setattr(self, key, value)


def _install_modules(monkeypatch, db, audit_log=None):
    ext = types.ModuleType("app.extensions")
    ext.db = db
    monkeypatch.setitem(sys.modules, "app.extensions", ext)

    models = types.ModuleType("app.models")
    models.__path__ = []
    monkeypatch.setitem(sys.modules, "app.models", models)
    rule_model = types.ModuleType("app.models.rule")
    rule_model.Rule = _Rule
    monkeypatch.setitem(sys.modules, "app.models.rule", rule_model)

    audit_mod = types.ModuleType("app.services.audit")
    audit_mod.audit = SimpleNamespace(log=audit_log or MagicMock())
    monkeypatch.setitem(sys.modules, "app.services.audit", audit_mod)
    return audit_mod.audit.log


def test_get_active_rule_scopes_by_tenant_key_and_status(monkeypatch):
    active = _Rule(id="active", tenant_id="tenant-1", rule_key="relief_eligibility")
    db = SimpleNamespace(session=MagicMock())
    db.session.query.return_value.filter_by.return_value.first.return_value = active
    _install_modules(monkeypatch, db)

    result = rule_service.get_active_rule("tenant-1", "relief_eligibility")

    assert result is active
    db.session.query.assert_called_once_with(_Rule)
    db.session.query.return_value.filter_by.assert_called_once_with(
        tenant_id="tenant-1", rule_key="relief_eligibility", status="active"
    )


def test_create_rule_draft_uses_next_version_and_audits(monkeypatch):
    current = _Rule(version=4)
    db = SimpleNamespace(session=MagicMock())
    db.session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = current
    log = _install_modules(monkeypatch, db)
    definition = {"rule_key": "relief_eligibility", "thresholds": {"auto_approve": 0.98}}

    created = rule_service.create_rule_draft(
        "tenant-1", "relief_eligibility", definition, "Updated limit", "admin-1"
    )

    assert created.version == 5
    assert created.status == "draft"
    assert created.definition is definition
    assert created.note == "Updated limit"
    assert created.created_by == "admin-1"
    db.session.add.assert_called_once_with(created)
    db.session.flush.assert_called_once_with()
    db.session.commit.assert_called_once_with()
    log.assert_called_once_with(
        actor_type="user",
        actor_id="admin-1",
        action="rule.create",
        entity_type="rule",
        entity_id="new-rule-id",
        payload={"rule_key": "relief_eligibility", "version": 5},
        tenant_id="tenant-1",
    )


def test_create_first_rule_starts_at_version_one(monkeypatch):
    db = SimpleNamespace(session=MagicMock())
    db.session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None
    _install_modules(monkeypatch, db)

    created = rule_service.create_rule_draft("tenant-1", "relief_eligibility", {}, None, "admin-1")

    assert created.version == 1


def test_activate_rule_archives_old_version_atomically_and_audits(monkeypatch):
    draft = _Rule(
        id="rule-v2",
        tenant_id="tenant-1",
        rule_key="relief_eligibility",
        version=2,
        status="draft",
    )
    db = SimpleNamespace(session=MagicMock())
    queries = [MagicMock(), MagicMock()]
    db.session.query.side_effect = queries
    queries[0].filter_by.return_value.first.return_value = draft
    log = _install_modules(monkeypatch, db)

    result = rule_service.activate_rule("rule-v2", "admin-1")

    assert result is draft
    assert draft.status == "active"
    assert draft.activated_at.tzinfo is not None
    db.session.commit.assert_called_once_with()
    queries[1].filter.assert_called_once_with(
        ("tenant_id", "==", "tenant-1"),
        ("rule_key", "==", "relief_eligibility"),
        ("status", "==", "active"),
        ("id", "!=", "rule-v2"),
    )
    queries[1].filter.return_value.update.assert_called_once_with(
        {"status": "archived"}, synchronize_session=False
    )
    log.assert_called_once_with(
        actor_type="user",
        actor_id="admin-1",
        action="rule.activate",
        entity_type="rule",
        entity_id="rule-v2",
        payload={"rule_key": "relief_eligibility", "version": 2},
        tenant_id="tenant-1",
    )


def test_activate_missing_rule_returns_none_without_audit(monkeypatch):
    db = SimpleNamespace(session=MagicMock())
    db.session.query.return_value.filter_by.return_value.first.return_value = None
    log = _install_modules(monkeypatch, db)

    assert rule_service.activate_rule("missing", "admin-1") is None
    log.assert_not_called()
    db.session.commit.assert_not_called()
