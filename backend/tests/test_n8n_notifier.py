from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.extensions import db
from app.services import n8n_notifier


def test_notify_n8n_is_noop_when_webhook_is_not_configured(monkeypatch):
    post = MagicMock()
    monkeypatch.setenv("N8N_WEBHOOK_URL", "")
    if n8n_notifier.requests is not None:
        monkeypatch.setattr(n8n_notifier.requests, "post", post)

    n8n_notifier.notify_n8n("case.approved", {"case_id": "case-1"})

    post.assert_not_called()


def test_notify_n8n_sends_payload_and_suppresses_demo_email(monkeypatch):
    post = MagicMock()
    monkeypatch.setenv("N8N_WEBHOOK_URL", "https://n8n.example.test/hook")
    monkeypatch.setattr(n8n_notifier, "requests", SimpleNamespace(post=post))
    payload = {"case_id": "case-1", "recipient_email": "citizen@demo.pk"}

    n8n_notifier.notify_n8n("case.approved", payload)

    post.assert_called_once_with(
        "https://n8n.example.test/hook",
        json={"event": "case.approved", "case_id": "case-1", "recipient_email": None},
        timeout=2,
    )
    assert payload["recipient_email"] == "citizen@demo.pk"  # caller payload is unchanged


def test_notify_n8n_swallows_webhook_failures(monkeypatch):
    post = MagicMock(side_effect=TimeoutError("offline"))
    monkeypatch.setenv("N8N_WEBHOOK_URL", "https://n8n.example.test/hook")
    monkeypatch.setattr(n8n_notifier, "requests", SimpleNamespace(post=post))

    n8n_notifier.notify_n8n("case.human_review", {})

    post.assert_called_once()


def test_notify_n8n_uses_bounded_stdlib_fallback_if_requests_is_unavailable(monkeypatch):
    response = MagicMock()
    opened = MagicMock()
    opened.return_value.__enter__.return_value = response
    monkeypatch.setenv("N8N_WEBHOOK_URL", "https://n8n.example.test/hook")
    monkeypatch.setattr(n8n_notifier, "requests", None)
    monkeypatch.setattr(n8n_notifier.urllib_request, "urlopen", opened)

    n8n_notifier.notify_n8n("case.approved", {"case_id": "case-1"})

    request = opened.call_args.args[0]
    assert request.full_url == "https://n8n.example.test/hook"
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert opened.call_args.kwargs == {"timeout": 2}


def test_case_notification_selects_event_and_rule_amount(monkeypatch):
    monkeypatch.setenv("N8N_WEBHOOK_URL", "https://n8n.example.test/hook")
    citizen = SimpleNamespace(id=str(uuid4()), user_id=str(uuid4()), full_name="Test Citizen")
    user = SimpleNamespace(email="citizen@example.test")
    rule = SimpleNamespace(definition={"amount": 25000})
    query_results = [citizen, user, rule]
    queries = []

    class Query:
        def filter_by(self, **_kwargs):
            return self

        def first(self):
            return query_results.pop(0)

    session = MagicMock()
    session.query.side_effect = lambda _model: (queries.append(_model) or Query())
    monkeypatch.setattr(db, "session", session)
    send = MagicMock()
    monkeypatch.setattr(n8n_notifier, "notify_n8n", send)
    case = SimpleNamespace(id=str(uuid4()), citizen_id=citizen.id, tenant_id=str(uuid4()))
    decision = SimpleNamespace(
        route="human_review", outcome="human_review", rule_version_id=str(uuid4()),
        reason_en="Officer review needed.", reason_ur="افسر کا جائزہ درکار ہے۔",
    )

    n8n_notifier.notify_case_decision(case, decision)

    send.assert_called_once_with("case.human_review", {
        "citizen_name": "Test Citizen", "case_id": case.id, "status": "in_review",
        "amount": 25000, "reason_en": decision.reason_en,
        "reason_ur": decision.reason_ur, "recipient_email": user.email,
    })


def test_officer_rejection_notification_includes_the_written_reason(monkeypatch):
    monkeypatch.setenv("N8N_WEBHOOK_URL", "https://n8n.example.test/hook")
    citizen = SimpleNamespace(id=str(uuid4()), user_id=str(uuid4()), full_name="Test Citizen")
    user = SimpleNamespace(email="citizen@example.test")
    rule = SimpleNamespace(definition={"amount": 25000})
    query_results = [citizen, user, rule]

    class Query:
        def filter_by(self, **_kwargs):
            return self

        def first(self):
            return query_results.pop(0)

    session = MagicMock()
    session.query.side_effect = lambda _model: Query()
    monkeypatch.setattr(db, "session", session)
    send = MagicMock()
    monkeypatch.setattr(n8n_notifier, "notify_n8n", send)
    case = SimpleNamespace(id=str(uuid4()), citizen_id=citizen.id, tenant_id=str(uuid4()))
    decision = SimpleNamespace(
        actor_type="officer", outcome="rejected", route=None,
        rule_version_id=str(uuid4()), reason_en="Generic rejection.",
        reason_ur="عام وجہ۔", trace={"note": "Monthly income is above the limit."},
    )

    n8n_notifier.notify_case_decision(case, decision)

    send.assert_called_once_with("case.rejected", {
        "citizen_name": "Test Citizen", "case_id": case.id, "status": "rejected",
        "amount": 25000, "reason_en": "Monthly income is above the limit.",
        "reason_ur": "Monthly income is above the limit.",
        "recipient_email": user.email,
        "officer_note": "Monthly income is above the limit.",
    })


def test_scam_notification_only_sends_for_scam_label(monkeypatch):
    send = MagicMock()
    monkeypatch.setattr(n8n_notifier, "notify_n8n", send)
    user = SimpleNamespace(full_name="Test Citizen", email="citizen@example.test")
    unsure = SimpleNamespace(label="unsure", advice_en="", advice_ur="")
    scam = SimpleNamespace(label="scam", advice_en="Do not click.", advice_ur="کلک نہ کریں۔")

    n8n_notifier.notify_scam_detected(user, unsure)
    send.assert_not_called()

    n8n_notifier.notify_scam_detected(user, scam)
    send.assert_called_once_with("scam.detected", {
        "citizen_name": user.full_name, "case_id": "SCAM-ALERT", "status": "scam",
        "amount": 0, "reason_en": scam.advice_en, "reason_ur": scam.advice_ur,
        "recipient_email": user.email,
    })
