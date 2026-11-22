from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from flask import Flask

from app import auth as auth_module
from app.api.ai import ai_bp
from app.auth import register_auth_error_handler
from app.extensions import db
from app.services import scam_service
from app.services.scam_service import ScamCheckError


def _result(label="scam"):
    return {
        "label": label,
        "confidence": 0.97,
        "category": "fake_relief",
        "reasons": ["Requests a CNIC and PIN through an unfamiliar link."],
        "advice_en": "Do not click the link.",
        "advice_ur": "لنک پر کلک نہ کریں۔",
    }


def test_logged_in_scam_check_persists_audits_and_notifies_after_commit(monkeypatch):
    actor = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()), full_name="Demo User", email="user@example.org", is_active=True)
    app = Flask(__name__)
    app.config.update(TESTING=True, SCAM_CHECKER=lambda _text: _result())
    register_auth_error_handler(app)
    app.register_blueprint(ai_bp, url_prefix="/api/v1/ai")
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": actor.id})
    session = MagicMock()
    session.get.return_value = actor
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(scam_service.audit, "log", MagicMock())

    def assert_notify_after_commit(user, result):
        assert user is actor
        assert result.label == "scam"
        assert session.commit.call_count == 1

    notify = MagicMock(side_effect=assert_notify_after_commit)
    monkeypatch.setattr(scam_service, "notify_scam_detected", notify)
    response = app.test_client().post(
        "/api/v1/ai/scam-check",
        json={"text": "Claim relief now, send your CNIC and PIN."},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.json["data"] == _result()
    assert response.json["error"] is None
    message = session.add.call_args.args[0]
    assert message.text == "Claim relief now, send your CNIC and PIN."
    assert message.label == "scam"
    assert message.reported_by == actor.id
    assert scam_service.audit.log.call_args.kwargs["action"] == "ai.scam_check"
    session.commit.assert_called_once_with()
    notify.assert_called_once()


@pytest.mark.parametrize("label", ["legit", "unsure"])
def test_logged_in_scam_check_does_not_notify_non_scam_results(label, monkeypatch):
    actor = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()))
    app = Flask(__name__)
    app.config.update(TESTING=True, SCAM_CHECKER=lambda _text: _result(label))
    with app.app_context():
        monkeypatch.setattr(db, "session", MagicMock())
        monkeypatch.setattr(scam_service.audit, "log", MagicMock())
        notify = MagicMock()
        monkeypatch.setattr(scam_service, "notify_scam_detected", notify)

        result = scam_service.check_scam(actor, "A verified public notice.")

    assert result["label"] == label
    notify.assert_not_called()


def test_logged_in_scam_check_fails_closed_when_classifier_unavailable():
    actor = SimpleNamespace(id=str(uuid4()), tenant_id=str(uuid4()))
    app = Flask(__name__)
    with app.app_context(), pytest.raises(ScamCheckError) as exc:
        scam_service.check_scam(actor, "message")

    assert exc.value.code == "AI_UNAVAILABLE"
    assert exc.value.status_code == 502


def test_ai_rate_limit_is_per_user_and_shared_across_ai_routes(monkeypatch):
    actor = SimpleNamespace(
        id=str(uuid4()), tenant_id=str(uuid4()), role="citizen", is_active=True,
        full_name="Demo User", email="user@example.test",
    )
    other_actor = SimpleNamespace(
        id=str(uuid4()), tenant_id=str(uuid4()), role="citizen", is_active=True,
        full_name="Other Demo User", email="other@example.test",
    )
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SCAM_CHECKER=lambda _text: _result("legit"),
        RATE_LIMIT_AI_COUNT=2,
        RATE_LIMIT_AI_WINDOW_SECONDS=60,
    )
    register_auth_error_handler(app)
    app.register_blueprint(ai_bp, url_prefix="/api/v1/ai")
    users = {actor.id: actor, other_actor.id: other_actor}
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda token: {
        "sub": actor.id if token == "user-one" else other_actor.id,
    })
    session = MagicMock()
    session.get.side_effect = lambda _model, user_id: users[user_id]
    monkeypatch.setattr(db, "session", session)
    monkeypatch.setattr(scam_service.audit, "log", MagicMock())
    monkeypatch.setattr("app.api.ai.audit.log", MagicMock())
    monkeypatch.setattr("app.api.ai.answer_policy_question", lambda *_args: {
        "answer": "Use the official office.", "sources": [], "confidence": 0.8, "handoff": False,
    })
    extractor = MagicMock(return_value={"form": {}, "missing_fields": [], "confidence": 0.0})
    monkeypatch.setattr("app.api.ai.extract_form", extractor)
    clock = [100.0]
    monkeypatch.setattr("app.api.ai.time.monotonic", lambda: clock[0])
    client = app.test_client()
    headers = {"Authorization": "Bearer user-one"}

    first = client.post("/api/v1/ai/scam-check", json={"text": "Notice"}, headers=headers)
    second = client.post("/api/v1/ai/ask", json={"question": "Where can I ask?"}, headers=headers)
    third = client.post("/api/v1/ai/extract-form", json={"text": "My name is Fatima"}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json["error"]["code"] == "RATE_LIMITED"
    assert int(third.headers["Retry-After"]) > 0

    other_user = client.post(
        "/api/v1/ai/scam-check", json={"text": "Notice"},
        headers={"Authorization": "Bearer user-two"},
    )
    assert other_user.status_code == 200

    clock[0] += 61
    after_window = client.post(
        "/api/v1/ai/extract-form", json={"text": "My name is Fatima"}, headers=headers,
    )
    assert after_window.status_code == 200
    extractor.assert_called_once()
