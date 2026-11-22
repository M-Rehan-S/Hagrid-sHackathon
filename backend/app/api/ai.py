"""Authenticated AI-assisted endpoints (PROPOSAL.md §7.5)."""

from __future__ import annotations

from collections import deque
from functools import wraps
from threading import RLock
import time
from typing import Any, Literal, Optional

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.ai.form_extractor import extract_form
from app.ai.rag import answer_policy_question
from app.ai.transcriber import TranscribeError, transcribe_audio
from app.auth import require_auth, require_role
from app.extensions import db
from app.schemas.public_api import PublicScamCheckRequest
from app.services.audit import audit
from app.services.scam_service import ScamCheckError, check_scam


ai_bp = Blueprint("ai", __name__)
_ai_limit_lock = RLock()
_ai_request_times: dict[str, deque[float]] = {}


def _limit_ai_requests(view):
    """Apply the proposal's per-user rolling-window limit after authentication."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = str(g.current_user.id)
        limit = int(current_app.config.get("RATE_LIMIT_AI_COUNT", 30))
        window = int(current_app.config.get("RATE_LIMIT_AI_WINDOW_SECONDS", 60))
        if limit < 1 or window < 1:
            return jsonify({
                "data": None,
                "error": {"code": "INTERNAL_ERROR", "message": "AI rate limiting is misconfigured.", "details": {}},
            }), 500

        now = time.monotonic()
        with _ai_limit_lock:
            events = _ai_request_times.setdefault(user_id, deque())
            while events and now - events[0] >= window:
                events.popleft()
            if len(events) >= limit:
                return jsonify({
                    "data": None,
                    "error": {"code": "RATE_LIMITED", "message": "AI request limit reached. Try again shortly.", "details": {}},
                }), 429, {"Retry-After": str(max(1, int(window - (now - events[0]))))}
            events.append(now)
        return view(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------------------------
# Pydantic schema for POST /ai/ask
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=5000)
    lang: Literal["ur", "en"] = "ur"

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank")
        return v


# ---------------------------------------------------------------------------
# Pydantic schema for POST /ai/extract-form
# ---------------------------------------------------------------------------

class ExtractFormRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=20000)
    lang: Literal["ur", "en"] = "ur"
    existing_form: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@ai_bp.errorhandler(ScamCheckError)
def handle_scam_check_error(error: ScamCheckError):
    return jsonify({
        "data": None,
        "error": {"code": error.code, "message": error.message, "details": {}},
    }), error.status_code


# ---------------------------------------------------------------------------
# POST /ai/scam-check  (existing endpoint, unchanged)
# ---------------------------------------------------------------------------

@ai_bp.post("/scam-check")
@require_auth
@_limit_ai_requests
def post_scam_check():
    try:
        body = PublicScamCheckRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        return jsonify({
            "data": None,
            "error": {"code": "VALIDATION_ERROR", "message": "Request body is invalid.", "details": {}},
        }), 400
    result = check_scam(g.current_user, body.text)
    return jsonify({"data": result, "error": None})


# ---------------------------------------------------------------------------
# POST /ai/ask  (RAG policy Q&A, §7.5 / §8.8)
# ---------------------------------------------------------------------------

@ai_bp.post("/ask")
@require_auth
@_limit_ai_requests
def post_ask():
    """Answer a policy question using RAG over policy_chunks (PROPOSAL.md §7.5)."""
    try:
        body = AskRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        return jsonify({
            "data": None,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "question is required and must not be blank.",
                "details": {},
            },
        }), 400

    result = answer_policy_question(body.question, body.lang)

    actor = g.current_user
    audit.log(
        actor_type="user",
        actor_id=str(actor.id),
        action="ai.rag_answer",
        entity_type="policy_chunks",
        entity_id=None,
        payload={
            "question_len": len(body.question),
            "lang": body.lang,
            "confidence": result.get("confidence"),
            "handoff": result.get("handoff"),
            "source_count": len(result.get("sources", [])),
        },
        tenant_id=str(actor.tenant_id),
    )
    db.session.commit()

    return jsonify({"data": result, "error": None})


# ---------------------------------------------------------------------------
# POST /ai/extract-form  (§7.5)
# ---------------------------------------------------------------------------

@ai_bp.post("/extract-form")
@require_role("citizen", "helper")
@_limit_ai_requests
def post_extract_form():
    """Extract ClaimForm fields from free-form text (PROPOSAL.md §7.5)."""
    raw_body = request.get_json(silent=True) or {}
    try:
        body = ExtractFormRequest.model_validate(raw_body)
    except ValidationError as exc:
        return jsonify({
            "data": None,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request body is invalid.",
                "details": {"errors": exc.errors(include_url=False)},
            },
        }), 400

    result = extract_form(body.text, body.lang, body.existing_form)

    actor = g.current_user
    audit.log(
        actor_type="user",
        actor_id=str(actor.id),
        action="ai.extract_form",
        entity_type="claim_form",
        entity_id=None,
        payload={
            "lang": body.lang,
            "confidence": result.get("confidence"),
            "missing_fields": result.get("missing_fields"),
            "text_len": len(body.text),
        },
        tenant_id=str(actor.tenant_id),
    )
    db.session.commit()

    return jsonify({"data": result, "error": None})


# ---------------------------------------------------------------------------
# POST /ai/transcribe  (§7.5)
# ---------------------------------------------------------------------------

@ai_bp.post("/transcribe")
@require_role("citizen", "helper")
@_limit_ai_requests
def post_transcribe():
    """Transcribe audio to text via Whisper (PROPOSAL.md §7.5)."""
    if "audio" not in request.files:
        return jsonify({
            "data": None,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "audio file is required.",
                "details": {},
            },
        }), 400

    audio_file = request.files["audio"]
    lang = request.form.get("lang", "ur").strip() or "ur"

    try:
        audio_bytes = audio_file.read()
        result = transcribe_audio(audio_bytes, audio_file.filename or "audio.mp3", lang)
    except TranscribeError as exc:
        return jsonify({
            "data": None,
            "error": {"code": exc.code, "message": exc.message, "details": {}},
        }), exc.status_code

    actor = g.current_user
    audit.log(
        actor_type="user",
        actor_id=str(actor.id),
        action="ai.transcribe",
        entity_type="audio_transcript",
        entity_id=None,
        payload={
            "lang": lang,
            "confidence": result.get("confidence"),
            "audio_size_bytes": len(audio_bytes),
            "filename": audio_file.filename or "audio.mp3",
        },
        tenant_id=str(actor.tenant_id),
    )
    db.session.commit()

    return jsonify({"data": result, "error": None})
