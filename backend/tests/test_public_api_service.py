from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from flask import Flask, g

from app.extensions import db
from app.models.api_key import APIKey
from app.services import public_api
from app.services.public_api import PublicAPIError


def test_api_key_auth_uses_prefix_hash_and_ignores_revoked_keys(monkeypatch):
    raw_key = "pk_live_" + "x" * 40
    active = SimpleNamespace(
        id=str(uuid4()), key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
        tenant_id=str(uuid4()), revoked_at=None,
    )
    query = MagicMock()
    query.filter_by.return_value.all.return_value = [active]
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(db, "session", session)

    assert public_api.authenticate_api_key(raw_key) is active
    query.filter_by.assert_called_once_with(key_prefix=raw_key[:8], revoked_at=None)


@pytest.mark.parametrize("raw_key", [None, "", "short"])
def test_api_key_auth_rejects_missing_or_short_key(raw_key):
    with pytest.raises(PublicAPIError) as exc:
        public_api.authenticate_api_key(raw_key)
    assert exc.value.code == "UNAUTHENTICATED"


def test_public_case_status_is_tenant_scoped_and_contains_no_pii(monkeypatch):
    api_key = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()))
    case_id = str(uuid4())
    case = SimpleNamespace(status="approved", updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    query = MagicMock()
    query.filter_by.return_value.first.return_value = case
    session = MagicMock()
    session.query.return_value = query
    monkeypatch.setattr(db, "session", session)

    status = public_api.public_case_status(api_key, case_id)

    assert status == {"status": "approved", "updated_at": "2026-01-01T00:00:00Z"}
    query.filter_by.assert_called_once_with(id=case_id, tenant_id=api_key.tenant_id)
    assert set(status) == {"status", "updated_at"}


def test_public_scam_check_validates_provider_result(monkeypatch):
    app = Flask(__name__)
    app.config["SCAM_CHECKER"] = lambda _text: {
        "label": "unsure", "confidence": 0.5, "category": None,
        "reasons": ["Insufficient signal"], "advice_en": "Ask for help.",
        "advice_ur": "مدد طلب کریں۔",
    }
    with app.app_context():
        result = public_api.public_scam_check(SimpleNamespace(tenant_id="tenant"), "text")

    assert result["label"] == "unsure"
    assert result["confidence"] == 0.5


def test_public_scam_check_does_not_guess_when_classifier_missing():
    app = Flask(__name__)
    with app.app_context(), pytest.raises(PublicAPIError) as exc:
        public_api.public_scam_check(SimpleNamespace(tenant_id="tenant"), "text")
    assert exc.value.code == "AI_UNAVAILABLE"
    assert exc.value.status_code == 502


def test_public_rate_limit_is_per_api_key_and_sliding_window(monkeypatch):
    app = Flask(__name__)
    app.config.update(RATE_LIMIT_PUBLIC_COUNT=2, RATE_LIMIT_PUBLIC_WINDOW_SECONDS=60)
    one, two = str(uuid4()), str(uuid4())
    times = iter([10.0, 11.0, 12.0, 13.0])
    monkeypatch.setattr(public_api.time, "monotonic", lambda: next(times))
    with public_api._rate_lock:
        public_api._request_times.pop(one, None)
        public_api._request_times.pop(two, None)

    with app.app_context():
        g.public_api_key = SimpleNamespace(id=one)
        public_api.enforce_public_rate_limit()
        public_api.enforce_public_rate_limit()
        with pytest.raises(PublicAPIError) as exc:
            public_api.enforce_public_rate_limit()
        assert exc.value.code == "RATE_LIMITED"
        g.public_api_key = SimpleNamespace(id=two)
        public_api.enforce_public_rate_limit()
