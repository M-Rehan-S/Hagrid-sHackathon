"""Flask application factory."""

from __future__ import annotations

from flask import Flask

from app.config import Config
from app.extensions import db


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    from app.auth import register_auth_error_handler

    register_auth_error_handler(app)

    db.init_app(app)

    # Import mappings before any service performs ORM queries. Migrations, not
    # SQLAlchemy metadata, own the database schema.
    from app import models as _models  # noqa: F401

    from app.api.auth import auth_bp
    from app.api.audit import audit_bp
    from app.api.cases import cases_bp
    from app.api.consents import consents_bp, handle_consent_error
    from app.services.consent_service import ConsentError

    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    app.register_blueprint(audit_bp, url_prefix="/api/v1/audit-logs")
    app.register_blueprint(cases_bp, url_prefix="/api/v1/cases")
    app.register_blueprint(consents_bp, url_prefix="/api/v1/consents")
    app.register_error_handler(ConsentError, handle_consent_error)

    return app
