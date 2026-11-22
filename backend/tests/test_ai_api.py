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
