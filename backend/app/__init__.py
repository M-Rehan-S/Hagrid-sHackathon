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

    db.init_app(app)

    # Import mappings before any service performs ORM queries. Migrations, not
    # SQLAlchemy metadata, own the database schema.
    from app import models as _models  # noqa: F401

    return app
