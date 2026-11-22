"""Authenticated scam-check workflow from PROPOSAL.md §7.5."""

from flask import current_app

from app.extensions import db
from app.models.scam_message import ScamMessage
from app.schemas.public_api import ScamCheckResult
from app.services.audit import audit
from app.services.n8n_notifier import notify_scam_detected


class ScamCheckError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def check_scam(actor, text: str) -> dict:
    checker = current_app.config.get("SCAM_CHECKER")
    if not callable(checker):
        raise ScamCheckError("AI_UNAVAILABLE", "Scam checking is temporarily unavailable.", 502)
    try:
        result = ScamCheckResult.model_validate(checker(text))
    except Exception as exc:
        # Do not expose provider errors or fall back to an unverified guess.
        raise ScamCheckError("AI_UNAVAILABLE", "Scam checking is temporarily unavailable.", 502) from exc

    message = ScamMessage(
        tenant_id=str(actor.tenant_id),
        text=text,
        label=result.label,
        confidence=result.confidence,
        category=result.category,
        reported_by=str(actor.id),
    )
    db.session.add(message)
    audit.log(
        actor_type="user",
        actor_id=str(actor.id),
        action="ai.scam_check",
        entity_type="scam_message",
        entity_id=None,
        payload={"label": result.label, "confidence": result.confidence, "category": result.category},
        tenant_id=str(actor.tenant_id),
    )
    db.session.commit()

    if result.label == "scam":
        notify_scam_detected(actor, result)
    return result.model_dump()
