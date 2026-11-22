"""Authenticated AI-assisted endpoints (PROPOSAL.md §7.5)."""

from __future__ import annotations

from typing import Literal

from flask import Blueprint, g, jsonify, request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.ai.rag import answer_policy_question
from app.auth import require_auth
from app.extensions import db
from app.schemas.public_api import PublicScamCheckRequest
from app.services.audit import audit
from app.services.scam_service import ScamCheckError, check_scam


ai_bp = Blueprint("ai", __name__)


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

    # Audit log per §8.6 — action "ai.rag_answer"
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
