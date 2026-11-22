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

    # Auto-load scam classifier (only if not already set, e.g. by test config).
    # If the model file is missing or fails to load, SCAM_CHECKER stays unset
    # so check_scam() raises ScamCheckError("AI_UNAVAILABLE", …, 502) as tests expect.
    if not app.config.get("SCAM_CHECKER"):
        try:
            from app.ai.scam_classifier import load_classifier
            clf = load_classifier()
            if clf is not None:
                app.config["SCAM_CHECKER"] = clf
        except Exception:
            pass

    # Import mappings before any service performs ORM queries. Migrations, not
    # SQLAlchemy metadata, own the database schema.
    from app import models as _models  # noqa: F401

    from app.api.auth import auth_bp
    from app.api.ai import ai_bp
    from app.api.audit import audit_bp
    from app.api.cases import cases_bp
    from app.api.citizens import citizens_bp
    from app.api.eval import eval_bp
    from app.api.mock_services import mock_services_bp
    from app.api.public import health_bp, public_bp
    from app.api.rules import rules_bp
    from app.api.sync import sync_bp
    from app.api.twin import twin_bp
    from app.api.consents import consents_bp, handle_consent_error
    from app.services.consent_service import ConsentError

    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    app.register_blueprint(ai_bp, url_prefix="/api/v1/ai")
    app.register_blueprint(audit_bp, url_prefix="/api/v1/audit-logs")
    app.register_blueprint(cases_bp, url_prefix="/api/v1/cases")
    app.register_blueprint(citizens_bp, url_prefix="/api/v1")
    app.register_blueprint(eval_bp, url_prefix="/api/v1/eval")
    app.register_blueprint(mock_services_bp, url_prefix="/api/v1/mock")
    app.register_blueprint(public_bp, url_prefix="/api/v1/public")
    app.register_blueprint(health_bp)
    app.register_blueprint(rules_bp, url_prefix="/api/v1/rules")
    app.register_blueprint(sync_bp, url_prefix="/api/v1/sync")
    app.register_blueprint(twin_bp, url_prefix="/api/v1/twin")
    app.register_blueprint(consents_bp, url_prefix="/api/v1/consents")
    app.register_error_handler(ConsentError, handle_consent_error)

    return app
