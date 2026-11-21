"""Authentication helpers for Supabase-issued access tokens."""

from __future__ import annotations

from functools import lru_cache, wraps
from uuid import UUID

import jwt
from flask import Flask, current_app, g, jsonify, request
from jwt import PyJWKClient, PyJWKClientConnectionError
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models.user import User


class AuthenticationError(Exception):
    """An authentication or authorization error safe to return to clients."""

    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def register_auth_error_handler(app: Flask) -> None:
    @app.errorhandler(AuthenticationError)
    def handle_authentication_error(error: AuthenticationError):
        return jsonify({
            "data": None,
            "error": {
                "code": error.code,
                "message": error.message,
                "details": {},
            },
        }), error.status_code


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


def _decode_access_token(token: str) -> dict:
    jwks_url = current_app.config.get("SUPABASE_JWKS_URL")
    jwt_secret = current_app.config.get("SUPABASE_JWT_SECRET")

    try:
        if jwks_url:
            signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=[signing_key.algorithm_name],
                audience="authenticated",
                options={"require": ["exp", "sub", "aud"]},
            )

        if jwt_secret:
            return jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                options={"require": ["exp", "sub", "aud"]},
            )
    except PyJWKClientConnectionError as exc:
        raise AuthenticationError(
            "INTERNAL_ERROR", "Authentication service is temporarily unavailable.", 500
        ) from exc
    except jwt.PyJWTError as exc:
        # Do not return verifier details, key URLs, or token fragments.
        raise AuthenticationError(
            "UNAUTHENTICATED", "Missing or invalid authentication token.", 401
        ) from exc
    except Exception as exc:
        # Verifier outages and JWKS retrieval failures are operational errors,
        # not evidence that the caller supplied an invalid credential.
        raise AuthenticationError(
            "INTERNAL_ERROR", "Authentication service is temporarily unavailable.", 500
        ) from exc

    raise AuthenticationError(
        "INTERNAL_ERROR", "Authentication is not configured.", 500
    )


def _load_current_user() -> User:
    header = request.headers.get("Authorization", "")
    scheme, separator, token = header.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError(
            "UNAUTHENTICATED", "A bearer access token is required.", 401
        )

    claims = _decode_access_token(token.strip())
    subject = claims.get("sub")
    try:
        subject = str(UUID(subject))
    except (TypeError, ValueError, AttributeError) as exc:
        raise AuthenticationError(
            "UNAUTHENTICATED", "Missing or invalid authentication token.", 401
        ) from exc

    try:
        user = db.session.get(User, subject)
    except SQLAlchemyError as exc:
        raise AuthenticationError(
            "INTERNAL_ERROR", "Unable to authenticate this request.", 500
        ) from exc

    if user is None or not user.is_active:
        raise AuthenticationError(
            "UNAUTHENTICATED", "This account is unavailable.", 401
        )
    return user


def require_auth(view):
    """Load the active profile from Postgres and attach it to ``g.current_user``."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "current_user", None) is None:
            g.current_user = _load_current_user()
        return view(*args, **kwargs)

    return wrapped


def require_role(*allowed_roles: str):
    """Require one of the roles stored on the active database profile."""

    def decorate(view):
        @wraps(view)
        @require_auth
        def wrapped(*args, **kwargs):
            role = getattr(g.current_user.role, "value", g.current_user.role)
            if role not in allowed_roles:
                raise AuthenticationError(
                    "FORBIDDEN_ROLE", "Your role cannot perform this action.", 403
                )
            return view(*args, **kwargs)

        return wrapped

    return decorate


__all__ = [
    "AuthenticationError",
    "register_auth_error_handler",
    "require_auth",
    "require_role",
]
