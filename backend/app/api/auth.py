"""Session introspection endpoints for Supabase Auth access tokens."""

from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify

from app.auth import require_auth
from app.extensions import limiter
from app.services.audit import audit


auth_bp = Blueprint("auth", __name__)


def _user_payload(user) -> dict:
    role = getattr(user.role, "value", user.role)
    return {
        "id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "email": user.email,
        "full_name": user.full_name,
        "role": role,
        "language": user.language,
    }


@auth_bp.post("/session")
@require_auth
@limiter.limit(
    lambda: f"{current_app.config.get('RATE_LIMIT_AUTH_SESSION_COUNT', 10)} per minute",
    override_defaults=False,
)
def create_session():
    """Validate the current Supabase token and record a successful login."""
    user = g.current_user
    audit.log(
        actor_type="user",
        actor_id=str(user.id),
        action="auth.login",
        entity_type="user",
        entity_id=str(user.id),
        payload={},
        tenant_id=str(user.tenant_id),
    )
    from app.extensions import db

    db.session.commit()
    return jsonify({"data": {"user": _user_payload(user)}, "error": None})


@auth_bp.get("/me")
@require_auth
def get_current_user():
    return jsonify({"data": {"user": _user_payload(g.current_user)}, "error": None})
