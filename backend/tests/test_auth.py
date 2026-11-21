from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import jwt
import pytest
from flask import Flask, jsonify

from app import auth as auth_module
from app.api.auth import auth_bp
from app.auth import (
    AuthenticationError,
    register_auth_error_handler,
    require_auth,
    require_role,
)
from app.extensions import db
from app.services import audit as audit_module


@pytest.fixture
def app():
    flask_app = Flask(__name__)
    flask_app.config.update(
        TESTING=True,
        SUPABASE_JWKS_URL=None,
        SUPABASE_JWT_SECRET=None,
    )
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    return flask_app


@pytest.fixture
def profile():
    return SimpleNamespace(
        id=str(uuid4()),
        tenant_id=str(uuid4()),
        email="citizen@example.test",
        full_name="Test Citizen",
        role="citizen",
        language="ur",
        is_active=True,
    )


def test_decode_token_uses_hs256_secret_and_authenticated_audience(app):
    secret = "test-only-jwt-secret-32-bytes-minimum"
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "aud": "authenticated",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )
    app.config["SUPABASE_JWT_SECRET"] = secret

    with app.app_context():
        claims = auth_module._decode_access_token(token)

    assert claims["aud"] == "authenticated"


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": str(uuid4()), "aud": "authenticated"},  # missing exp
        {
            "sub": str(uuid4()),
            "aud": "other",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        {
            "sub": str(uuid4()),
            "aud": "authenticated",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
    ],
)
def test_decode_token_rejects_missing_exp_wrong_audience_and_expired_token(app, claims):
    secret = "test-only-jwt-secret-32-bytes-minimum"
    token = jwt.encode(claims, secret, algorithm="HS256")
    app.config["SUPABASE_JWT_SECRET"] = secret

    with app.app_context(), pytest.raises(AuthenticationError) as exc:
        auth_module._decode_access_token(token)

    assert exc.value.code == "UNAUTHENTICATED"
    assert exc.value.status_code == 401


def test_decode_token_prefers_jwks_when_configured(app, monkeypatch):
    token = "signed-token"
    key = SimpleNamespace(key="public-key", algorithm_name="RS256")
    client = MagicMock()
    client.get_signing_key_from_jwt.return_value = key
    decode = MagicMock(return_value={"sub": str(uuid4())})
    monkeypatch.setattr(auth_module, "_jwks_client", lambda _url: client)
    monkeypatch.setattr(auth_module.jwt, "decode", decode)
    app.config.update(
        SUPABASE_JWKS_URL="https://auth.example.test/.well-known/jwks.json",
        SUPABASE_JWT_SECRET="legacy-secret",
    )

    with app.app_context():
        auth_module._decode_access_token(token)

    client.get_signing_key_from_jwt.assert_called_once_with(token)
    assert decode.call_args.args[:2] == (token, "public-key")
    assert decode.call_args.kwargs["algorithms"] == ["RS256"]
    assert decode.call_args.kwargs["audience"] == "authenticated"


def test_decode_token_rejects_when_verification_is_not_configured(app):
    with app.app_context(), pytest.raises(AuthenticationError) as exc:
        auth_module._decode_access_token("any-token")

    assert exc.value.code == "UNAUTHENTICATED"


def test_auth_me_loads_role_and_tenant_from_database(app, profile, monkeypatch):
    monkeypatch.setattr(
        auth_module, "_decode_access_token", lambda _token: {"sub": profile.id, "role": "admin"}
    )
    get = MagicMock(return_value=profile)
    monkeypatch.setattr(db.session, "get", get)

    response = app.test_client().get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer valid-token"}
    )

    assert response.status_code == 200
    assert response.json["error"] is None
    assert response.json["data"]["user"]["role"] == "citizen"
    assert response.json["data"]["user"]["tenant_id"] == profile.tenant_id
    get.assert_called_once()


def test_auth_me_rejects_missing_bearer_token(app):
    response = app.test_client().get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json == {
        "data": None,
        "error": {
            "code": "UNAUTHENTICATED",
            "message": "A bearer access token is required.",
            "details": {},
        },
    }


def test_auth_me_rejects_unknown_or_inactive_user(app, profile, monkeypatch):
    monkeypatch.setattr(
        auth_module, "_decode_access_token", lambda _token: {"sub": profile.id}
    )
    monkeypatch.setattr(db.session, "get", lambda *_args: None)
    response = app.test_client().get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer valid-token"}
    )
    assert response.status_code == 401

    profile.is_active = False
    monkeypatch.setattr(db.session, "get", lambda *_args: profile)
    response = app.test_client().get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer valid-token"}
    )
    assert response.status_code == 401


def test_require_role_uses_database_role_not_jwt_claim(app, profile, monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "_decode_access_token",
        lambda _token: {"sub": profile.id, "role": "admin"},
    )
    monkeypatch.setattr(db.session, "get", lambda *_args: profile)

    @app.get("/admin-only")
    @require_role("admin")
    def admin_only():
        return jsonify({"ok": True})

    response = app.test_client().get(
        "/admin-only", headers={"Authorization": "Bearer valid-token"}
    )

    assert response.status_code == 403
    assert response.json["error"]["code"] == "FORBIDDEN_ROLE"


def test_auth_session_audits_successful_login_and_commits(app, profile, monkeypatch):
    monkeypatch.setattr(
        auth_module, "_decode_access_token", lambda _token: {"sub": profile.id}
    )
    monkeypatch.setattr(db.session, "get", lambda *_args: profile)
    commit = MagicMock()
    monkeypatch.setattr(db.session, "commit", commit)
    log = MagicMock()
    monkeypatch.setattr(audit_module.audit, "log", log)

    response = app.test_client().post(
        "/api/v1/auth/session", headers={"Authorization": "Bearer valid-token"}
    )

    assert response.status_code == 200
    assert response.json["data"]["user"]["id"] == profile.id
    log.assert_called_once_with(
        actor_type="user",
        actor_id=profile.id,
        action="auth.login",
        entity_type="user",
        entity_id=profile.id,
        payload={},
        tenant_id=profile.tenant_id,
    )
    commit.assert_called_once_with()
