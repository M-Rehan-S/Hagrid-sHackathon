"""Comprehensive tests for the RAG policy Q&A pipeline.

Covers PROPOSAL.md §7.5 (POST /ai/ask) and §8.6 (audit log).

Test inventory:
  1. Unauthenticated POST /ai/ask → 401 UNAUTHENTICATED
  2. Blank / missing question → 400 VALIDATION_ERROR
  3. In-policy English question → 200, handoff=False, sources cite 01_eligibility_rules.txt
  4. In-policy Urdu question → 200, Urdu answer, sources present
  5. Out-of-policy question → 200, answer=None, handoff=True
  6. Audit log confirms ai.rag_answer was written
  7. No regression: existing POST /ai/scam-check still works
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from flask import Flask

from app import auth as auth_module
from app.api.ai import ai_bp
from app.auth import register_auth_error_handler
from app.extensions import db
from app.services import scam_service
from conftest import init_test_limiter


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ACTOR_ID = str(uuid4())
TENANT_ID = str(uuid4())


def _make_actor(**kwargs):
    defaults = dict(
        id=ACTOR_ID,
        tenant_id=TENANT_ID,
        email="helper@example.test",
        full_name="Test Helper",
        role="helper",
        language="ur",
        is_active=True,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_app(monkeypatch, actor=None, mock_db=None):
    """Build a minimal Flask test app wired to ai_bp with mocked auth + DB."""
    if actor is None:
        actor = _make_actor()
    if mock_db is None:
        mock_db = MagicMock()
        mock_db.session.get.return_value = actor

    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True)
    register_auth_error_handler(flask_app)
    init_test_limiter(flask_app)
    flask_app.register_blueprint(ai_bp, url_prefix="/api/v1/ai")

    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": actor.id})
    monkeypatch.setattr(db, "session", mock_db.session)

    return flask_app, actor, mock_db


# ---------------------------------------------------------------------------
# Eligibility policy snippet used in mock RAG results
# ---------------------------------------------------------------------------

_ELIGIBILITY_SNIPPET = (
    "Eligible widows receive a one-time relief payout of PKR 25,000. "
    "Total monthly household income must be PKR 30,000 or less."
)

_ELIGIBILITY_SOURCES = [
    {
        "doc_name": "01_eligibility_rules.txt",
        "chunk_index": 1,
        "snippet": _ELIGIBILITY_SNIPPET,
    }
]

_IN_POLICY_RESULT_EN = {
    "answer": (
        "Eligible widows receive a one-time relief payout of PKR 25,000. "
        "The monthly household income limit is PKR 30,000 or less."
    ),
    "sources": _ELIGIBILITY_SOURCES,
    "confidence": 0.87,
    "handoff": False,
}

_IN_POLICY_RESULT_UR = {
    "answer": "اہل بیوائیں 25,000 روپے کی یکمشت امداد حاصل کرتی ہیں۔ گھریلو ماہانہ آمدنی 30,000 روپے یا اس سے کم ہونی چاہیے۔",
    "sources": _ELIGIBILITY_SOURCES,
    "confidence": 0.85,
    "handoff": False,
}

_OUT_OF_POLICY_RESULT = {
    "answer": None,
    "sources": [],
    "confidence": 0.1,
    "handoff": True,
}


# ---------------------------------------------------------------------------
# 1. Unauthenticated → 401
# ---------------------------------------------------------------------------

def test_unauthenticated_ask_returns_401():
    """POST /ai/ask without a bearer token must return 401 UNAUTHENTICATED."""
    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True, SUPABASE_JWKS_URL=None, SUPABASE_JWT_SECRET=None)
    register_auth_error_handler(flask_app)
    init_test_limiter(flask_app)
    flask_app.register_blueprint(ai_bp, url_prefix="/api/v1/ai")

    client = flask_app.test_client()
    response = client.post(
        "/api/v1/ai/ask",
        json={"question": "What is the income limit?"},
    )

    assert response.status_code == 401
    body = response.get_json()
    assert body["data"] is None
    assert body["error"]["code"] == "UNAUTHENTICATED"


# ---------------------------------------------------------------------------
# 2. Missing / blank question → 400
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    {},
    {"question": ""},
    {"question": "   "},
    {"lang": "en"},
])
def test_missing_or_blank_question_returns_400(payload, monkeypatch):
    flask_app, actor, mock_db = _make_app(monkeypatch)
    client = flask_app.test_client()

    response = client.post(
        "/api/v1/ai/ask",
        json=payload,
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["data"] is None
    assert body["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# 3. In-policy English question → 200, handoff=False, cites eligibility doc
# ---------------------------------------------------------------------------

def test_in_policy_english_question_returns_answer_with_sources(monkeypatch):
    """Authenticated in-policy question in English returns answer + correct sources."""
    flask_app, actor, mock_db = _make_app(monkeypatch)

    mock_audit = MagicMock()

    with (
        patch("app.api.ai.answer_policy_question", return_value=_IN_POLICY_RESULT_EN) as mock_rag,
        patch("app.api.ai.audit", mock_audit),
        patch("app.api.ai.db", mock_db),
    ):
        client = flask_app.test_client()
        response = client.post(
            "/api/v1/ai/ask",
            json={"question": "What is the income limit and payout for widows?", "lang": "en"},
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["error"] is None

    data = body["data"]
    assert data["handoff"] is False
    assert data["answer"] is not None
    assert isinstance(data["answer"], str)
    assert len(data["answer"]) > 0

    # Must cite 01_eligibility_rules.txt
    assert len(data["sources"]) >= 1
    doc_names = [s["doc_name"] for s in data["sources"]]
    assert "01_eligibility_rules.txt" in doc_names

    assert 0 <= data["confidence"] <= 1

    # RAG was called with correct args
    mock_rag.assert_called_once_with(
        "What is the income limit and payout for widows?", "en"
    )


# ---------------------------------------------------------------------------
# 4. In-policy Urdu question → 200, Urdu answer + sources
# ---------------------------------------------------------------------------

def test_in_policy_urdu_question_returns_urdu_answer_with_sources(monkeypatch):
    """Authenticated in-policy Urdu question returns Urdu-script answer + sources."""
    flask_app, actor, mock_db = _make_app(monkeypatch)

    mock_audit = MagicMock()

    with (
        patch("app.api.ai.answer_policy_question", return_value=_IN_POLICY_RESULT_UR) as mock_rag,
        patch("app.api.ai.audit", mock_audit),
        patch("app.api.ai.db", mock_db),
    ):
        client = flask_app.test_client()
        response = client.post(
            "/api/v1/ai/ask",
            json={"question": "بیواؤں کے لیے ماہانہ آمدنی کی حد کیا ہے؟", "lang": "ur"},
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["error"] is None

    data = body["data"]
    assert data["handoff"] is False
    assert data["answer"] is not None

    # Answer should contain Urdu script characters
    urdu_chars = any('\u0600' <= c <= '\u06ff' for c in data["answer"])
    assert urdu_chars, f"Expected Urdu script in answer, got: {data['answer']!r}"

    assert len(data["sources"]) >= 1

    mock_rag.assert_called_once_with(
        "بیواؤں کے لیے ماہانہ آمدنی کی حد کیا ہے؟", "ur"
    )


# ---------------------------------------------------------------------------
# 5. Out-of-policy question → 200, answer=None, handoff=True
# ---------------------------------------------------------------------------

def test_out_of_policy_question_returns_handoff(monkeypatch):
    """Out-of-policy question must return handoff=True with answer=None."""
    flask_app, actor, mock_db = _make_app(monkeypatch)

    mock_audit = MagicMock()

    with (
        patch("app.api.ai.answer_policy_question", return_value=_OUT_OF_POLICY_RESULT),
        patch("app.api.ai.audit", mock_audit),
        patch("app.api.ai.db", mock_db),
    ):
        client = flask_app.test_client()
        response = client.post(
            "/api/v1/ai/ask",
            json={"question": "Can I get a free solar panel or tractor loan?", "lang": "en"},
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["error"] is None

    data = body["data"]
    assert data["handoff"] is True
    assert data["answer"] is None
    assert data["sources"] == []


# ---------------------------------------------------------------------------
# 6. Audit log: ai.rag_answer is written
# ---------------------------------------------------------------------------

def test_audit_log_records_ai_rag_answer_action(monkeypatch):
    """POST /ai/ask must write an audit log entry with action='ai.rag_answer'."""
    flask_app, actor, mock_db = _make_app(monkeypatch)

    captured_calls: list[dict] = []

    class CapturingAudit:
        def log(self, **kwargs):
            captured_calls.append(kwargs)

    with (
        patch("app.api.ai.answer_policy_question", return_value=_IN_POLICY_RESULT_EN),
        patch("app.api.ai.audit", CapturingAudit()),
        patch("app.api.ai.db", mock_db),
    ):
        client = flask_app.test_client()
        response = client.post(
            "/api/v1/ai/ask",
            json={"question": "What documents do I need?", "lang": "en"},
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 200

    # Verify audit.log was called with action "ai.rag_answer"
    assert len(captured_calls) == 1, f"Expected 1 audit call, got {len(captured_calls)}"
    call = captured_calls[0]
    assert call["action"] == "ai.rag_answer"
    assert call["actor_type"] == "user"
    assert call["actor_id"] == actor.id
    assert call["tenant_id"] == actor.tenant_id
    assert call["entity_type"] == "policy_chunks"
    assert "confidence" in call["payload"]
    assert "handoff" in call["payload"]
    assert "lang" in call["payload"]


# ---------------------------------------------------------------------------
# 7. Regression: existing POST /ai/scam-check still works
# ---------------------------------------------------------------------------

def test_scam_check_regression(monkeypatch):
    """POST /ai/scam-check must still function correctly (zero regressions)."""
    actor = _make_actor()
    mock_db = MagicMock()
    mock_db.session.get.return_value = actor

    scam_result = {
        "label": "scam",
        "confidence": 0.95,
        "category": "fake_relief",
        "reasons": ["Asks for CNIC and bank PIN"],
        "advice_en": "Do not share your PIN.",
        "advice_ur": "اپنا پن شیئر نہ کریں۔",
    }

    flask_app = Flask(__name__)
    flask_app.config.update(TESTING=True, SCAM_CHECKER=lambda _text: scam_result)
    register_auth_error_handler(flask_app)
    init_test_limiter(flask_app)
    flask_app.register_blueprint(ai_bp, url_prefix="/api/v1/ai")

    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": actor.id})
    monkeypatch.setattr(db, "session", mock_db.session)
    monkeypatch.setattr(scam_service.audit, "log", MagicMock())

    notify = MagicMock()
    monkeypatch.setattr(scam_service, "notify_scam_detected", notify)

    response = flask_app.test_client().post(
        "/api/v1/ai/scam-check",
        json={"text": "Win relief money now. Send CNIC and PIN to claim."},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["error"] is None
    assert body["data"]["label"] == "scam"
    assert body["data"]["confidence"] == 0.95


# ---------------------------------------------------------------------------
# 8. RAG unit test: answer_policy_question handoff on empty table
# ---------------------------------------------------------------------------

def test_rag_returns_handoff_when_table_empty(monkeypatch):
    """answer_policy_question returns handoff=True when policy_chunks is empty."""
    from app.ai import rag as rag_module

    mock_session = MagicMock()
    mock_session.execute.return_value.scalar_one.return_value = 0  # row_count = 0

    monkeypatch.setattr(db, "session", mock_session)

    result = rag_module.answer_policy_question("What is the payout?", "en")

    assert result["handoff"] is True
    assert result["answer"] is None
    assert result["sources"] == []


# ---------------------------------------------------------------------------
# 9. RAG unit test: handoff when top score below threshold
# ---------------------------------------------------------------------------

def test_rag_returns_handoff_when_score_below_threshold(monkeypatch):
    """answer_policy_question returns handoff=True when similarity is below threshold."""
    from app.ai import rag as rag_module
    from app.ai import embeddings as emb_module

    # Fake a 768-dim zero-ish vector
    fake_vec = [0.0] * 768
    fake_vec[0] = 1.0  # L2-norm = 1

    mock_session = MagicMock()
    # row_count > 0
    mock_session.execute.return_value.scalar_one.return_value = 10

    # second execute call returns rows with low score
    low_score_row = ("01_eligibility_rules.txt", 0, "Some content", 0.10)
    mock_session.execute.return_value.fetchall.return_value = [low_score_row]

    monkeypatch.setattr(db, "session", mock_session)
    monkeypatch.setattr(emb_module, "embed", lambda _text: fake_vec)
    monkeypatch.setattr(emb_module, "_active_provider", "sparse")

    result = rag_module.answer_policy_question("solar panel loan tractor", "en")

    assert result["handoff"] is True
    assert result["answer"] is None


# ---------------------------------------------------------------------------
# 10. RAG unit test: LLM NO_ANSWER sentinel → handoff
# ---------------------------------------------------------------------------

def test_rag_returns_handoff_when_llm_returns_no_answer(monkeypatch):
    """answer_policy_question returns handoff=True when LLM returns NO_ANSWER."""
    from app.ai import rag as rag_module
    from app.ai import embeddings as emb_module
    import app.ai.llm_client as llm_module

    fake_vec = [1.0 / (768 ** 0.5)] * 768  # L2-normalised

    mock_session = MagicMock()
    mock_session.execute.return_value.scalar_one.return_value = 10

    high_score_row = ("01_eligibility_rules.txt", 0, "Widows receive PKR 25,000.", 0.85)
    mock_session.execute.return_value.fetchall.return_value = [high_score_row]

    monkeypatch.setattr(db, "session", mock_session)
    monkeypatch.setattr(emb_module, "embed", lambda _text: fake_vec)
    monkeypatch.setattr(emb_module, "_active_provider", "gemini")
    monkeypatch.setattr(llm_module, "chat", lambda _sys, _usr: "NO_ANSWER")

    result = rag_module.answer_policy_question("Can I get a tractor loan?", "en")

    assert result["handoff"] is True
    assert result["answer"] is None


# ---------------------------------------------------------------------------
# 11. Default lang is "ur"
# ---------------------------------------------------------------------------

def test_default_lang_is_ur(monkeypatch):
    """POST /ai/ask without lang defaults to 'ur'."""
    flask_app, actor, mock_db = _make_app(monkeypatch)

    captured_args: list = []

    def fake_rag(question, lang):
        captured_args.append((question, lang))
        return _IN_POLICY_RESULT_UR

    mock_audit = MagicMock()

    with (
        patch("app.api.ai.answer_policy_question", side_effect=fake_rag),
        patch("app.api.ai.audit", mock_audit),
        patch("app.api.ai.db", mock_db),
    ):
        client = flask_app.test_client()
        response = client.post(
            "/api/v1/ai/ask",
            json={"question": "What is the payout amount?"},
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 200
    assert captured_args == [("What is the payout amount?", "ur")]


# ---------------------------------------------------------------------------
# 12. Invalid lang value → 400
# ---------------------------------------------------------------------------

def test_invalid_lang_returns_400(monkeypatch):
    flask_app, actor, mock_db = _make_app(monkeypatch)
    client = flask_app.test_client()

    response = client.post(
        "/api/v1/ai/ask",
        json={"question": "What is the income limit?", "lang": "fr"},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
