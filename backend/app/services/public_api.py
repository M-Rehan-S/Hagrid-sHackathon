"""API-key authentication and tenant-scoped public read/check operations."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import deque
from functools import wraps
from threading import RLock

from flask import current_app, g, request

from app.extensions import db
from app.models.api_key import APIKey
from app.models.case import Case
from app.schemas.public_api import ScamCheckResult


class PublicAPIError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


_rate_lock = RLock()
_request_times: dict[str, deque[float]] = {}


def authenticate_api_key(raw_key: str | None) -> APIKey:
    if not raw_key or len(raw_key) < 8:
        raise PublicAPIError("UNAUTHENTICATED", "A valid API key is required.", 401)
    candidates = db.session.query(APIKey).filter_by(
        key_prefix=raw_key[:8], revoked_at=None
    ).all()
    supplied_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    for candidate in candidates:
        if hmac.compare_digest(str(candidate.key_hash), supplied_hash):
            return candidate
    raise PublicAPIError("UNAUTHENTICATED", "A valid API key is required.", 401)


def require_public_api_key(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        key = request.headers.get("X-API-Key", "")
        g.public_api_key = authenticate_api_key(key)
        return view(*args, **kwargs)
    return wrapped


def enforce_public_rate_limit() -> None:
    key = str(g.public_api_key.id)
    limit = int(current_app.config.get("RATE_LIMIT_PUBLIC_COUNT", 60))
    window = int(current_app.config.get("RATE_LIMIT_PUBLIC_WINDOW_SECONDS", 60))
    if limit < 1 or window < 1:
        raise PublicAPIError("INTERNAL_ERROR", "Public API rate limiting is misconfigured.", 500)
    now = time.monotonic()
    with _rate_lock:
        events = _request_times.setdefault(key, deque())
        while events and now - events[0] >= window:
            events.popleft()
        if len(events) >= limit:
            raise PublicAPIError("RATE_LIMITED", "This API key has reached its request limit.", 429)
        events.append(now)


def public_case_status(api_key: APIKey, case_id: str) -> dict:
    case = db.session.query(Case).filter_by(
        id=case_id, tenant_id=str(api_key.tenant_id)
    ).first()
    if case is None:
        raise PublicAPIError("NOT_FOUND", "Case was not found.", 404)
    updated_at = case.updated_at
    if updated_at is not None:
        updated_at = updated_at.isoformat()
        if updated_at.endswith("+00:00"):
            updated_at = updated_at[:-6] + "Z"
    return {
        "status": getattr(case.status, "value", case.status),
        "updated_at": updated_at,
    }


def public_scam_check(api_key: APIKey, text: str) -> dict:
    # Person C's classifier is injected by the AI integration. Never substitute
    # an untrained guess if that dependency is unavailable.
    checker = current_app.config.get("SCAM_CHECKER")
    if not callable(checker):
        raise PublicAPIError("AI_UNAVAILABLE", "Scam checking is temporarily unavailable.", 502)
    try:
        result = ScamCheckResult.model_validate(checker(text))
    except PublicAPIError:
        raise
    except Exception as exc:
        raise PublicAPIError("AI_UNAVAILABLE", "Scam checking is temporarily unavailable.", 502) from exc
    return result.model_dump()
