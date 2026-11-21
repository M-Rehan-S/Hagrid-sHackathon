"""Shared SQLAlchemy extension used by the Flask application and services."""

from __future__ import annotations

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    """Small SQLAlchemy 2.x session manager; schema stays migration-owned."""

    Model = Base

    def __init__(self) -> None:
        self.engine = None
        self.session = scoped_session(
            sessionmaker(autoflush=False, expire_on_commit=False)
        )

    def init_app(self, app: Flask) -> None:
        database_url = app.config.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required to initialize the database")

        if database_url.startswith("postgres://"):
            database_url = "postgresql+psycopg://" + database_url[len("postgres://") :]
        elif database_url.startswith("postgresql://"):
            database_url = "postgresql+psycopg://" + database_url[len("postgresql://") :]

        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.session.configure(bind=self.engine)
        app.extensions["db"] = self
        app.teardown_appcontext(self._remove_session)

    def _remove_session(self, _error: BaseException | None = None) -> None:
        self.session.remove()


db = Database()
