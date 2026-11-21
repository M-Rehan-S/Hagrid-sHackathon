from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from flask import Flask

from app import auth as auth_module
from app.api import citizens as citizens_api
from app.api.citizens import citizens_bp
from app.auth import register_auth_error_handler
from app.extensions import db


def _user(role="helper"):
    return SimpleNamespace(
        id=str(uuid4()), tenant_id=str(uuid4()), role=role, language="ur", is_active=True
    )


def _app(monkeypatch, actor):
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    register_auth_error_handler(flask_app)
    flask_app.register_blueprint(citizens_bp, url_prefix="/api/v1")
    monkeypatch.setattr(auth_module, "_decode_access_token", lambda _token: {"sub": actor.id})
    session = MagicMock()
    session.get.return_value = actor
    monkeypatch.setattr(db, "session", session)
    return flask_app.test_client()


def _citizen(actor):
    return SimpleNamespace(
        id=str(uuid4()), tenant_id=actor.tenant_id, user_id=None,
        full_name="Fatima Bibi", father_name=None, cnic=None, dob=date(1978, 4, 12),
        district=None, phone=None, language="ur", created_at=datetime.now(timezone.utc),
    )


def test_post_citizen_returns_created_profile_and_helper_link(monkeypatch):
    actor = _user()
    client = _app(monkeypatch, actor)
    citizen = _citizen(actor)
    link = SimpleNamespace(id=str(uuid4()), citizen_id=citizen.id, status="active", created_at=datetime.now(timezone.utc))
    create = MagicMock(return_value=(citizen, link))
    monkeypatch.setattr(citizens_api, "create_citizen", create)

    response = client.post("/api/v1/citizens", headers={"Authorization": "Bearer token"}, json={
        "full_name": "Fatima Bibi", "dob": "1978-04-12",
    })

    assert response.status_code == 201
    assert response.json["error"] is None
    assert response.json["data"]["citizen"]["id"] == citizen.id
    assert response.json["data"]["helper_link"]["status"] == "active"
    create.assert_called_once()


def test_get_citizen_returns_consent_checked_profile(monkeypatch):
    actor = _user("citizen")
    client = _app(monkeypatch, actor)
    citizen = _citizen(actor)
    get = MagicMock(return_value=citizen)
    monkeypatch.setattr(citizens_api, "get_citizen", get)

    response = client.get(
        f"/api/v1/citizens/{citizen.id}", headers={"Authorization": "Bearer token"}
    )

    assert response.status_code == 200
    assert response.json["data"]["dob"] == "1978-04-12"
    get.assert_called_once_with(actor, citizen.id)


def test_helper_link_route_matches_proposal_and_is_role_protected(monkeypatch):
    actor = _user("helper")
    client = _app(monkeypatch, actor)
    citizen_id = str(uuid4())
    link = SimpleNamespace(id=str(uuid4()), citizen_id=citizen_id, status="active", created_at=datetime.now(timezone.utc))
    create_link = MagicMock(return_value=link)
    monkeypatch.setattr(citizens_api, "link_helper_to_citizen", create_link)

    response = client.post(
        f"/api/v1/helper/citizens/{citizen_id}/link",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 201
    assert response.json["data"]["citizen_id"] == citizen_id
    create_link.assert_called_once_with(actor, citizen_id)


def test_helper_citizen_list_exposes_service_scoped_fields(monkeypatch):
    actor = _user("helper")
    client = _app(monkeypatch, actor)
    rows = [{"citizen_id": str(uuid4()), "status": "active", "created_at": datetime.now(timezone.utc)}]
    monkeypatch.setattr(citizens_api, "list_helper_citizens", lambda _actor: rows)

    response = client.get("/api/v1/helper/citizens", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    assert response.json["data"][0]["citizen_id"] == rows[0]["citizen_id"]
    assert response.json["data"][0]["created_at"].endswith("Z")

